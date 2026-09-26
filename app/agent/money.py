"""Rupee amounts for the LLM: code converts, the model only reads words.

The Sarvam LLM misread raw integers by 10x in both directions (200000000 said as "2 crore"; "30 crore" sent as
30000000), so no raw rupee integer is ever shown to the model, and amounts it sends back are parsed here.

  money(200000000)                 -> "₹20 crore"
  money_range(860500, 1344500)     -> "₹8.6 lakh – ₹13.45 lakh a year"
  words_in_text("Rs 25,32,440 at maturity", 2) -> "₹50.65 lakh at maturity"
  parse_amount("30Cr") -> 300000000;  parse_amount("50 lakh") -> 5000000
"""
from __future__ import annotations

import re

_UNITS = {"k": 1e3, "thousand": 1e3, "hazaar": 1e3, "hazar": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
          "lacs": 1e5, "l": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "karod": 1e7, "karor": 1e7}
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(k|thousand|hazaa?r|lakhs?|lacs?|l|crores?|cr|karod|karor)\b", re.I)
_GROUPED = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?(\d{1,3}(?:,\d{2,3})+|\d+)(?!\s*(?:lakh|lac|crore|cr)\b)", re.I)


def _fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def money(n) -> str | None:
    """Indian words for a rupee amount: crore / lakh above 1 lakh, grouped digits below."""
    if n is None:
        return None
    n = float(n)
    if n >= 1e7:
        return f"₹{_fmt(n / 1e7)} crore"
    if n >= 1e5:
        return f"₹{_fmt(n / 1e5)} lakh"
    return f"₹{int(round(n)):,}"


def money_range(lo, hi, per: str = "a year") -> str:
    return f"{money(lo)} – {money(hi)}{' ' + per if per else ''}"


_BARE = re.compile(r"(?<![\d.])\b(\d{1,3}(?:,\d{2,3}){2,})\b")


def words_in_text(text: str, factor: float = 1.0, bare: bool = False) -> str:
    """Rewrite 'Rs 25,32,440' / '₹10,000,000' inside a string as words, optionally scaled by factor.
    bare=True also rewrites un-prefixed grouped numbers of a lakh or more ('5,000,000')."""
    out = _GROUPED.sub(lambda m: money(float(m.group(1).replace(",", "")) * factor), text or "")
    if bare:
        out = _BARE.sub(lambda m: money(float(m.group(1).replace(",", "")) * factor)
                        if float(m.group(1).replace(",", "")) >= 1e5 else m.group(1), out)
    return out


def parse_amount(text) -> int | None:
    """Cover / premium amount from the model's or customer's words. Needs a unit or rupee grouping, so a bare
    '30' is never guessed. '30Cr' -> 300000000, '₹2 crore' -> 20000000, '30,00,00,000' -> 300000000."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text) if text >= 1000 else None
    t = str(text).lower().replace("₹", " ").replace("rs.", " ").replace("rs ", " ")
    m = _AMOUNT.search(t.replace(",", ""))
    if m:
        return int(round(float(m.group(1)) * _UNITS[m.group(2).lower()]))
    m = re.search(r"\b(\d{1,3}(?:,\d{2,3})+|\d{5,})\b", t)
    return int(m.group(1).replace(",", "")) if m else None
