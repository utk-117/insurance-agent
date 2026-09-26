"""v2 consult-phase tools: one registry for every LLM provider.

  TOOLS            -> list of {name, description, parameters (JSON schema)}; adapters convert to their format
  run(state, name, args) -> {"ok": bool, ...result or "error"}; never raises for bad model input
Every result is compact JSON with page / source references. The close tools (book_callback,
share_purchase_link, end_conversation) are the code guards of Phase 3.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta

from app.agent import actions, knowledge
from app.agent.money import money, money_range, parse_amount, words_in_text
from app.agent.state import IST, Phase, SessionState, now_ist

log = logging.getLogger("tools")

SECTION_TOPICS = ["key_features", "plan_options", "death_benefit", "maturity_benefit", "optional_benefits", "riders",
                  "free_look", "grace_period", "suicide_exclusion", "surrender_and_paid_up", "loan", "revival", "tax",
                  "claims", "non_disclosure_sec45", "other_exclusions"]
OUTCOMES = ["callback_scheduled", "purchase_link_sent", "purchase_link_and_callback", "not_interested",
            "wrong_person", "dropped"]
SECTION_CHARS = 3500
MAX_CALLBACK_DAYS = 14


def _pid():
    return {"type": "string", "enum": sorted(knowledge.cards())}


def tool_specs() -> list:
    return [
        {"name": "get_product_info",
         "description": "Brochure wording (with page numbers) for up to 3 section topics of one product. Use for "
                        "benefits, options, exclusions, free-look, surrender, tax, claims and other detail.",
         "parameters": {"type": "object", "properties": {
             "product_id": _pid(),
             "topics": {"type": "array", "items": {"type": "string", "enum": SECTION_TOPICS}, "maxItems": 3}},
             "required": ["product_id", "topics"]}},
        {"name": "get_premium_estimate",
         "description": "Indicative yearly premium RANGE for a term plan at a given cover (sum assured), for this "
                        "customer's profile. Use when the customer wants a price at a cover not in SNAPSHOT.",
         "parameters": {"type": "object", "properties": {
             "product_id": _pid(),
             "cover": {"type": "string", "description": "cover amount in words, as the customer said it, e.g. '30 crore', "
                                                        "'50 lakh' (code converts it; don't convert to digits)"}},
             "required": ["product_id", "cover"]}},
        {"name": "get_savings_illustration",
         "description": "What a savings plan's brochure example pays, scaled to the customer's yearly premium.",
         "parameters": {"type": "object", "properties": {
             "product_id": _pid(),
             "annual_premium": {"type": "string", "description": "yearly premium in words, e.g. '1 lakh'"}},
             "required": ["product_id", "annual_premium"]}},
        {"name": "get_claims_record",
         "description": "IRDAI individual death claims paid by amount and by number, FY2022-23 to FY2024-25.",
         "parameters": {"type": "object", "properties": {
             "insurer_slug": {"type": "string", "enum": sorted(knowledge.claims_history())}},
             "required": ["insurer_slug"]}},
        {"name": "compare_products",
         "description": "Side-by-side facts for 2-3 products: key benefits, options, cover limits, indicative price "
                        "ranges for this customer, and claims record.",
         "parameters": {"type": "object", "properties": {
             "product_ids": {"type": "array", "items": _pid(), "minItems": 2, "maxItems": 3}},
             "required": ["product_ids"]}},
        {"name": "get_process_info",
         "description": "How buying / underwriting / claims work (buying process + the insurer's notes).",
         "parameters": {"type": "object", "properties": {
             "topic": {"type": "string", "enum": sorted(knowledge.PROCESS_TOPICS)},
             "insurer_slug": {"type": "string", "enum": sorted(knowledge.claims_history())}},
             "required": ["topic"]}},
        {"name": "book_callback",
         "description": "Book the human advisor call. Only after you read back the full day, date and time and the "
                        "customer said yes to it and to being called on their number.",
         "parameters": {"type": "object", "properties": {
             "datetime_iso": {"type": "string", "description": "e.g. 2026-09-27T17:00:00+05:30 (IST)"},
             "product_ids": {"type": "array", "items": _pid()},
             "note": {"type": "string", "description": "one line for the advisor"},
             "customer_confirmed": {"type": "boolean"}},
             "required": ["datetime_iso", "customer_confirmed"]}},
        {"name": "share_purchase_link",
         "description": "Show the product's official purchase page on the customer's screen. Only when they say "
                        "they have decided to buy.",
         "parameters": {"type": "object", "properties": {"product_id": _pid()}, "required": ["product_id"]}},
        {"name": "end_conversation",
         "description": "End the call. Call it once, when the customer wants to stop or the conversation is over. "
                        "`goodbye` is spoken as your last line.",
         "parameters": {"type": "object", "properties": {
             "outcome": {"type": "string", "enum": OUTCOMES},
             "goodbye": {"type": "string", "description": "your last words, in the customer's language, e.g. 'Sure, "
                                                         "cutting the call now. Have a nice day, Rahul!'"},
             "summary": {"type": "string"}},
             "required": ["outcome", "goodbye"]}},
    ]


# ---- implementations ---------------------------------------------------------------------------

def _note_products(state: SessionState, *pids):
    for p in pids:
        if p in knowledge.cards() and p not in state.discussed_products:
            state.discussed_products.append(p)


def _eligible_ids(state):
    return [e["product_id"] for e in (state.snapshot or {}).get("eligible", [])]


def get_product_info(state, product_id, topics):
    _note_products(state, product_id)
    out = []
    for s in knowledge.get_sections(product_id, [t for t in topics if t in SECTION_TOPICS][:3]):
        text = s.get("text") or ""
        out.append({"topic": s["topic"], "available": s.get("available", False), "pages": s.get("pages"),
                    "text": text[:SECTION_CHARS] + (" […]" if len(text) > SECTION_CHARS else "") if text
                    else "Not covered in this brochure."})
    card = knowledge.cards()[product_id]
    return {"product": f"{card['insurer']} {card['name']}", "source": card.get("source_file"), "sections": out}


def _last_customer_text(state) -> str:
    return next((t["text"] for t in reversed(state.transcript) if t["role"] == "user"), "")


def get_premium_estimate(state, product_id, cover=None, sum_assured=None):
    p = state.profile
    if product_id not in _eligible_ids(state):
        return {"error": "This product is not in SNAPSHOT.eligible for this customer; don't quote it."}
    sa = parse_amount(cover if cover is not None else sum_assured)
    if not sa:
        return {"error": f"Couldn't read the cover amount {cover or sum_assured!r}. Pass it in words, e.g. '30 crore'."}
    fixed = None
    said = parse_amount(_last_customer_text(state))
    if said and said != sa and max(said, sa) / min(said, sa) in (10, 100):  # model dropped / added a zero
        fixed, sa = sa, said
    q = knowledge.intake_rules().estimate_term_premium(
        product_id, age=p["age"], gender=p.get("gender") or "male", tobacco=bool(p.get("tobacco")),
        sum_assured=sa, employment_type=p.get("employment_type"))
    if not q:
        return {"error": "No term-price basis for this product (savings plan?). Use get_savings_illustration."}
    min_sa = knowledge.cards()[product_id].get("min_sum_assured_inr") or 0
    if sa < min_sa:
        return {"error": f"Minimum cover for this product is {money(min_sa)}."}
    lo, hi = q["annual_premium_range"]
    c = knowledge.cards()[product_id]
    out = {"product": f"{c['insurer']} {c['name']}", "cover": money(sa),
           "indicative_premium": money_range(lo, hi), "pay": "regular pay",
           "basis": words_in_text(q["basis"], bare=True), "disclaimer": q["disclaimer"],
           "say": f"For {money(sa)} cover: about {money_range(lo, hi)} (indicative)."}
    if q.get("salaried_first_year_discount"):
        out["salaried_discount"] = f"{q['salaried_first_year_discount'] * 100:g}% off the first year's premium only"
    if q.get("note"):
        out["note"] = q["note"]
    if fixed:
        out["corrected"] = f"You passed {money(fixed)} but the customer said {money(sa)}; quoted {money(sa)}."
    cap = (state.snapshot or {}).get("max_cover")
    if cap and sa > cap:
        out["above_max_cover"] = (f"{money(sa)} is above the customer's indicative max cover of {money(cap)}; the "
                                  "insurer decides higher cover with income proof — say so.")
    _note_products(state, product_id)
    state.quoted.append({"product_id": product_id, "sum_assured": sa, "range": [lo, hi]})
    return out


def get_savings_illustration(state, product_id, annual_premium):
    ap = parse_amount(annual_premium)
    if not ap:
        return {"error": f"Couldn't read the premium {annual_premium!r}. Pass it in words, e.g. '1 lakh'."}
    ill = knowledge.intake_rules().savings_illustration(product_id, ap)
    if not ill:
        return {"error": "No brochure illustration for this product (term plan?). Use get_premium_estimate."}
    _note_products(state, product_id)
    kind = knowledge.pricing()["products"][product_id]["kind"]
    out = {"product_id": product_id, "customer_annual_premium": money(ap), "illustrations": [
        {"option": x.get("option"), "example": f"age {x.get('age')}, {x.get('gender')}, "
                                               f"{money(x['annual_premium'])} a year for {x.get('ppt')} years, "
                                               f"policy term {x.get('policy_term')} years (p.{x.get('page')})",
         "brochure_benefit": words_in_text(x.get("benefit", "")),
         "scaled_to_customer_premium": words_in_text(x.get("benefit", ""), x["scale_factor"])} for x in ill],
        "caveat": "Scaled from the brochure example; actual figures depend on age, term and option.",
        "disclaimer": knowledge.pricing()["_meta"]["spoken_disclaimer_en"]}
    if kind == "savings_participating":
        out["must_say"] = "Give both the 4% and 8% figures and say bonuses are not guaranteed."
    return out


def get_claims_record(state, insurer_slug):
    rows = knowledge.claims_record([insurer_slug])
    if not rows:
        return {"error": f"Unknown insurer {insurer_slug}."}
    meta = json.loads((knowledge.K / "claims_history.json").read_text())["_meta"]
    return {"rows": rows, "how_to_speak": meta["how_to_speak"], "source": meta["source"]["publication"]}


def compare_products(state, product_ids):
    pids = [p for p in dict.fromkeys(product_ids) if p in knowledge.cards()][:3]
    if len(pids) < 2:
        return {"error": "Give 2-3 valid product ids."}
    _note_products(state, *pids)
    snap = {e["product_id"]: e for e in (state.snapshot or {}).get("eligible", [])}
    out = []
    for pid in pids:
        c = knowledge.cards()[pid]
        rec = knowledge.claims_record([pid])[:1]
        out.append({"product_id": pid, "product": f"{c['insurer']} {c['name']}", "plan_type": c["plan_type"],
                    "pitch_line": c["pitch_line"], "key_benefits": c["key_benefits"][:5],
                    "plan_options": c["plan_options"], "premium_payment_options": c["premium_payment_options"],
                    "cover_up_to_age": c.get("cover_up_to_age"), "min_cover": money(c.get("min_sum_assured_inr")),
                    "eligible_for_customer": pid in snap,
                    "price_ranges": [{"cover": money(q["sum_assured"]),
                                      "indicative_premium": money_range(*q["annual_premium_range"])}
                                     for q in snap.get(pid, {}).get("quotes", [])],
                    "claims_latest": rec[0] if rec else None})
    return {"products": out, "disclaimer": knowledge.pricing()["_meta"]["spoken_disclaimer_en"]}


def get_process_info(state, topic, insurer_slug=None):
    r = knowledge.process_info(topic, insurer_slug)
    return r if r else {"error": f"Unknown topic. Use one of {sorted(knowledge.PROCESS_TOPICS)}."}


def _parse_dt(s: str):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def _read_back_ok(state: SessionState, dt: datetime) -> bool:
    """The agent's previous reply must have read back this date (day of month) and hour."""
    prev = next((t["text"] for t in reversed(state.transcript[:-1]) if t["role"] == "agent"), "")
    h12 = dt.hour % 12 or 12
    has_day = re.search(rf"\b{dt.day}(st|nd|rd|th)?\b", prev) or dt.strftime("%A").lower() in prev.lower() \
        or ("kal" in prev.lower() or "tomorrow" in prev.lower()) and dt.date() == (now_ist() + timedelta(days=1)).date()
    has_hour = re.search(rf"\b{h12}(:\d\d)?\s*(am|pm|a\.m|p\.m|baje|o'?clock)?\b", prev, re.I) \
        or re.search(rf"\b{dt.hour}:\d\d\b", prev)
    return bool(has_day and has_hour)


def book_callback(state, datetime_iso, customer_confirmed, product_ids=None, note=None):
    dt = _parse_dt(datetime_iso)
    if dt is None:
        return {"error": "datetime_iso is not a valid ISO datetime. Resolve the time with the CALENDAR."}
    now = now_ist()
    if dt <= now:
        return {"error": f"{dt:%A %d %B, %I:%M %p} is in the past (now {now:%A %d %B, %I:%M %p} IST). Ask again."}
    if dt > now + timedelta(days=MAX_CALLBACK_DAYS):
        return {"error": f"Callbacks can be booked up to {MAX_CALLBACK_DAYS} days ahead. Ask for an earlier time."}
    if not customer_confirmed:
        return {"error": "Not booked: read back the full day, date and time, get a clear yes (and consent to call "
                         f"{state.lead.get('phone')}), then call again with customer_confirmed=true."}
    if not _read_back_ok(state, dt):
        return {"error": f"Not booked: you haven't read back {dt:%A, %d %B at %I:%M %p} to the customer yet. "
                         "Read it back and get a yes first."}
    _note_products(state, *(product_ids or []))
    ev = actions.log_callback(state, dt.isoformat(timespec="minutes"))
    state.events.append(ev)
    state.phase = Phase.WRAP_UP
    return {"booked": True, "callback_time_ist": f"{dt:%A, %d %B %Y at %I:%M %p}", "phone": state.lead.get("phone"),
            "note": note}


def share_purchase_link(state, product_id):
    if product_id not in knowledge.cards():
        return {"error": "Unknown product."}
    ev = actions.share_purchase_link(state, product_id)
    if not ev:
        return {"error": "No purchase page is available for this product. Offer the advisor callback instead; the "
                         "advisor will help them buy on the insurer's official website."}
    _note_products(state, product_id)
    state.events.append(ev)
    if state.outcome not in ("callback_scheduled", "purchase_link_and_callback"):
        state.outcome = "purchase_link_sent"
    state.phase = Phase.CLOSE
    return {"shown": True, "product": ev["name"], "insurer": ev["insurer"],
            "next": "Tell them the official page is on their screen, then offer an advisor callback."}


def end_conversation(state, outcome, goodbye=None, summary=None):
    if state.phase == Phase.END:  # already ended this turn: no second log, no second goodbye
        return {"ended": True, "note": "already ended"}
    # code decides what the outcome can be: a booked call or a shared link can't be downgraded by the model
    if state.callback_time:
        outcome = "purchase_link_and_callback" if state.purchase_link else "callback_scheduled"
    elif state.purchase_link:
        outcome = "purchase_link_sent"
    elif outcome in ("callback_scheduled", "purchase_link_and_callback", "purchase_link_sent"):
        outcome = "dropped"  # model claimed a close that never happened
    state.outcome = outcome if outcome in OUTCOMES else "dropped"
    if summary:
        state.summary = str(summary)[:300]
    state.phase = Phase.END
    state.goodbye = (goodbye or "").strip() or None
    return {"ended": True, "outcome": state.outcome}


IMPL = {"get_product_info": get_product_info, "get_premium_estimate": get_premium_estimate,
        "get_savings_illustration": get_savings_illustration, "get_claims_record": get_claims_record,
        "compare_products": compare_products, "get_process_info": get_process_info,
        "book_callback": book_callback, "share_purchase_link": share_purchase_link,
        "end_conversation": end_conversation}


def run(state: SessionState, name: str, args: dict) -> dict:
    """Run one tool call; errors come back as {"ok": false, "error": ...} for the model to act on."""
    t0 = time.perf_counter()
    fn = IMPL.get(name)
    if fn is None:
        res = {"error": f"Unknown tool {name}. Tools: {sorted(IMPL)}."}
    else:
        try:
            res = fn(state, **(args or {}))
        except TypeError as e:  # wrong / missing arguments from the model
            res = {"error": f"Bad arguments for {name}: {e}"}
        except (ValueError, KeyError) as e:
            res = {"error": f"{name} failed: {e}"}
    ok = "error" not in res
    ms = round((time.perf_counter() - t0) * 1000)
    state.tool_calls.append({"name": name, "args": args, "ok": ok, "ms": ms,
                             **({"error": res["error"]} if not ok else {})})
    log.info(json.dumps({"event": "tool", "session": state.session_id, "name": name, "ok": ok, "ms": ms},
                        ensure_ascii=False))
    return {"ok": ok, **res}
