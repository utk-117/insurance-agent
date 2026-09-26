"""v2 phase controller.

  GREET -> CONFIRM_IDENTITY -> INTAKE (5 slots, code decides) -> profile_snapshot() -> CONSULT (LLM + tools)
        -> CLOSE / WRAP_UP (code-guarded tools) -> END
Deterministic only where it must be: identity, intake slots, snapshot, and the close guards (in tools.py).
The consult conversation itself is the LLM's, with the snapshot in context and tools for detail.

  state = new_session("Rahul", "98xxxxxx")
  res = await start(state)                  # greeting, agent speaks first
  res = await handle_turn(state, "haan")    # -> {reply, reply_language, phase, events, ended, llm_ms, tool_calls}
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from datetime import datetime, timedelta
from functools import lru_cache

from app.adapters.base import LLMParseError, ProviderError, get_llm
from app.agent import actions, intake, knowledge, tools
from app.agent.money import money, money_range, parse_amount, words_in_text
from app.agent.state import IST, Phase, SessionState, now_ist

log = logging.getLogger("controller")
PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "prompts"
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "2"))
HISTORY_MSGS = int(os.getenv("HISTORY_MSGS", "20"))
LANGS = ["en-IN", "hi-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"]
CLOSE_TOOLS = {"book_callback", "share_purchase_link", "end_conversation"}
STATIC_CHUNKS = ("_intro", "How you speak", "How you sell", "Rails", "PROCESS KNOWLEDGE", "OBJECTION GUIDE",
                 "NEED FIT", "PRODUCT CARDS", "Output")

# ---- prompt files -----------------------------------------------------------------------------


@lru_cache(maxsize=None)
def md_sections(name: str) -> dict:
    """'## NAME' -> body for a prompts/*.md file; text before the first heading is under '_intro'."""
    out, key, buf = {}, "_intro", []
    for line in (PROMPTS / name).read_text().splitlines():
        if line.startswith("# "):  # file title, not prompt text
            continue
        if line.startswith("## "):
            out[key] = "\n".join(buf).strip()
            key, buf = line[3:].strip(), []
        else:
            buf.append(line)
    out[key] = "\n".join(buf).strip()
    return out


def fill(template: str, **vals) -> str:
    """Replace {name} placeholders that we have values for; leave any other braces alone."""
    return re.sub(r"\{(\w+)\}", lambda m: str(vals[m.group(1)]) if m.group(1) in vals else m.group(0), template)


def snippet(name: str, **vals) -> str:
    return fill(md_sections("controller.md")[name], **vals)


def brand() -> str:
    return os.getenv("BRAND_NAME", "Suraksha Advisory")


# ---- time & language helpers (kept from v1) ---------------------------------------------------

YES_RE = re.compile(r"^\W*(yes|yeah|yep|yup|sure|ok|okay|haan|han|ha|ji|ji haan|theek|thik|bilkul|correct|right|"
                    r"that'?s right|sahi|done|fine|chalega|go ahead|please do|perfect|great)\b", re.I)
NO_RE = re.compile(r"^\W*(no|nope|nah|nahi|nahin|na|not really|galat|wrong)\b", re.I)
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "somvar": 0, "mangalvar": 1, "budhvar": 2, "guruvar": 3, "shukravar": 4, "shanivar": 5, "ravivar": 6}
PM_WORDS = ("pm", "p.m", "shaam", "sham", "evening", "raat", "night", "dopahar", "afternoon")
AM_WORDS = ("am", "a.m", "subah", "morning")
HINDI_WORDS = re.compile(r"\b(hai|hain|nahi|nahin|kya|mera|meri|mujhe|aap|aapka|haan|kal|baje|mein|hoon|"
                         r"kar|karo|chahiye|theek|bhi|toh|kaise|kitna|lagega|batao|bataiye|ji|abhi|wala|wali)\b", re.I)


def parse_time_text(text: str | None, now: datetime | None = None):
    """Fallback resolver for 'tomorrow 5 pm' / 'kal shaam 5 baje' / 'Saturday 11 am' -> future IST datetime."""
    if not text:
        return None
    t, now = text.lower(), now or now_ist()
    m = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.?|p\.m\.?|baje|bje|o'?clock)", t) or \
        re.search(r"\bat\s+(\d{1,2})(?:[:.](\d{2}))?\b", t)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    if any(w in t for w in PM_WORDS) and hour < 12:
        hour += 12
    elif any(re.search(rf"\b{re.escape(w)}", t) for w in AM_WORDS):
        hour = 0 if hour == 12 else hour
    elif hour < 8:  # "5 baje" with no am/pm: assume business hours
        hour += 12
    day = None
    if re.search(r"\b(day after tomorrow|parso|parson)\b", t):
        day = now.date() + timedelta(days=2)
    elif re.search(r"\b(tomorrow|kal)\b", t):
        day = now.date() + timedelta(days=1)
    elif re.search(r"\b(today|aaj)\b", t):
        day = now.date()
    for w, i in WEEKDAYS.items():
        if re.search(rf"\b{w}\b", t):
            day = now.date() + timedelta(days=((i - now.weekday()) % 7) or 7)
    if day is None:
        day = now.date() if (hour, minute) > (now.hour, now.minute) else now.date() + timedelta(days=1)
    dt = datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)
    return dt if dt > now else None


def redact_phone(text: str, phone: str | None) -> str:
    """Safety net: the model never gets the number, but never speak it (or any phone-like digit run) anyway."""
    words = snippet("PHONE_WORDS")
    if phone:
        digits = re.sub(r"\D", "", phone)[-10:]
        if len(digits) >= 8:
            text = re.sub(r"[\s-]?".join(digits), words, text)
    return re.sub(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", words, text)


def text_language(text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "Hindi (Devanagari)"
    hits = len(HINDI_WORDS.findall(text or ""))
    return "Hinglish" if hits >= 2 or (hits == 1 and len((text or "").split()) <= 3) else "English"


def customer_language(state: SessionState) -> str:
    """Language of the customer's last real sentence (a bare "36" or "male" doesn't switch it)."""
    users = [t for t in state.transcript if t["role"] == "user"]
    last = next((t for t in reversed(users) if len(t["text"].split()) >= 2), users[-1] if users else None)
    if not last:
        return "unknown"
    lang = text_language(last["text"])
    if lang == "English" and last.get("lang") and last["lang"] not in ("en-IN", None):
        return last["lang"]
    return lang


def reply_lang_code(reply: str) -> str:
    return "en-IN" if text_language(reply) == "English" else "hi-IN"


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%A, %d %B %Y, %I:%M %p")


def _week(now: datetime) -> str:
    return ", ".join((now + timedelta(days=d)).strftime("%A %d %B")
                     + (" (today)" if d == 0 else " (tomorrow)" if d == 1 else "") for d in range(8))


# ---- prompt assembly --------------------------------------------------------------------------

def _label(pid):
    c = knowledge.cards()[pid]
    return f"{c['insurer']} {c['name']} [{pid}]"


def _snapshot_text(state: SessionState) -> str:
    """The snapshot as the LLM sees it: every rupee amount already in words (it misreads raw integers by 10x)."""
    s = state.snapshot
    if not s:
        return "(after intake)"
    prof = dict(s["profile"])
    prof["annual_income"] = money(prof.pop("annual_income_inr", None)) or "not working"
    eligible = []
    for e in s["eligible"]:
        item = {"product": _label(e["product_id"]), "type": e["type"]}
        if "quotes" in e:
            item["min_cover"] = money(e["min_cover"])
            item["price_ranges"] = []
            for q in e["quotes"]:
                pr = {"cover": money(q["sum_assured"]),
                      "indicative_premium": money_range(*q["annual_premium_range"])}
                if q.get("salaried_first_year_discount"):
                    pr["salaried_discount"] = f"{q['salaried_first_year_discount'] * 100:g}% off the first year only"
                if q.get("note"):
                    pr["note"] = q["note"]
                item["price_ranges"].append(pr)
        else:
            item["pricing"] = e.get("pricing")
        eligible.append(item)
    compact = {"profile": prof, "max_cover": money(s["max_cover"]) if s["max_cover"] else None,
               "max_cover_rule": s["max_cover_rule"], "eligible": eligible,
               "excluded": [{"product": _label(x["product_id"]), "reason": words_in_text(x["reason"], bare=True)}
                            for x in s["excluded"]],
               "not_working_options": s.get("not_working_options"), "disclaimer": s["disclaimer"]}
    return json.dumps(compact, ensure_ascii=False)


def _claims_text(state: SessionState) -> str:
    if not state.snapshot:
        return "(after intake)"
    insurers = [knowledge.cards()[e["product_id"]]["insurer"] for e in state.snapshot["eligible"]]
    rows = knowledge.claims_record(list(dict.fromkeys(insurers)))
    meta = json.loads((knowledge.K / "claims_history.json").read_text())["_meta"]
    return json.dumps({"how_to_speak": meta["how_to_speak"], "rows": rows}, ensure_ascii=False) if rows else "(none)"


def _intake_text(state: SessionState, parsed: dict) -> str:
    p = state.profile
    nxt = intake.next_slot(p)
    q = intake.question(nxt) if nxt else {"ask_en": "", "ask_hi": ""}
    english = customer_language(state) in ("English", "unknown")
    ask = q["ask_en"] if english else q["ask_hi"]
    if nxt == "gender" and state.gender_hint in ("male", "female"):
        ask = snippet("GENDER_CONFIRM_EN" if english else "GENDER_CONFIRM_HI", gender=state.gender_hint)
    return snippet("INTAKE_STATE",
                   known=json.dumps({k: v for k, v in p.items() if v is not None}) or "{}",
                   parsed=json.dumps(parsed) if parsed else "nothing",
                   missing=", ".join(intake.missing(p)) or "none",
                   next_slot=nxt or "none (intake complete)", ask=ask)


def _prefetch_text(state: SessionState, text: str) -> str:
    """v1 topic router as a prefetch: sections the customer's words clearly name, for the product in focus."""
    if not state.snapshot:
        return ""
    focus = knowledge.match_products(text) + state.discussed_products[-1:]
    route = knowledge.route_topics(text, {"product_refs": list(dict.fromkeys(focus))[:2]})
    parts = []
    for pid, topics in route["products"].items():
        asked = [t for t in topics if t in route["matched_topics"]][:3]
        for s in knowledge.get_sections(pid, asked):
            parts.append(f"### {_label(pid)} — {s['topic']} (pages {s.get('pages')})\n"
                         f"{(s.get('text') or '')[:tools.SECTION_CHARS]}")
        for t in route["unavailable"].get(pid, []):
            parts.append(f"### {_label(pid)} — {t}: not covered in this brochure.")
    for slug in route["claims_fallback"]:
        parts.append(knowledge.insurer_notes(slug, "Death claims"))
    return snippet("PREFETCHED", sections="\n\n".join(parts)) if parts else ""


def _current_turn(state: SessionState, text: str = "") -> str:
    now = now_ist()
    extra = []
    if state.phase in (Phase.CONSULT, Phase.CLOSE, Phase.WRAP_UP):
        dt = parse_time_text(text)
        if dt:
            extra.append(snippet("RESOLVED_TIME", when=f"{dt:%A, %d %B at %I:%M %p}", iso=dt.isoformat()))
            if not tools.in_callback_hours(dt):
                extra.append(snippet("OUTSIDE_HOURS", hours=tools.CALLBACK_HOURS_TEXT))
        amount = parse_amount(text) if not dt else None
        if amount:
            extra.append(snippet("RESOLVED_AMOUNT", amount=money(amount)))
        if state.quoted:
            quoted = "; ".join(f"{_label(q['product_id'])}: {money(q['sum_assured'])} cover -> "
                               f"{money_range(*q['range'])}" for q in state.quoted[-6:])
            extra.append(snippet("QUOTED", quoted=quoted))
        pre = _prefetch_text(state, text)
        if pre:
            extra.append(pre)
    return snippet("CURRENT_TURN", now_ist=_fmt_time(now), week=_week(now), language=customer_language(state),
                   extra="\n".join(extra))


def phase_guide(state: SessionState, phase: Phase) -> str:
    key = "CONSULT_OPEN" if phase == Phase.CONSULT and not state.consult_opened else phase.value
    return fill(md_sections("phases.md")[key], brand_name=brand(), lead_name=state.lead.get("name"))


def build_system(state: SessionState, phase: Phase, output: str, text: str = "", parsed: dict | None = None) -> list:
    """[static block (cacheable), dynamic block]. Static = persona, rails, knowledge; dynamic = phase + turn."""
    consult = phase in (Phase.CONSULT, Phase.CLOSE, Phase.WRAP_UP)
    start = datetime.fromisoformat(state.started_at)
    if phase == Phase.INTAKE:
        intake_state = _intake_text(state, parsed or {})
    else:
        intake_state = "(done)" if state.snapshot else "(not started)"
    vals = dict(
        brand_name=brand(), lead_name=state.lead.get("name"),
        now_ist=_fmt_time(start), calendar=f"CALENDAR: {_week(start)}.",
        language="see CURRENT TURN below",
        phase=phase.value if phase != Phase.CONSULT or state.consult_opened else "CONSULT (opening)",
        phase_guide=phase_guide(state, phase), intake_state=intake_state,
        snapshot=_snapshot_text(state), claims_records=_claims_text(state),
        buying_process=knowledge.buying_process(),
        objection_guide=(PROMPTS / "objections.md").read_text() if consult else "(Phase 2)",
        need_fit=json.dumps(knowledge.need_fit(), ensure_ascii=False, separators=(",", ":")) if consult
        else "(Phase 2)",
        product_cards=json.dumps(knowledge.prompt_cards(), ensure_ascii=False, separators=(",", ":")),
        output_instructions=output,
    )
    static, dynamic = [], []
    for name, body in md_sections("system.md").items():
        chunk = (f"## {name}\n" if name != "_intro" else "") + fill(body, **vals)
        (static if name.startswith(STATIC_CHUNKS) else dynamic).append(chunk)
    dynamic.append("## CURRENT TURN\n" + _current_turn(state, text))
    return [{"text": "\n\n".join(static), "cache": True}, {"text": "\n\n".join(dynamic), "cache": False}]


def build_messages(state: SessionState) -> list:
    msgs = [{"role": "user", "content": snippet("GREET_TRIGGER")}]
    tr = state.transcript
    start = max(0, len(tr) - HISTORY_MSGS)
    if start > 0 and tr[start]["role"] == "user":
        start -= 1
    for t in tr[start:]:
        msgs.append({"role": "assistant" if t["role"] == "agent" else "user", "content": t["text"]})
    return msgs


# ---- JSON phases: greet, identity, intake ------------------------------------------------------

SIMPLE_SCHEMA = {"type": "object", "properties": {
    "reply": {"type": "string"}, "reply_language": {"type": "string", "enum": LANGS},
    "intent": {"type": "string", "enum": ["confirm_yes", "confirm_no", "wrong_person", "not_interested", "question",
                                          "unclear"]}},
    "required": ["reply", "reply_language", "intent"]}
INTAKE_SCHEMA = {"type": "object", "properties": {
    "reply": {"type": "string"}, "reply_language": {"type": "string", "enum": LANGS},
    "extracted": {"type": "object", "properties": {
        "age": {"type": ["integer", "null"]},
        "gender": {"type": ["string", "null"], "enum": ["male", "female", "other", None]},
        "employment_type": {"type": ["string", "null"], "enum": intake.EMPLOYMENT + [None]},
        "annual_income_inr": {"type": ["integer", "null"]}, "tobacco": {"type": ["boolean", "null"]}}},
    "intent": {"type": "string", "enum": ["answered", "question", "not_interested", "wrong_person", "unclear"]}},
    "required": ["reply", "reply_language", "extracted", "intent"]}
SUMMARY_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"}, "intents": {"type": "array", "items": {"type": "string"}},
    "objections": {"type": "array", "items": {"type": "string"}}}, "required": ["summary"]}


async def _json_call(state: SessionState, system: list, schema: dict):
    state.metrics["llm_calls"] += 1
    try:
        r = await get_llm(state.llm_provider).complete_json(system, build_messages(state), schema)
    except (LLMParseError, ProviderError) as e:
        log.warning(json.dumps({"event": "llm_failed", "session": state.session_id, "error": str(e)[:300]}))
        state.metrics["parse_fallbacks"] += 1
        return None, 0
    state.metrics["input_tokens"] += r["input_tokens"] or 0
    state.metrics["output_tokens"] += r["output_tokens"] or 0
    d = r["data"]
    if not isinstance(d.get("reply"), str) or not d["reply"].strip():
        state.metrics["parse_fallbacks"] += 1
        return None, r["provider_ms"]
    d["reply"] = d["reply"].strip()
    if d.get("reply_language") not in LANGS:
        d["reply_language"] = reply_lang_code(d["reply"])
    return d, r["provider_ms"]


def _not_interested(state: SessionState):
    """One soft retry, then end (code-side, so a no is always respected)."""
    if state.soft_retry_used:
        state.outcome, state.phase = "not_interested", Phase.END
    state.soft_retry_used = True


async def _identity_turn(state: SessionState, text: str) -> tuple:
    d, ms = await _json_call(state, build_system(state, state.phase, snippet("OUTPUT_SIMPLE"), text), SIMPLE_SCHEMA)
    if d is None:
        return None, None, ms
    intent = d.get("intent")
    if intent == "wrong_person" or (intent == "confirm_no" and NO_RE.match(text)):
        state.outcome, state.phase = "wrong_person", Phase.END
    elif intent == "not_interested":
        _not_interested(state)
    elif intent != "unclear" or YES_RE.match(text):
        state.phase = Phase.INTAKE
    return d["reply"], d["reply_language"], ms


def _apply_slots(state: SessionState, values: dict) -> dict:
    changed = {}
    for slot, v in values.items():
        if slot in intake.SLOTS and state.profile.get(slot) is None and v is not None:
            state.profile[slot] = v
            changed[slot] = v
    if state.profile.get("employment_type") == "not_working":
        state.profile["annual_income_inr"] = None
        changed.pop("annual_income_inr", None)
    return changed


def _gender_turn(state: SessionState, text: str, parsed: dict):
    """Gender is filled only by an explicit answer or a confirmed hint. A hint ('bol raha hoon', even from the
    identity check) makes Asha ask 'I'm assuming you're male, is that right?' instead of asking cold."""
    if state.profile.get("gender") is not None:
        return
    hint = state.gender_hint
    if hint in ("male", "female") and state.asked_slot == "gender":
        if YES_RE.match(text) and not NO_RE.match(text):
            parsed.update(_apply_slots(state, {"gender": hint}))
            return
        if NO_RE.match(text):
            state.gender_hint = "rejected"
    if state.gender_hint is None:
        state.gender_hint = next((intake.gender_hint(t["text"]) for t in state.transcript
                                  if t["role"] == "user" and intake.gender_hint(t["text"])), None)


def _finish_intake(state: SessionState):
    state.snapshot = knowledge.profile_snapshot(dict(state.profile))
    state.phase = Phase.CONSULT
    log.info(json.dumps({"event": "snapshot", "session": state.session_id, "profile": state.profile,
                         "max_cover": state.snapshot["max_cover"],
                         "eligible": [e["product_id"] for e in state.snapshot["eligible"]],
                         "excluded": [x["product_id"] for x in state.snapshot["excluded"]]}, ensure_ascii=False))


async def _intake_turn(state: SessionState, text: str, on_tool_round=None) -> tuple:
    parsed = _apply_slots(state, intake.parse_turn(text, state.profile))
    _gender_turn(state, text, parsed)
    if not intake.missing(state.profile):
        _finish_intake(state)
        return await _consult_turn(state, text, on_tool_round)
    output = snippet("OUTPUT_INTAKE", schema=json.dumps(INTAKE_SCHEMA["properties"], separators=(",", ":")))
    d, ms = await _json_call(state, build_system(state, Phase.INTAKE, output, text, parsed), INTAKE_SCHEMA)
    if d is None:
        return None, None, ms, []
    ex = d.get("extracted") if isinstance(d.get("extracted"), dict) else {}
    _apply_slots(state, {s: intake.clean_llm_value(s, ex.get(s)) for s in intake.SLOTS})
    if d.get("intent") == "wrong_person":
        state.outcome, state.phase = "wrong_person", Phase.END
    elif d.get("intent") == "not_interested":
        _not_interested(state)
    if state.phase == Phase.INTAKE and not intake.missing(state.profile):
        # the LLM caught the last slot that code missed: its reply asked the wrong thing, so open the consult now
        _finish_intake(state)
        reply, lang, ms2, calls = await _consult_turn(state, text, on_tool_round)
        return reply, lang, ms + ms2, calls
    state.asked_slot = intake.next_slot(state.profile)
    return d["reply"], d["reply_language"], ms, []


# ---- consult: tool loop -----------------------------------------------------------------------

async def _consult_turn(state: SessionState, text: str, on_tool_round=None) -> tuple:
    """LLM + tools, max MAX_TOOL_ROUNDS rounds, then the model must answer. Returns (reply, lang, ms, calls)."""
    if state.phase == Phase.CONSULT and state.consult_opened and parse_time_text(text):
        state.phase = Phase.CLOSE
    llm = get_llm(state.llm_provider)
    state.metrics["tool_mode"] = getattr(llm, "tool_mode", "native")
    system = build_system(state, state.phase, snippet("OUTPUT_CONSULT"), text)
    msgs, specs, total_ms, turn_calls, reply = build_messages(state), tools.tool_specs(), 0, [], None
    for rnd in range(MAX_TOOL_ROUNDS + 1):
        allow = rnd < MAX_TOOL_ROUNDS and state.phase != Phase.END
        state.metrics["llm_calls"] += 1
        try:
            r = await llm.chat_with_tools(system, msgs, specs, allow_tools=allow)
        except (LLMParseError, ProviderError) as e:
            log.warning(json.dumps({"event": "llm_failed", "session": state.session_id, "error": str(e)[:300]}))
            state.metrics["parse_fallbacks"] += 1
            break
        total_ms += r["provider_ms"]
        state.metrics["input_tokens"] += r["input_tokens"] or 0
        state.metrics["output_tokens"] += r["output_tokens"] or 0
        calls = r["tool_calls"] if allow else [c for c in r["tool_calls"] if c["name"] in CLOSE_TOOLS]
        if not calls:
            reply = r["reply"]
            break
        state.metrics["tool_rounds"] += 1
        if on_tool_round:
            await on_tool_round(rnd, total_ms)
        msgs.append({"role": "assistant", "content": r["reply"], "tool_calls": calls, "raw": r.get("raw")})
        for c in calls:
            res = tools.run(state, c["name"], c["args"])
            turn_calls.append({"name": c["name"], "ok": res["ok"]})
            if c["name"] == "book_callback" and state.phase == Phase.CONSULT:
                state.phase = Phase.CLOSE
            msgs.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                         "content": json.dumps(res, ensure_ascii=False, default=str)})
        if state.phase == Phase.END:  # ended: speak the goodbye, no further LLM call
            reply = state.goodbye or r["reply"]
            if reply:
                break
        elif not allow and r["reply"]:
            reply = r["reply"]
            break
    state.consult_opened = True
    if not reply:
        return None, None, total_ms, turn_calls
    return reply, reply_lang_code(reply), total_ms, turn_calls


# ---- public API -------------------------------------------------------------------------------

def new_session(name: str, phone: str, llm_provider: str | None = None) -> SessionState:
    return SessionState(lead={"name": name, "phone": phone}, llm_provider=llm_provider)


async def start(state: SessionState) -> dict:
    """Agent speaks first: GREET, then wait in CONFIRM_IDENTITY."""
    d, ms = await _json_call(state, build_system(state, Phase.GREET, snippet("OUTPUT_SIMPLE")), SIMPLE_SCHEMA)
    reply = d["reply"] if d else snippet("FALLBACK_GREETING", brand_name=brand(), lead_name=state.lead.get("name"))
    lang = d["reply_language"] if d else "en-IN"
    state.add("agent", reply, lang)
    state.phase = Phase.CONFIRM_IDENTITY
    return {"reply": reply, "reply_language": lang, "phase": state.phase.value, "stage": state.phase.value,
            "events": [], "ended": False, "llm_ms": ms, "tool_calls": []}


async def handle_turn(state: SessionState, text: str, lang: str | None = None, on_tool_round=None) -> dict:
    state.add("user", text, lang)
    phase_in, calls = state.phase, []
    if state.phase in (Phase.GREET, Phase.CONFIRM_IDENTITY):
        reply, rlang, ms = await _identity_turn(state, text)
    elif state.phase == Phase.INTAKE:
        reply, rlang, ms, calls = await _intake_turn(state, text, on_tool_round)
    else:
        reply, rlang, ms, calls = await _consult_turn(state, text, on_tool_round)
    fallback = reply is None
    if fallback:
        reply, rlang = snippet("FALLBACK_REPLY"), "en-IN"
    reply = redact_phone(reply, state.lead.get("phone"))
    state.add("agent", reply, rlang)
    events, state.events = state.events, []
    state.latencies.append({"llm_ms": ms})
    state.turn_log.append({"phase_in": phase_in.value, "phase_out": state.phase.value, "tool_calls": calls,
                           "llm_ms": ms, "fallback": fallback})
    log.info(json.dumps({"event": "turn", "session": state.session_id, "phase_in": phase_in.value,
                         "phase_out": state.phase.value, "profile": state.profile, "tool_calls": calls,
                         "llm_ms": ms}, ensure_ascii=False))
    ended = state.phase == Phase.END
    if ended:
        await finish(state)
        events.append({"type": "end", "outcome": state.outcome})
    return {"reply": reply, "reply_language": rlang, "phase": state.phase.value, "stage": state.phase.value,
            "events": events, "ended": ended, "llm_ms": ms, "tool_calls": calls}


async def finish(state: SessionState) -> str:
    """Summary (+ intents / objections for the sheet) and the final lead row. Safe to call more than once."""
    if not state.outcome:
        state.outcome = "dropped"
    if not state.summary and len(state.transcript) > 1:
        convo = "\n".join(f"{t['role']}: {t['text']}" for t in state.transcript)
        try:
            r = await get_llm(state.llm_provider).complete_json(
                snippet("SUMMARY"), [{"role": "user", "content": f"OUTCOME: {state.outcome}\n\n{convo}"}],
                SUMMARY_SCHEMA)
            d = r["data"]
            state.summary = str(d.get("summary", ""))[:300]
            state.intents = [str(x)[:80] for x in d.get("intents") or []][:6]
            state.objections = [str(x)[:80] for x in d.get("objections") or []][:6]
        except (LLMParseError, ProviderError) as e:
            log.warning("summary failed: %s", e)
    state.phase = Phase.END
    return actions.log_outcome(state)
