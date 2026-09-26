"""Deterministic layer after intake: eligibility, max cover, indicative premiums.

    from intake_rules import profile_snapshot
    snap = profile_snapshot({"age": 32, "gender": "male", "employment_type": "salaried",
                             "annual_income_inr": 1200000, "tobacco": False})

Everything here reads data/knowledge/*.json. The LLM never computes cover or prices; it reads the snapshot
or calls the pricing tools, which call these functions.
"""
from __future__ import annotations

import json
import math
import pathlib

import eligibility

K = pathlib.Path(__file__).parent
_load = lambda n: json.loads((K / n).read_text())
CARDS = {c["id"]: c for c in _load("cards.json")["products"]}
RULES = _load("underwriting_rules.json")
PRICING = _load("pricing.json")
TERM_KINDS = {"term", "term_return_of_premium"}


def _round_cover(x: float) -> int:
    step = 500_000 if x < 10_000_000 else 2_500_000
    return int(x // step * step)


def _round(x: float, step: int) -> int:
    return int(round(x / step) * step)


def max_cover(age: int, employment_type: str, annual_income_inr: int | None) -> int | None:
    if employment_type == "not_working" or not annual_income_inr:
        return None
    mult = next(b["multiple"] for b in RULES["max_cover"]["income_multiple_by_age"] if age <= b["age_max"])
    return _round_cover(mult * annual_income_inr)


def estimate_term_premium(product_id: str, *, age: int, gender: str, tobacco: bool, sum_assured: int,
                          employment_type: str | None = None) -> dict | None:
    """Indicative annual premium range (regular pay) for a term product, or None if no anchor."""
    p = PRICING["products"].get(product_id)
    if not p or p["kind"] not in TERM_KINDS:
        return None
    m = PRICING["term_model"]
    anchors = [a for a in p["anchors"] if a["pay"] == "regular"] or p["anchors"]
    a = min(anchors, key=lambda a: abs(a["age"] - age))
    est = a["annual_premium"] * (sum_assured / a["sa"]) * math.exp(m["age_k"] * (age - a["age"]))
    # gender: normalise anchor to male, then apply customer's gender
    fem = p.get("gender_factor_female") or m["gender_factor_female_default"]
    if a.get("gender") == "female":
        est /= fem
    if gender == "female":
        est *= fem
    # tobacco: anchors are non-tobacco or unstated (treated as non-tobacco)
    if tobacco:
        est *= m["tobacco_factor"]
    lo_f, hi_f = (m["range_low"], m["range_high"]) if sum_assured >= 5_000_000 else (0.75, 1.35)
    out = {
        "product_id": product_id,
        "sum_assured": sum_assured,
        "pay": "regular",
        "annual_premium_range": [_round(est * lo_f, m["round_to"]), _round(est * hi_f, m["round_to"])],
        "basis": f"brochure example: age {a['age']}, {a.get('gender') or 'gender n/a'}, cover {a['sa']:,}, "
                 f"premium {a['annual_premium']:,} (p.{a['page']}); scaled for age, cover, gender, tobacco",
        "disclaimer": PRICING["_meta"]["spoken_disclaimer_en"],
    }
    sd = p.get("salaried_discount")
    if sd and employment_type == "salaried":
        out["salaried_first_year_discount"] = sd["regular"]
    if p["kind"] == "term_return_of_premium":
        out["note"] = "Return of premium plan: costs more than pure term because premiums come back at maturity."
    return out


def savings_illustration(product_id: str, annual_premium: int) -> list[dict] | None:
    p = PRICING["products"].get(product_id)
    if not p or "illustrations" not in p:
        return None
    out = []
    for ill in p["illustrations"]:
        f = annual_premium / ill["annual_premium"]
        out.append({**ill, "scale_factor": round(f, 3),
                    "how_to_say": f"The brochure example pays {ill['annual_premium']:,} a year; for {annual_premium:,} "
                                  f"multiply its figures by about {f:.2f}. Actual figures depend on age, term and option."})
    return out


def profile_snapshot(profile: dict) -> dict:
    age, emp = profile["age"], profile["employment_type"]
    inc, gender, tob = profile.get("annual_income_inr"), profile.get("gender", "male"), bool(profile.get("tobacco"))
    cap = max_cover(age, emp, inc)
    eligible = eligibility.eligible_products(age, cards=list(CARDS.values()))
    products, excluded = [], []
    for pid in eligible:
        card = CARDS[pid]
        gate = RULES["gates"].get(pid)
        if gate and not ((inc or 0) >= 10_000_000):
            excluded.append({"product_id": pid, "reason": gate["reason"]})
            continue
        is_term = card["plan_type"] in TERM_KINDS
        if is_term:
            if cap is None:
                excluded.append({"product_id": pid, "reason": "no income: term cover on own life not available"})
                continue
            min_sa = card.get("min_sum_assured_inr") or 0
            if min_sa > cap:
                excluded.append({"product_id": pid, "reason": f"minimum cover {min_sa:,} is above max cover {cap:,}"})
                continue
            quotes = []
            for sa in sorted({s for s in (10_000_000, cap) if min_sa <= s <= cap}):
                q = estimate_term_premium(pid, age=age, gender=gender, tobacco=tob, sum_assured=sa, employment_type=emp)
                if q:
                    quotes.append(q)
            products.append({"product_id": pid, "insurer": card["insurer"], "type": card["plan_type"],
                             "min_cover": min_sa, "max_cover": cap, "quotes": quotes})
        else:
            products.append({"product_id": pid, "insurer": card["insurer"], "type": card["plan_type"],
                             "pricing": "savings: customer chooses the premium; use savings_illustration()"})
    return {"profile": profile, "max_cover": cap,
            "max_cover_rule": RULES["max_cover"]["rule"] if cap else RULES["max_cover"]["not_working"],
            "not_working_options": RULES["not_working_options"] if emp == "not_working" else None,
            "eligible": products, "excluded": excluded,
            "disclaimer": PRICING["_meta"]["spoken_disclaimer_en"]}


if __name__ == "__main__":
    for prof in [
        {"age": 30, "gender": "male", "employment_type": "salaried", "annual_income_inr": 1_200_000, "tobacco": False},
        {"age": 42, "gender": "female", "employment_type": "self_employed", "annual_income_inr": 2_500_000, "tobacco": True},
        {"age": 28, "gender": "female", "employment_type": "not_working", "annual_income_inr": None, "tobacco": False},
    ]:
        s = profile_snapshot(prof)
        print("\n", prof, "\n max_cover:", s["max_cover"])
        for e in s["eligible"]:
            print("  ", e["product_id"], [(q["sum_assured"], q["annual_premium_range"]) for q in e.get("quotes", [])])
        for x in s["excluded"]:
            print("   x", x["product_id"], "-", x["reason"])
