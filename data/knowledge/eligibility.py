"""Layer 2 filter: deterministic eligibility check over data/knowledge/eligibility.json.

Field conventions (see README):
  entry_age_min / entry_age_max : int, or "18-policy_term" / "65-policy_term" (depends on the term chosen)
  policy_term_min / policy_term_max : int; None = limited only by maturity_age_max;
                                      "whole_life" = term runs to maturity_age_max; "1_month" = under a year
  maturity_age_min / maturity_age_max : int or None
  channel : "all" (bank / direct / online) or "pos" (POSP channel only) - the agent uses "all"
"""
import json, pathlib

DEFAULT_PATH = pathlib.Path(__file__).parent / "eligibility.json"

# Discovery offers 4 goals; cards only tag 2. Map the extra ones onto the card goals
# (need_fit.json primary_need then does the finer ranking).
GOAL_ALIASES = {"child_future": "savings_protection", "retirement": "savings_protection"}


def _age_bound(v, pt):
    if isinstance(v, str) and v.endswith("-policy_term"):
        return int(v.split("-")[0]) - pt
    return v


def _terms(row, age):
    """Yield candidate policy terms (years) for this row at this entry age."""
    mat_max = row.get("maturity_age_max")
    lo, hi = row.get("policy_term_min"), row.get("policy_term_max")
    if lo == "whole_life":
        if mat_max is not None and mat_max > age:
            yield mat_max - age
        return
    if lo == "1_month":
        lo = 1
    if hi is None:
        hi = (mat_max - age) if mat_max is not None else lo
    for pt in row.get("policy_term_values") or range(lo, hi + 1):
        yield pt


def row_allows(row, age):
    for pt in _terms(row, age):
        emin, emax = _age_bound(row["entry_age_min"], pt), _age_bound(row["entry_age_max"], pt)
        if emin is not None and age < max(emin, 0):
            continue
        if emax is not None and age > emax:
            continue
        mat = age + pt
        if row.get("maturity_age_max") is not None and mat > row["maturity_age_max"]:
            continue
        if row.get("maturity_age_min") is not None and mat < row["maturity_age_min"]:
            continue
        return True
    return False


def eligible_products(age, goal=None, channel="all", rows=None, cards=None):
    """Return {product_id: [matching rows]} for a customer age (age last birthday)."""
    rows = rows if rows is not None else json.loads(DEFAULT_PATH.read_text())["rows"]
    goal_ok = None
    goal = GOAL_ALIASES.get(goal, goal)
    if goal and cards is not None:
        goal_ok = {c["id"] for c in cards if goal in c["goals"]}
    out = {}
    for r in rows:
        if r["channel"] != channel:
            continue
        if goal_ok is not None and r["product_id"] not in goal_ok:
            continue
        if row_allows(r, age):
            out.setdefault(r["product_id"], []).append(r)
    return out
