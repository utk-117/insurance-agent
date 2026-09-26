"""Stage machine. One LLM call per customer turn (plus at most one follow-up for a router miss or a
newly detected objection). The LLM only writes the reply and extracts fields; this module applies the
fields, decides the next stage, loads knowledge for the prompt and runs actions.

  state = new_session("Rahul", "98xxxxxx")
  res = await start(state)                  # greeting, agent speaks first
  res = await handle_turn(state, "haan")    # -> {reply, reply_language, stage, events, ended, llm_ms}
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from datetime import datetime, timedelta
from functools import lru_cache
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.adapters.base import LLMParseError, ProviderError, get_llm
from app.agent import actions, knowledge
from app.agent.state import IST, Stage, SessionState, now_ist

log = logging.getLogger("controller")
PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "prompts"

INTENTS = ["answered", "question", "objection", "wants_to_buy_now", "wants_callback", "asks_price",
           "confirm_yes", "confirm_no", "not_interested", "wrong_person", "unclear", "off_topic"]
OBJECTIONS = ["too_expensive", "already_covered", "think_about_it", "claims_distrust", "no_money_back",
              "trust_online", "not_now", "medical_worry", "other"]
LANGS = ["en-IN", "hi-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"]
GOAL_IDS = ["pure_protection", "savings_protection", "child_future", "retirement"]
DEPENDENTS = ["none", "spouse", "spouse+kids", "parents"]
INCOME_BANDS = ["<5L", "5–10L", "10–25L", "25L+"]
EXTRACT_FIELDS = ["age", "gender", "city", "goal", "preferred_insurer", "motivation", "primary_need",
                  "dependents", "income_band", "selected_product", "callback_time_text", "callback_time_iso"]
POST_IDENTITY = {Stage.DISCOVERY, Stage.NEED_CHECK, Stage.RECOMMEND, Stage.QA, Stage.OBJECTION, Stage.CLOSE,
                 Stage.PURCHASE_LINK, Stage.CALLBACK, Stage.WRAP_UP}
SECTIONS_BUDGET = int(os.getenv("SECTIONS_CHAR_BUDGET", "24000"))
SECTION_MAX = int(os.getenv("SECTION_CHAR_MAX", "12000"))
HISTORY_MSGS = int(os.getenv("HISTORY_MSGS", "16"))
MAX_DISCOVERY_TURNS = 10

# ---- prompt files -----------------------------------------------------------------------------


@lru_cache(maxsize=None)
def md_sections(name: str) -> dict:
    """'## NAME' -> body for a prompts/*.md file; text before the first heading is under '_intro'."""
    text = (PROMPTS / name).read_text()
    out, key, buf = {}, "_intro", []
    for line in text.splitlines():
        if line.startswith("# "):  # file title, not prompt text
            continue
        if line.startswith("## "):
            out[key] = "\n".join(buf).strip()
            key, buf = line[3:].strip(), []
        else:
            buf.append(line)
    out[key] = "\n".join(buf).strip()
    return out


@lru_cache(maxsize=None)
def prompt_file(name: str) -> str:
    return (PROMPTS / name).read_text()


def fill(template: str, **vals) -> str:
    """Replace {name} placeholders that we have values for; leave any other braces alone."""
    return re.sub(r"\{(\w+)\}", lambda m: str(vals[m.group(1)]) if m.group(1) in vals else m.group(0), template)


def snippet(name: str, **vals) -> str:
    return fill(md_sections("controller.md")[name], **vals)


def stage_text(stage: Stage) -> str:
    stages = md_sections("stages.md")
    if stage == Stage.END:
        return ""
    return stages[stage.value]


# ---- LLM turn contract ------------------------------------------------------------------------

def _nullish(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in ("", "null", "none", "unknown", "n/a", "na") else s


class Extracted(BaseModel):
    model_config = ConfigDict(extra="ignore")
    age: Optional[int] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    goal: Optional[str] = None
    preferred_insurer: Optional[str] = None
    motivation: Optional[str] = None
    primary_need: Optional[str] = None
    dependents: Optional[str] = None
    income_band: Optional[str] = None
    selected_product: Optional[str] = None
    callback_time_text: Optional[str] = None
    callback_time_iso: Optional[str] = None

    @field_validator("age", mode="before")
    @classmethod
    def _age(cls, v):
        try:
            a = int(float(str(v).strip()))
            return a if 0 <= a <= 110 else None
        except (TypeError, ValueError):
            return None

    @field_validator("gender", "city", "goal", "preferred_insurer", "motivation", "primary_need", "income_band",
                     "selected_product", "callback_time_text", "callback_time_iso", mode="before")
    @classmethod
    def _str(cls, v):
        return _nullish(v)

    @field_validator("dependents", mode="before")
    @classmethod
    def _dep(cls, v):  # "none" is a real answer here
        return None if v is None or str(v).strip().lower() in ("", "null", "unknown") else str(v).strip()


class TurnOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reply: str
    reply_language: str = "en-IN"
    extracted: Extracted = Extracted()
    objection_type: Optional[str] = None
    intent: str = "unclear"
    product_refs: List[str] = []
    topics_needed: List[str] = []

    @field_validator("reply")
    @classmethod
    def _reply(cls, v):
        if not v or not v.strip():
            raise ValueError("empty reply")
        return v.strip()

    @field_validator("reply_language", mode="before")
    @classmethod
    def _lang(cls, v):
        return v if v in LANGS else "en-IN"

    @field_validator("extracted", mode="before")
    @classmethod
    def _ex(cls, v):
        return v if isinstance(v, dict) else {}

    @field_validator("intent", mode="before")
    @classmethod
    def _intent(cls, v):
        return v if v in INTENTS else "unclear"

    @field_validator("objection_type", mode="before")
    @classmethod
    def _obj(cls, v):
        v = _nullish(v)
        return None if v is None else (v if v in OBJECTIONS else "other")

    @field_validator("product_refs", mode="before")
    @classmethod
    def _refs(cls, v):
        out = []
        for x in v if isinstance(v, list) else []:
            pid = x if x in knowledge.cards() else next(iter(knowledge.match_products(str(x))), None)
            if pid and pid not in out:
                out.append(pid)
        return out

    @field_validator("topics_needed", mode="before")
    @classmethod
    def _topics(cls, v):
        known = set(knowledge.router()["keywords"]) | set(knowledge.router()["core_topics"])
        return [t for t in (v if isinstance(v, list) else []) if t in known]


def _nullable(enum=None):
    s = {"type": ["string", "null"]}
    if enum:
        s["enum"] = enum + [None]
    return s


@lru_cache(maxsize=None)
def turn_schema() -> dict:
    extracted = {f: _nullable() for f in EXTRACT_FIELDS}
    extracted["age"] = {"type": ["integer", "null"]}
    extracted["goal"] = _nullable(GOAL_IDS)
    extracted["dependents"] = _nullable(DEPENDENTS)
    extracted["income_band"] = _nullable(INCOME_BANDS)
    extracted["primary_need"] = _nullable(list(knowledge.need_fit()["needs"]))
    extracted["selected_product"] = _nullable(list(knowledge.cards()))
    extracted["gender"] = _nullable(["male", "female", "other"])
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "reply_language": {"type": "string", "enum": LANGS},
            "extracted": {"type": "object", "properties": extracted, "required": EXTRACT_FIELDS,
                          "additionalProperties": False},
            "objection_type": _nullable(OBJECTIONS),
            "intent": {"type": "string", "enum": INTENTS},
            "product_refs": {"type": "array", "items": {"type": "string"}},
            "topics_needed": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["reply", "reply_language", "extracted", "objection_type", "intent", "product_refs",
                     "topics_needed"],
        "additionalProperties": False,
    }


SUMMARY_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"],
                  "additionalProperties": False}

# ---- normalising extracted fields -------------------------------------------------------------


def norm_goal(v):
    s = v.lower()
    if s in GOAL_IDS:
        return s
    if "child" in s or "bach" in s:
        return "child_future"
    if "retire" in s or "pension" in s:
        return "retirement"
    if "saving" in s:
        return "savings_protection"
    if "protect" in s or "term" in s:
        return "pure_protection"
    return None


def norm_income(v):
    s = v.lower().replace(" ", "").replace("lakhs", "l").replace("lakh", "l").replace("lac", "l").replace("-", "–")
    if s in [b.lower() for b in INCOME_BANDS]:
        return INCOME_BANDS[[b.lower() for b in INCOME_BANDS].index(s)]
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s)]
    if not nums:
        return None
    n = max(nums) if any(w in s for w in ("+", "above", "more", "over")) else nums[-1]
    if any(w in s for w in ("<", "below", "under", "less")):
        n = n - 0.01
    if "cr" in s:
        n *= 100
    if n < 5:
        return "<5L"
    if n < 10 or (len(nums) == 2 and nums == [5.0, 10.0]):
        return "5–10L"
    if n < 25 or (len(nums) == 2 and nums == [10.0, 25.0]):
        return "10–25L"
    return "25L+"


def norm_dependents(v):
    s = v.lower()
    if s in DEPENDENTS:
        return s
    if any(w in s for w in ("kid", "child", "bach", "son", "daughter")):
        return "spouse+kids"
    if any(w in s for w in ("parent", "mother", "father", "maa", "papa")):
        return "parents"
    if any(w in s for w in ("spouse", "wife", "husband", "patni", "pati")):
        return "spouse"
    if s in ("no", "nobody", "no one", "koi nahi", "single"):
        return "none"
    return None


def norm_gender(v):
    s = v.lower()
    if s.startswith("f") or s in ("woman", "lady", "mahila"):
        return "female"
    if s.startswith("m") or s in ("man", "purush"):
        return "male"
    return "other" if s == "other" else None


def parse_callback(iso: str | None):
    """ISO string -> aware IST datetime in the future, else None."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    dt = dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)
    return dt if dt > now_ist() else None


YES_RE = re.compile(r"^\W*(yes|yeah|yep|yup|sure|ok|okay|haan|han|ha|ji|ji haan|theek|thik|bilkul|correct|right|"
                    r"that'?s right|sahi|done|fine|chalega|go ahead|please do)\b", re.I)
NO_RE = re.compile(r"^\W*(no|nope|nah|nahi|nahin|na|not really|galat|wrong)\b", re.I)
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "somvar": 0, "mangalvar": 1, "budhvar": 2, "guruvar": 3, "shukravar": 4, "shanivar": 5, "ravivar": 6}
PM_WORDS = ("pm", "p.m", "shaam", "sham", "evening", "raat", "night", "dopahar", "afternoon")
AM_WORDS = ("am", "a.m", "subah", "morning")


def parse_time_text(text: str | None, now: datetime | None = None):
    """Fallback resolver for 'tomorrow 5 pm' / 'kal shaam 5 baje' / 'Saturday 11 am'. Returns a future IST
    datetime or None. Used only when the LLM didn't return callback_time_iso."""
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


HINDI_WORDS = re.compile(r"\b(hai|hain|nahi|nahin|kya|mera|meri|mujhe|aap|aapka|haan|kal|baje|mein|hoon|"
                         r"kar|karo|chahiye|theek|bhi|toh|kaise|kitna|lagega|batao|bataiye|ji|abhi|wala|wali)\b", re.I)


def customer_language(state: SessionState) -> str:
    """Language of the customer's last message: STT language_code if we have one, else a script/word heuristic."""
    last = next((t for t in reversed(state.transcript) if t["role"] == "user"), None)
    if not last:
        return "unknown"
    text = last["text"]
    if re.search(r"[\u0900-\u097F]", text):
        return "Hindi (Devanagari)"
    hits = len(HINDI_WORDS.findall(text))
    if hits >= 2 or (hits == 1 and len(text.split()) <= 3):
        return "Hinglish"
    if last.get("lang") and last["lang"] != "en-IN":
        return last["lang"]
    return "English"


def is_yes(out, text: str) -> bool:
    return out.intent == "confirm_yes" or (out.intent in ("answered", "unclear", "question", "wants_callback")
                                           and bool(YES_RE.match(text or "")) and not NO_RE.match(text or ""))


def is_no(out, text: str) -> bool:
    return out.intent == "confirm_no" or (out.intent in ("answered", "unclear") and bool(NO_RE.match(text or "")))


FEMALE_FORMS = re.compile(r"\b(rahi|rehti|rahti|karti|chahti|sakti|gayi|jaati|leti|deti|sochti|hoti) (hoon|hun|hu)\b", re.I)
MALE_FORMS = re.compile(r"\b(raha|rehta|rahta|karta|chahta|sakta|gaya|jaata|leta|deta|sochta|hota) (hoon|hun|hu)\b", re.I)


def infer_gender(state: SessionState):
    """Hindi first-person verb endings reveal gender ("bol rahi hoon"); saves an awkward question."""
    if state.profile.get("gender"):
        return None
    for t in state.transcript:
        if t["role"] == "user":
            if FEMALE_FORMS.search(t["text"]):
                return "female"
            if MALE_FORMS.search(t["text"]):
                return "male"
    return None


def apply_extracted(state: SessionState, ex: Extracted) -> dict:
    """Write cleaned values into state.profile; returns {field: new_value} for what changed."""
    p, changed = state.profile, {}
    g = infer_gender(state)
    if g:
        p["gender"] = changed["gender"] = g
    cleaners = {"goal": norm_goal, "income_band": norm_income, "dependents": norm_dependents,
                "gender": norm_gender, "preferred_insurer": knowledge.match_insurer,
                "primary_need": lambda v: v if v in knowledge.need_fit()["needs"] else None}
    for f in ["age", "gender", "city", "goal", "dependents", "income_band", "motivation", "primary_need",
              "preferred_insurer"]:
        v = getattr(ex, f)
        if v is None:
            continue
        v = cleaners[f](v) if f in cleaners else v
        if v is not None and p.get(f) != v:
            p[f] = v
            changed[f] = v
    if ex.selected_product:
        pid = ex.selected_product if ex.selected_product in knowledge.cards() else \
            next(iter(knowledge.match_products(ex.selected_product)), None)
        if pid:
            state.selected_product = pid
            changed["selected_product"] = pid
    if changed.keys() & {"age", "goal", "primary_need", "income_band", "preferred_insurer"} and p.get("age"):
        state.shortlist = knowledge.shortlist(p)
    return changed


# ---- prompt assembly --------------------------------------------------------------------------

STATIC_CHUNKS = ("_intro", "How you speak", "Rails", "PROCESS KNOWLEDGE", "PRODUCT CARDS")


def _label(pid):
    c = knowledge.cards()[pid]
    return f"{c['insurer']} {c['name']} [{pid}]"


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%A, %d %B %Y, %I:%M %p")


def _focus_product(state):
    return state.selected_product or state.pitched_product or (state.shortlist[0] if state.shortlist else None)


def stage_goal(state: SessionState, stage: Stage, objection_type=None) -> str:
    focus = _focus_product(state)
    parts = []
    if stage in POST_IDENTITY:
        parts.append(md_sections("stages.md")["Sales behaviour in every stage after CONFIRM_IDENTITY"])
    parts.append(stage_text(stage))
    if stage in POST_IDENTITY and stage not in (Stage.QA, Stage.RECOMMEND, Stage.WRAP_UP):
        parts.append(snippet("QUESTION_ASIDE"))
    if stage in (Stage.NEED_CHECK, Stage.RECOMMEND, Stage.QA) and state.profile.get("age") is not None \
            and not state.shortlist:
        parts.append(snippet("NO_SHORTLIST"))
    if stage in (Stage.RECOMMEND, Stage.QA, Stage.CLOSE, Stage.OBJECTION) and focus \
            and not knowledge.cards()[focus].get("purchase_url"):
        parts.append(snippet("NO_PURCHASE_LINK", product=_label(focus)))
    return fill("\n\n".join(p for p in parts if p), brand_name=os.getenv("BRAND_NAME", "Suraksha Advisory"),
                lead_name=state.lead.get("name"), lead_phone=state.lead.get("phone"),
                objection_type=objection_type or "the objection",
                selected_product=_label(focus) if focus else "the product")


def next_stages(state: SessionState, stage: Stage) -> list:
    focus = _focus_product(state)
    link = bool(focus and knowledge.cards()[focus].get("purchase_url"))
    nxt = {
        Stage.DISCOVERY: [Stage.NEED_CHECK],
        Stage.NEED_CHECK: [Stage.RECOMMEND],
        Stage.RECOMMEND: [Stage.CLOSE] + ([Stage.PURCHASE_LINK] if link else []),
        Stage.QA: [Stage.CLOSE] + ([Stage.PURCHASE_LINK] if link else []),
        Stage.CLOSE: [Stage.CALLBACK] + ([Stage.PURCHASE_LINK] if link else []),
        Stage.PURCHASE_LINK: [Stage.CALLBACK, Stage.WRAP_UP],
        Stage.CALLBACK: [Stage.WRAP_UP],
        Stage.OBJECTION: [Stage.WRAP_UP],
    }.get(stage, [])
    if state.soft_retry_used and Stage.WRAP_UP not in nxt and stage in POST_IDENTITY:
        nxt.append(Stage.WRAP_UP)
    return nxt


def _mentioned_insurers(text: str) -> list:
    t = (text or "").lower()
    return [ins for ins in knowledge.insurer_slugs() if re.search(rf"\b{ins.split()[0].lower()}\b", t)]


def render_sections(route: dict) -> str:
    parts, used = [], 0
    for pid, topics in route["products"].items():
        for sec in knowledge.get_sections(pid, topics):
            asked = sec["topic"] in route["matched_topics"] or sec["topic"] in route.get("extra_topics", [])
            text = sec.get("text") or ""
            if len(text) > SECTION_MAX:
                text = text[:SECTION_MAX] + " […]"
            block = f"### {_label(pid)} — {sec['topic']} (brochure pages {sec.get('pages')})\n{text}"
            if sec.get("note"):
                block += f"\nNote: {sec['note']}"
            if not asked and used + len(block) > SECTIONS_BUDGET:
                log.info(json.dumps({"event": "section_skipped_budget", "product": pid, "topic": sec["topic"]}))
                continue
            parts.append(block)
            used += len(block)
        for t in route["unavailable"].get(pid, []):
            parts.append(f"### {_label(pid)} — {t}: this brochure does not cover this topic.")
    return "\n\n".join(parts) or "(none loaded)"


def build_system(state: SessionState, stage: Stage, route: dict, objection: bool = False,
                 objection_type=None, user_text: str = "") -> list:
    p = state.profile
    past_discovery = stage not in (Stage.GREET, Stage.CONFIRM_IDENTITY, Stage.DISCOVERY)
    nf = knowledge.need_fit()
    if past_discovery:
        prods = list(dict.fromkeys(state.shortlist + [x for x in [state.selected_product] if x]))
        need_fit = knowledge.need_fit_for(prods)
    else:
        need_fit = {"needs": {k: {"label": v["label"], "listen_for": v["listen_for"]} for k, v in nf["needs"].items()}}

    claims_insurers = _mentioned_insurers(user_text)
    if stage in (Stage.RECOMMEND, Stage.QA, Stage.CLOSE, Stage.PURCHASE_LINK, Stage.CALLBACK) or objection \
            or "claims" in route["matched_topics"] or claims_insurers:
        claims_insurers += [knowledge.cards()[x]["insurer"] for x in state.shortlist + list(route["products"])]
    claims = knowledge.claims_record(list(dict.fromkeys(claims_insurers)))
    claims_txt = json.dumps({"how_to_speak": json.loads((knowledge.K / "claims_history.json").read_text())
                             ["_meta"]["how_to_speak"], "rows": claims}, ensure_ascii=False) if claims \
        else "(not loaded)"

    slugs = list(dict.fromkeys([knowledge.insurer_slug(pid) for pid in route["products"]]
                               + route["claims_fallback"]))
    notes = "\n\n".join(knowledge.insurer_notes(s) for s in slugs) or "(none loaded)"

    steps = next_stages(state, stage)
    now = now_ist()
    week = ", ".join((now + timedelta(days=d)).strftime("%A %d %B") + (" (today)" if d == 0 else " (tomorrow)"
                     if d == 1 else "") for d in range(8))
    context_extra = [snippet("NOW", now_ist=_fmt_time(now), week=week),
                     snippet("LANGUAGE", language=customer_language(state))]
    if steps:
        context_extra.append(snippet("NEXT_STEPS", steps="\n\n".join(
            f"### NEXT STEP: {s.value}\n{stage_goal(state, s)}" for s in steps)))

    vals = dict(
        brand_name=os.getenv("BRAND_NAME", "Suraksha Advisory"),
        lead_name=state.lead.get("name"), lead_phone=state.lead.get("phone"),
        now_ist=_fmt_time(datetime.fromisoformat(state.started_at)),
        stage=stage.value, stage_goal=stage_goal(state, stage, objection_type),
        profile_json=json.dumps(dict({k: v for k, v in p.items() if v is not None},
                                     **({"pending_callback_ist": _fmt_time(datetime.fromisoformat(
                                         state.pending_callback_iso))} if state.pending_callback_iso else {})),
                                ensure_ascii=False),
        missing_fields=", ".join(state.missing_fields()) or "none",
        shortlist_json=json.dumps([_label(x) for x in state.shortlist], ensure_ascii=False),
        primary_need=p.get("primary_need") or "unknown", motivation=p.get("motivation") or "not yet stated",
        selected_product=_label(state.selected_product) if state.selected_product else "none",
        objections_handled=", ".join(state.objections_handled) or "none",
        soft_retry_used=str(state.soft_retry_used).lower(),
        buying_process=knowledge.buying_process(),
        claims_records=claims_txt,
        need_fit=json.dumps(need_fit, ensure_ascii=False),
        objection_playbook=prompt_file("objections.md") if objection else "(not loaded)",
        product_cards=json.dumps(knowledge.prompt_cards(), ensure_ascii=False, separators=(",", ":")),
        product_sections=render_sections(route),
        insurer_notes=notes,
        turn_schema=json.dumps(turn_schema(), separators=(",", ":")),
    )
    chunks = md_sections("system.md")
    static, dynamic = [], []
    for name, body in chunks.items():
        text = (f"## {name}\n" if name != "_intro" else "") + fill(body, **vals)
        if name.startswith("Current context"):
            text += "\n" + "\n\n".join(context_extra)
        (static if name.startswith(STATIC_CHUNKS) else dynamic).append(text)
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


# ---- LLM calls --------------------------------------------------------------------------------

async def _call(state: SessionState, system: list, messages: list):
    llm = get_llm(state.llm_provider)
    state.metrics["llm_calls"] += 1
    try:
        r = await llm.complete_json(system, messages, turn_schema())
    except (LLMParseError, ProviderError) as e:
        log.warning(json.dumps({"event": "llm_failed", "session": state.session_id, "error": str(e)[:300]}))
        state.metrics["parse_fallbacks"] += 1
        return None, 0
    state.metrics["input_tokens"] += r["input_tokens"] or 0
    state.metrics["output_tokens"] += r["output_tokens"] or 0
    try:
        return TurnOut.model_validate(r["data"]), r["provider_ms"]
    except ValidationError as e:
        log.warning(json.dumps({"event": "turn_invalid", "session": state.session_id, "error": str(e)[:300]}))
        state.metrics["parse_fallbacks"] += 1
        return None, r["provider_ms"]


def _merge(first: TurnOut, second: TurnOut) -> TurnOut:
    """Follow-up call's reply wins; keep extracted values the first call found and the second dropped."""
    ex = second.extracted.model_copy()
    for f in EXTRACT_FIELDS:
        if getattr(ex, f) is None and getattr(first.extracted, f) is not None:
            setattr(ex, f, getattr(first.extracted, f))
    out = second.model_copy(update={"extracted": ex})
    if first.intent == "objection" and out.intent != "objection":
        out = out.model_copy(update={"intent": "objection", "objection_type": first.objection_type})
    return out


# ---- stage machine ----------------------------------------------------------------------------

def new_session(name: str, phone: str, llm_provider: str | None = None) -> SessionState:
    return SessionState(lead={"name": name, "phone": phone}, llm_provider=llm_provider)


def _select(state: SessionState, out: TurnOut):
    if not state.selected_product:
        state.selected_product = (out.product_refs[0] if len(out.product_refs) == 1 else None) \
            or state.pitched_product or (state.shortlist[0] if state.shortlist else None)


def _to(state: SessionState, stage: Stage):
    if stage != state.stage:
        log.info(json.dumps({"event": "stage", "session": state.session_id, "from": state.stage.value,
                             "to": stage.value}))
    if stage == Stage.RECOMMEND and state.shortlist and not state.pitched_product:
        state.pitched_product = state.shortlist[0]
    state.stage = stage


def _end(state: SessionState, outcome: str | None = None) -> list:
    if outcome and not state.outcome:
        state.outcome = outcome
    _to(state, Stage.END)  # the reply of this turn is already the wrap-up (NEXT STEP: WRAP_UP)
    return []


def _purchase(state: SessionState, out: TurnOut) -> list:
    _select(state, out)
    ev = actions.share_purchase_link(state, state.selected_product) if state.selected_product else None
    if ev:
        state.outcome = "purchase_link_sent"
        _to(state, Stage.PURCHASE_LINK)
        return [ev]
    _to(state, Stage.CALLBACK)
    return []


def transition(state: SessionState, out: TurnOut, text: str = "") -> list:
    """Decide the next stage. Uses the LLM's intent, but doesn't trust it alone: a yes/no fallback on the
    customer's words, callback detection in every stage after identity, and a sync step when the LLM has
    already pitched a product."""
    st, i = state.stage, out.intent
    yes, no = is_yes(out, text), is_no(out, text)
    if i == "asks_price":
        state.price_asked = True

    if st in (Stage.GREET, Stage.CONFIRM_IDENTITY):
        if i == "wrong_person" or (no and i != "not_interested"):
            return _end(state, "wrong_person")
        if i == "not_interested":
            if state.soft_retry_used:
                return _end(state, "not_interested")
            state.soft_retry_used = True
            return []
        if i not in ("unclear", "off_topic"):
            _to(state, Stage.DISCOVERY)
        return []

    if i == "not_interested":
        if not state.soft_retry_used:
            state.soft_retry_used = True
            return []
        return _end(state, "not_interested")

    if i == "objection":
        t = out.objection_type or "other"
        if t in state.objections_handled and t != "other":
            return _end(state, "not_interested")
        if t not in state.objections_handled:
            state.objections_handled.append(t)
        return []

    # Callback: works from any stage once discovery has started.
    cb = parse_callback(out.extracted.callback_time_iso) or parse_time_text(out.extracted.callback_time_text)
    if not cb and (st in (Stage.CLOSE, Stage.CALLBACK, Stage.PURCHASE_LINK) or i == "wants_callback"):
        cb = parse_time_text(text)
    new_time = cb and cb.isoformat(timespec="minutes") != state.pending_callback_iso
    if new_time:  # a new/changed time must be read back and confirmed first
        _select(state, out)
        state.pending_callback_iso = cb.isoformat(timespec="minutes")
        _to(state, Stage.CALLBACK)
        return []
    if st == Stage.CALLBACK:
        if yes and state.pending_callback_iso:
            ev = actions.log_callback(state, state.pending_callback_iso)
            _end(state)
            return [ev]
        if no:
            state.pending_callback_iso = None
        return []
    if i == "wants_callback":
        _select(state, out)
        _to(state, Stage.CALLBACK)
        return []
    if i == "wants_to_buy_now" and st != Stage.DISCOVERY:
        return _purchase(state, out)

    if st == Stage.DISCOVERY:
        state.metrics["discovery_turns"] += 1
        p = state.profile
        core_known = all(p.get(f) is not None for f in ("goal", "age", "dependents"))
        if (not state.missing_fields() and (p.get("motivation") or p.get("primary_need"))) or \
                (core_known and state.metrics["discovery_turns"] >= MAX_DISCOVERY_TURNS):
            state.shortlist = knowledge.shortlist(p) if p.get("age") is not None else []
            _to(state, Stage.NEED_CHECK)
        return []

    if st == Stage.NEED_CHECK:
        if no or "primary_need" in out.extracted.model_fields_set and out.extracted.primary_need \
                and out.extracted.primary_need != state.profile.get("primary_need"):
            return []
        if yes or i in ("question", "asks_price"):
            _to(state, Stage.RECOMMEND)
        return []

    if st in (Stage.RECOMMEND, Stage.QA):
        if len(out.product_refs) == 1:
            state.pitched_product = out.product_refs[0]
        if yes or out.extracted.selected_product:
            _select(state, out)
            _to(state, Stage.CLOSE)
        elif i in ("question", "asks_price"):
            _to(state, Stage.QA)
        return []

    if st == Stage.CLOSE:
        if yes:
            _to(state, Stage.CALLBACK)
        return []

    if st == Stage.PURCHASE_LINK:
        if yes:
            _to(state, Stage.CALLBACK)
        elif no:
            return _end(state, "purchase_link_sent")
        return []
    return []


def sync_with_reply(state: SessionState, reply: str):
    """If the LLM already pitched a shortlisted product before the code reached RECOMMEND, catch up."""
    if state.stage not in (Stage.DISCOVERY, Stage.NEED_CHECK) or not state.shortlist:
        return
    named = [p for p in knowledge.match_products(reply) if p in state.shortlist]
    if named and state.stage == Stage.NEED_CHECK or (named and not state.missing_fields()):
        state.pitched_product = named[0]
        log.info(json.dumps({"event": "stage_sync", "session": state.session_id, "product": named[0]}))
        _to(state, Stage.RECOMMEND)


async def start(state: SessionState) -> dict:
    """Agent speaks first: GREET, then wait in CONFIRM_IDENTITY."""
    route = {"products": {}, "matched_topics": [], "unavailable": {}, "claims_fallback": []}
    out, ms = await _call(state, build_system(state, Stage.GREET, route), build_messages(state))
    reply = out.reply if out else snippet("FALLBACK_GREETING", brand_name=os.getenv("BRAND_NAME", "Suraksha Advisory"),
                                          lead_name=state.lead.get("name"))
    lang = out.reply_language if out else "en-IN"
    state.add("agent", reply, lang)
    _to(state, Stage.CONFIRM_IDENTITY)
    return {"reply": reply, "reply_language": lang, "stage": state.stage.value, "events": [], "ended": False,
            "llm_ms": ms}


async def handle_turn(state: SessionState, text: str, lang: str | None = None) -> dict:
    state.add("user", text, lang)
    stage = stage_in = state.stage
    route = knowledge.route_topics(text, {"selected_product": state.selected_product or state.pitched_product,
                                          "product_refs": state.product_refs, "shortlist": state.shortlist})
    objection = state.last_intent == "objection"
    msgs = build_messages(state)
    out, ms = await _call(state, build_system(state, stage, route, objection, user_text=text), msgs)
    llm_ms = ms

    if out:
        followup, obj_type = False, None
        loaded = {t for ts in route["products"].values() for t in ts}
        missing = [t for t in out.topics_needed if t not in loaded]
        focus = list(route["products"]) or [x for x in [_focus_product(state)] if x]
        if missing and focus:
            state.metrics["router_miss"] += 1
            log.info(json.dumps({"event": "router_miss", "session": state.session_id, "topics": missing,
                                 "text": text}))
            route = dict(route, extra_topics=missing, products={
                pid: list(dict.fromkeys(missing + route["products"].get(pid, [])))[:knowledge.MAX_TOPICS + 2]
                for pid in focus[:knowledge.MAX_PRODUCTS]})
            followup = True
        if out.intent == "objection" and not objection:
            state.metrics["objection_followup"] += 1
            objection, obj_type, stage, followup = True, out.objection_type, Stage.OBJECTION, True
        if followup:
            out2, ms2 = await _call(state, build_system(state, stage, route, objection, obj_type, text), msgs)
            llm_ms += ms2
            if out2:
                out = _merge(out, out2)

    events = []
    if out is None:
        reply, reply_lang = snippet("FALLBACK_REPLY"), state.transcript[-2]["lang"] if len(state.transcript) > 1 \
            else "en-IN"
        reply_lang = reply_lang or "en-IN"
    else:
        changed = apply_extracted(state, out.extracted)
        events = transition(state, out, text)
        if state.stage != Stage.END:
            sync_with_reply(state, out.reply)
        state.last_intent = out.intent
        state.product_refs = out.product_refs
        state.loaded_products = list(route["products"])
        reply, reply_lang = out.reply, out.reply_language
        log.info(json.dumps({"event": "turn", "session": state.session_id, "stage_in": stage_in.value,
                             "stage_out": state.stage.value, "intent": out.intent,
                             "objection_type": out.objection_type, "changed": changed,
                             "extracted": out.extracted.model_dump(exclude_none=True),
                             "pending_callback": state.pending_callback_iso,
                             "topics": route["products"], "llm_ms": llm_ms}, ensure_ascii=False))

    state.add("agent", reply, reply_lang)
    state.latencies.append({"llm_ms": llm_ms})
    state.turn_log.append({"stage_in": stage_in.value, "stage_out": state.stage.value,
                           "intent": out.intent if out else None,
                           "objection_type": out.objection_type if out else None,
                           "sections": route["products"], "claims_fallback": route["claims_fallback"],
                           "extra_topics": route.get("extra_topics", []), "llm_ms": llm_ms,
                           "fallback": out is None})
    ended = state.stage == Stage.END
    if ended:
        await finish(state)
        events.append({"type": "end", "outcome": state.outcome})
    return {"reply": reply, "reply_language": reply_lang, "stage": state.stage.value, "events": events,
            "ended": ended, "llm_ms": llm_ms}


async def finish(state: SessionState) -> str:
    """One-line summary + final lead row. Safe to call more than once (upsert)."""
    if not state.outcome:
        state.outcome = "dropped"
    if not state.summary and len(state.transcript) > 1:
        convo = "\n".join(f"{t['role']}: {t['text']}" for t in state.transcript)
        try:
            r = await get_llm(state.llm_provider).complete_json(
                snippet("SUMMARY"), [{"role": "user", "content": f"OUTCOME: {state.outcome}\n\n{convo}"}],
                SUMMARY_SCHEMA)
            state.summary = str(r["data"].get("summary", ""))[:300]
        except (LLMParseError, ProviderError) as e:
            log.warning("summary failed: %s", e)
    _to(state, Stage.END)
    return actions.log_outcome(state)
