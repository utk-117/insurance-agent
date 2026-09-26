"""Knowledge wiring over data/knowledge (built offline - never regenerated here).

  shortlist(profile)                 -> ranked product ids (eligibility + gates + need_fit rank, insurer-neutral)
  route_topics(transcript, state)    -> which products / section topics to load this turn (no LLM call)
  get_sections(product_id, topics)   -> brochure wording for those topics
  insurer_notes(slug, part=None)     -> data/insurers/<slug>/insurer.md, whole or one "## " section
  claims_record(insurers)            -> IRDAI death-claim rows for those insurers
plus prompt helpers: prompt_cards(), need_fit_for(), and small lookups.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
from functools import lru_cache

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
K = DATA / "knowledge"

MAX_PRODUCTS = 2
MAX_TOPICS = 4
CARD_DROP = ("topics_available", "source_file", "uin")

# Discovery answers -> ids used in cards / need_fit / eligibility.py
GOALS = {
    "pure protection": "pure_protection", "pure_protection": "pure_protection", "protection": "pure_protection",
    "term": "pure_protection",
    "savings + protection": "savings_protection", "savings_protection": "savings_protection",
    "savings": "savings_protection",
    "child's future": "child_future", "child_future": "child_future", "child future": "child_future",
    "retirement": "retirement",
}


def _load(name):
    return json.loads((K / name).read_text())


@lru_cache(maxsize=None)
def _eligibility():
    spec = importlib.util.spec_from_file_location("kb_eligibility", K / "eligibility.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@lru_cache(maxsize=None)
def cards() -> dict:
    return {c["id"]: c for c in _load("cards.json")["products"]}


@lru_cache(maxsize=None)
def eligibility_rows() -> list:
    return _load("eligibility.json")["rows"]


@lru_cache(maxsize=None)
def need_fit() -> dict:
    return _load("need_fit.json")


@lru_cache(maxsize=None)
def router() -> dict:
    return _load("topic_router.json")


@lru_cache(maxsize=None)
def insurer_slugs() -> dict:
    return _load("insurers.json")["by_name"]


@lru_cache(maxsize=None)
def claims_history() -> dict:
    return {i["insurer_slug"]: i for i in _load("claims_history.json")["insurers"]}


@lru_cache(maxsize=None)
def _sections(product_id: str) -> dict:
    data = json.loads((K / "sections" / f"{product_id}.json").read_text())
    return {s["topic"]: s for s in data["sections"]}


@lru_cache(maxsize=None)
def buying_process() -> str:
    return (K / "buying_process.md").read_text()


def _get(obj, key, default=None):
    """Read a field from a dict or a dataclass-like object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def norm_goal(goal):
    if not goal:
        return None
    return GOALS.get(str(goal).strip().lower(), goal)


def insurer_slug(product_id: str) -> str:
    return insurer_slugs()[cards()[product_id]["insurer"]]


def match_insurer(name) -> str | None:
    """'hdfc' / 'HDFC Life' / 'hdfc-life' -> insurer name as in cards, or None."""
    if not name:
        return None
    n = str(name).lower()
    for ins, slug in insurer_slugs().items():
        if n == slug or n in ins.lower() or ins.lower().split()[0] in n:
            return ins
    return None


# ---- Shortlisting -----------------------------------------------------------------------------

def _need_features(product_id, need):
    return len(need_fit()["products"].get(product_id, {}).get(need) or [])


def _goal_features(product_id, goal):
    """All need_fit features of this product for needs that belong to the discovery goal."""
    goal = _eligibility().GOAL_ALIASES.get(goal, goal)
    needs = need_fit()["needs"]
    m = need_fit()["products"].get(product_id, {})
    return sum(len(v) for k, v in m.items()
               if k in needs and (goal is None or needs[k]["discovery_goal"] == goal))


def _gate_ok(product_id, profile) -> bool:
    gate = need_fit()["products"].get(product_id, {}).get("gate")
    if not gate:
        return True
    for field, allowed in gate.items():
        if field == "reason":
            continue
        # unknown value -> fail closed (e.g. don't pitch ICICI Assured Savings until income band is known)
        if _get(profile, field) not in allowed:
            return False
    return True


def _soft_gated(product_id, profile) -> bool:
    sg = need_fit()["products"].get(product_id, {}).get("soft_gate")
    if not sg:
        return False
    return any(_get(profile, f) in allowed for f, allowed in sg.items() if f != "reason")


def rank_products(profile) -> list:
    """All eligible, gate-passing products, best first. Returns [] if age is unknown."""
    age = _get(profile, "age")
    if age is None:
        return []
    goal = norm_goal(_get(profile, "goal"))
    need = _get(profile, "primary_need")
    eligible = _eligibility().eligible_products(int(age), goal, channel="all",
                                                rows=eligibility_rows(), cards=list(cards().values()))
    pref = match_insurer(_get(profile, "preferred_insurer"))
    scored = []
    for pid in eligible:
        if not _gate_ok(pid, profile):
            continue
        key = (
            0 if pref and cards()[pid]["insurer"] == pref else 1,  # volunteered insurer first
            1 if _soft_gated(pid, profile) else 0,                  # soft gate only lowers rank
            -_need_features(pid, need) if need else 0,              # features for the stated need
            -_goal_features(pid, goal),                             # tie-break: features for the goal overall
            pid,                                                    # deterministic
        )
        scored.append((key, pid))
    return [pid for _, pid in sorted(scored)]


def shortlist(profile, k: int = 3) -> list:
    """Top-k product ids. Insurer-neutral: at most one per insurer unless preferred_insurer is set."""
    ranked = rank_products(profile)
    if match_insurer(_get(profile, "preferred_insurer")):
        return ranked[:k]
    out, seen = [], set()
    for pid in ranked:
        ins = cards()[pid]["insurer"]
        if ins not in seen:
            out.append(pid)
            seen.add(ins)
        if len(out) == k:
            break
    return out


# ---- Topic routing ----------------------------------------------------------------------------

def _kw_pattern(kw: str) -> re.Pattern:
    # Short keywords ("war", "tax", "exit", "gift") need word boundaries, or "war" matches "aware" and
    # "exit" matches "existing". Longer ones match as substrings, as topic_router.json describes.
    k = re.escape(kw.lower())
    if len(kw) <= 4:
        return re.compile(rf"(?<![a-z0-9]){k}s?(?![a-z0-9])")
    return re.compile(k)


@lru_cache(maxsize=None)
def _compiled_router():
    r = router()
    topics = [(t, [_kw_pattern(k) for k in kws]) for t, kws in r["keywords"].items()]
    aliases = [(pid, [_kw_pattern(a) for a in al + [cards()[pid]["name"]]])
               for pid, al in r["product_aliases"].items()]
    return topics, aliases


def match_topics(text: str) -> list:
    t = (text or "").lower()
    topics, _ = _compiled_router()
    return [topic for topic, pats in topics if any(p.search(t) for p in pats)]


def match_products(text: str, shortlist_ids=None) -> list:
    """Products named in the text by alias/name; bare insurer names ("the HDFC one") resolve to
    that insurer's product in the shortlist."""
    t = (text or "").lower()
    _, aliases = _compiled_router()
    found = [pid for pid, pats in aliases if any(p.search(t) for p in pats)]
    for pid in shortlist_ids or []:
        if pid in found:
            continue
        ins = cards()[pid]["insurer"]
        short = ins.split()[0].lower()  # sbi / icici / hdfc
        if re.search(rf"(?<![a-z0-9]){short}(?![a-z0-9])", t) and \
                not any(cards()[f]["insurer"] == ins for f in found):
            found.append(pid)
    return found


def route_topics(transcript: str, state=None) -> dict:
    """Pick products (max 2) and topics (max 4 each) to load for this turn.

    state (dict or object) may carry: selected_product, product_refs (last LLM turn), shortlist,
    answered_topics {product_id: [topic]} (core topics already covered are not re-loaded).
    Returns {"products": {pid: [topics]}, "matched_topics": [...], "unavailable": {pid: [topics]},
             "claims_fallback": [insurer_slug]}  - claims_fallback means: load insurer_notes(slug, "Death claims").
    """
    matched = match_topics(transcript)
    products = []
    for pid in ([_get(state, "selected_product")]
                + match_products(transcript, _get(state, "shortlist") or [])
                + list(_get(state, "product_refs") or [])):
        if pid and pid in cards() and pid not in products:
            products.append(pid)
    products = products[:MAX_PRODUCTS]

    answered = _get(state, "answered_topics") or {}
    out, unavailable, fallback = {}, {}, []
    for pid in products:
        secs = _sections(pid)
        chosen = []
        for t in matched:
            if secs.get(t, {}).get("available"):
                chosen.append(t)
            else:
                unavailable.setdefault(pid, []).append(t)
                if t == "claims":
                    slug = insurer_slug(pid)
                    if slug not in fallback:
                        fallback.append(slug)
        chosen = chosen[:MAX_TOPICS]
        for t in router()["core_topics"]:
            if len(chosen) >= MAX_TOPICS:
                break
            if t not in chosen and secs.get(t, {}).get("available") and t not in answered.get(pid, []):
                chosen.append(t)
        out[pid] = chosen
    return {"products": out, "matched_topics": matched, "unavailable": unavailable, "claims_fallback": fallback}


def get_sections(product_id: str, topics) -> list:
    """[{topic, available, text, pages, note?}] in the order asked; unknown topics come back unavailable."""
    secs = _sections(product_id)
    return [copy.deepcopy(secs.get(t, {"topic": t, "available": False, "text": None, "pages": []})) for t in topics]


# ---- Insurer notes & claims -------------------------------------------------------------------

def insurer_notes(slug_or_product: str, part: str | None = None) -> str:
    """Whole insurer.md, or only the '## <part>...' section (case-insensitive prefix, e.g. 'Death claims')."""
    slug = slug_or_product if slug_or_product not in cards() else insurer_slug(slug_or_product)
    text = (DATA / "insurers" / slug / "insurer.md").read_text()
    if not part:
        return text
    chunks = re.split(r"(?m)^(?=## )", text)
    title = chunks[0].strip().splitlines()[0] if chunks and chunks[0].startswith("# ") else ""
    hits = [c.strip() for c in chunks if c.lower().startswith("## " + part.lower())]
    return "\n\n".join(([title] if title else []) + hits)


def claims_record(insurers) -> list:
    """Rows for the given insurers (names, slugs or product ids), all FYs, newest first."""
    out, seen = [], set()
    for x in insurers or []:
        if x in cards():
            slug = insurer_slug(x)
        elif x in claims_history():
            slug = x
        else:
            ins = match_insurer(x)
            slug = insurer_slugs().get(ins) if ins else None
        if not slug or slug in seen:
            continue
        seen.add(slug)
        rec = claims_history()[slug]
        for y in sorted(rec["years"], key=lambda y: y["fy"], reverse=True):
            out.append({"insurer": rec["insurer"], "fy": y["fy"],
                        "paid_pct_by_amount": y["paid_pct_by_amount"],
                        "paid_pct_by_number": y["paid_pct_by_number"],
                        "source_ref": y["source_ref"]})
    return out


# ---- Prompt helpers ---------------------------------------------------------------------------

def prompt_cards() -> list:
    """All cards without the fields the LLM doesn't need (token saving)."""
    return [{k: v for k, v in c.items() if k not in CARD_DROP} for c in cards().values()]


def need_fit_for(product_ids) -> dict:
    """need_fit restricted to the given products (gates removed - they are applied in code)."""
    nf = need_fit()
    prods = {pid: {k: v for k, v in nf["products"][pid].items() if k not in ("gate", "soft_gate")}
             for pid in product_ids if pid in nf["products"]}
    used = {n for m in prods.values() for n in m}
    return {"needs": {n: {"label": v["label"], "discovery_goal": v["discovery_goal"]}
                      for n, v in nf["needs"].items() if n in used},
            "products": prods}


# ---- v2: intake rules, pricing, process knowledge -----------------------------------------------

@lru_cache(maxsize=None)
def intake_rules():
    """data/knowledge/intake_rules.py (reference implementation; imports `eligibility` from its own folder)."""
    import sys
    if str(K) not in sys.path:
        sys.path.insert(0, str(K))
    import intake_rules as ir  # noqa: E402
    return ir


@lru_cache(maxsize=None)
def underwriting_rules() -> dict:
    return _load("underwriting_rules.json")


@lru_cache(maxsize=None)
def pricing() -> dict:
    return _load("pricing.json")


def profile_snapshot(profile: dict) -> dict:
    return intake_rules().profile_snapshot(profile)


def _md_parts(text: str) -> dict:
    """'## heading' -> section text (heading included)."""
    parts = {}
    for chunk in re.split(r"(?m)^(?=## )", text):
        if chunk.startswith("## "):
            parts[chunk.splitlines()[0][3:].strip()] = chunk.strip()
    return parts


# get_process_info topic -> (buying_process.md heading prefixes, insurer.md heading prefixes)
PROCESS_TOPICS = {
    "buying_steps": (["1. From interest"], []),
    "medical_tests": (["1. From interest"], ["Medical tests"]),
    "underwriting": (["1. From interest"], ["Medical tests"]),
    "disclosure": (["2. Tobacco"], []),
    "tobacco": (["2. Tobacco"], ["Medical tests"]),
    "after_issue": (["3. After the policy"], []),
    "free_look": (["3. After the policy"], []),
    "claims": (["4. Death claims"], ["Death claims"]),
    "documents": (["4. Death claims"], ["Death claims"]),
    "contacts": ([], ["Death claims", "Other contacts"]),
}


def process_info(topic: str, insurer_slug: str | None = None) -> dict | None:
    if topic not in PROCESS_TOPICS:
        return None
    bp_heads, ins_heads = PROCESS_TOPICS[topic]
    bp = _md_parts(buying_process())
    out = {"topic": topic, "source": "buying_process.md",
           "text": "\n\n".join(v for k, v in bp.items() if any(k.startswith(h) for h in bp_heads))}
    if insurer_slug and ins_heads:
        notes = _md_parts((DATA / "insurers" / insurer_slug / "insurer.md").read_text())
        out["insurer_notes"] = "\n\n".join(v for k, v in notes.items() if any(k.startswith(h) for h in ins_heads))
        out["insurer_source"] = f"data/insurers/{insurer_slug}/insurer.md"
    return out
