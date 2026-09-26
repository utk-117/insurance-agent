"""Phase 1 intake: 5 fixed slots, asked in order, decided in code.

Code parses the customer's words first (deterministic, so the reply can ask the right next question);
the LLM's `extracted` values fill anything code couldn't parse.
"""
from __future__ import annotations

import re

from app.agent import knowledge

SLOTS = ["age", "gender", "employment_type", "annual_income_inr", "tobacco"]
EMPLOYMENT = ["salaried", "self_employed", "not_working"]

_NOT_WORKING = re.compile(r"\b(house ?wife|home ?maker|housewife|student|retired|unemployed|not working|"
                          r"between jobs|no job|kaam nahi|naukri nahi|ghar sambhal|gruhini|grihini)\b", re.I)
_SELF_EMP = re.compile(r"\b(self[- ]?employed|business|businessman|dukaan|dukan|shop|freelanc\w*|consultant|"
                       r"own (?:firm|company|practice|clinic)|khud ka|apna kaam|vyapaar|vyapar|trader|farmer|kisan|"
                       r"proprietor|entrepreneur)\b", re.I)
_SALARIED = re.compile(r"\b(salaried|salary|job|naukri|employee|employed|work(?:ing)? (?:at|in|for)|"
                       r"private company|govt|government|sarkari|mnc|it company)\b", re.I)
_FEMALE = re.compile(r"\b(female|woman|lady|ladki|mahila|aurat|housewife|homemaker|gruhini|grihini)\b", re.I)
_MALE = re.compile(r"\b(male|man|gent|ladka|purush|aadmi)\b", re.I)
_FEMALE_FORMS = re.compile(r"\b(rahi|rehti|rahti|karti|chahti|sakti|gayi|jaati|leti|deti|sochti|hoti) (hoon|hun|hu)\b", re.I)
_MALE_FORMS = re.compile(r"\b(raha|rehta|rahta|karta|chahta|sakta|gaya|jaata|leta|deta|sochta|hota) (hoon|hun|hu)\b", re.I)
_TOBACCO_NO = re.compile(r"\b(non[- ]?smoker|don'?t smoke|do not smoke|never|no tobacco|nahi(?:n)?|nahin|na|no|nope|"
                         r"kabhi nahi|bilkul nahi|not at all|quit (?:over|more than) (?:a|one|1|2|two) years?)\b", re.I)
_TOBACCO_YES = re.compile(r"\b(yes|haan|han|ha|smoke|smoking|smoker|cigarette|cigarettes|bidi|beedi|gutka|gutkha|"
                          r"pan masala|khaini|hookah|vape|vaping|chew|occasionally|kabhi kabhi|sometimes|socially)\b", re.I)
_UNITS = {"k": 1e3, "thousand": 1e3, "hazaar": 1e3, "hazar": 1e3, "hajar": 1e3, "lakh": 1e5, "lakhs": 1e5,
          "lac": 1e5, "lacs": 1e5, "l": 1e5, "lpa": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7}
_MONTHLY = re.compile(r"\b(month|monthly|mahina|mahine|mahina|per month|pm|a month|har mahine)\b", re.I)
_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)(?:\s*(?:-|–|to|se)\s*(\d+(?:\.\d+)?))?\s*"
                       r"(k|thousand|hazaar|hazar|hajar|lakhs?|lacs?|lpa|l|crores?|cr)?\b", re.I)


def parse_age(text: str, expecting: bool) -> int | None:
    t = text.lower()
    m = re.search(r"\b(\d{1,2})\s*(?:years?|yrs?|saal|sal|baras)\b", t) or \
        re.search(r"\b(?:age|umar|umra|i am|i'm|im|main)\s*(?:is\s*)?(\d{1,2})\b", t)
    if not m and expecting:  # first 1-2 digit number that isn't an amount ("18 lakh", "80k") or a range
        m = re.search(r"(?<![\d.,-])\b(\d{1,2})\b(?!\s*(?:lakhs?|lacs?|l\b|k\b|crores?|cr\b|thousand|hazaa?r|"
                      r"hajar|lpa|%|[-–.,]\d|se\s+\d|to\s+\d))", t)
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 99 else None


def parse_gender(text: str, expecting: bool) -> str | None:
    if _FEMALE_FORMS.search(text) or _FEMALE.search(text):
        return "female"
    if _MALE_FORMS.search(text) or _MALE.search(text):
        return "male"
    return None


def parse_employment(text: str, expecting: bool) -> str | None:
    if _NOT_WORKING.search(text):
        return "not_working"
    if _SELF_EMP.search(text):
        return "self_employed"
    if _SALARIED.search(text):
        return "salaried"
    return None


def parse_income(text: str, expecting: bool) -> int | None:
    """'80k per month' -> 960000; '12-15 lakh' -> 1350000; '18 LPA' -> 1800000; '₹9,60,000' -> 960000."""
    t = text.lower().replace(",", "").replace("₹", " ").replace("rs.", " ").replace("rs ", " ")
    best = None
    for m in _NUM_UNIT.finditer(t):
        lo, hi, unit = float(m.group(1)), m.group(2), (m.group(3) or "").lower()
        val = (lo + float(hi)) / 2 if hi else lo
        if unit:
            val *= _UNITS[unit]
        elif val < 1000:  # bare small number: not an income unless we asked for it and it's plausible lakhs
            if not expecting or val > 500:
                continue
            val *= 1e5 if val <= 200 else 1  # "18" when asked for yearly income ≈ 18 lakh
        if val < 10_000:
            continue
        best = val
        break
    if best is None:
        return None
    if _MONTHLY.search(t):
        best *= 12
    return int(round(best))


def parse_tobacco(text: str, expecting: bool) -> bool | None:
    t = text.lower()
    if re.search(r"\b(non[- ]?smoker|don'?t smoke|do not smoke|no tobacco|never smoked?)\b", t):
        return False
    if re.search(r"\b(i smoke|smoker|smoking|cigarettes?|gutkha?|bidi|beedi|khaini|pan masala|vap(?:e|ing))\b", t) \
            and not re.search(r"\b(nahi|nahin|no|never|don'?t|not)\b", t):
        return True
    if not expecting:
        return None
    if _TOBACCO_NO.search(t) and not _TOBACCO_YES.search(t.replace("haan", "")):
        return False
    if _TOBACCO_YES.search(t):
        return True
    if _TOBACCO_NO.search(t):
        return False
    return None


PARSERS = {"age": parse_age, "gender": parse_gender, "employment_type": parse_employment,
           "annual_income_inr": parse_income, "tobacco": parse_tobacco}


def missing(profile: dict) -> list:
    out = []
    for s in SLOTS:
        if s == "annual_income_inr" and profile.get("employment_type") == "not_working":
            continue
        if profile.get(s) is None:
            out.append(s)
    return out


def next_slot(profile: dict) -> str | None:
    m = missing(profile)
    return m[0] if m else None


def parse_turn(text: str, profile: dict) -> dict:
    """Slots code can read from this message. The expected slot gets lenient parsing ('haan', a bare number)."""
    expected = next_slot(profile)
    found = {}
    for slot in SLOTS:
        if profile.get(slot) is not None:
            continue
        v = PARSERS[slot](text, slot == expected)
        if v is not None:
            found[slot] = v
    if found.get("employment_type") == "not_working":
        found.pop("annual_income_inr", None)
    return found


def clean_llm_value(slot: str, v):
    """Validate an LLM-extracted slot value; None if unusable."""
    if v is None or v == "":
        return None
    if slot == "age":
        try:
            a = int(float(v))
        except (TypeError, ValueError):
            return None
        lo, hi = next(q["valid"] for q in knowledge.underwriting_rules()["intake_questions"] if q["slot"] == "age")
        return a if lo <= a <= hi else None
    if slot == "gender":
        s = str(v).lower()
        return s if s in ("male", "female", "other") else parse_gender(s, True)
    if slot == "employment_type":
        s = str(v).lower().replace("-", "_").replace(" ", "_")
        return s if s in EMPLOYMENT else parse_employment(str(v), True)
    if slot == "annual_income_inr":
        if isinstance(v, (int, float)):
            return int(v) if v >= 10_000 else None
        return parse_income(str(v), True)
    if slot == "tobacco":
        if isinstance(v, bool):
            return v
        return parse_tobacco(str(v), True)
    return None


def question(slot: str) -> dict:
    return next(q for q in knowledge.underwriting_rules()["intake_questions"] if q["slot"] == slot)
