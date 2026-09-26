"""Text normalisation for TTS only (the transcript keeps the raw text).

  ₹5,00,000 / Rs. 5 lakh -> "5 lakh rupees";  1,00,00,000 -> "1 crore";  98.5% -> "98.5 percent"
  18-65 yrs -> "18 to 65 years";  2026-09-26 -> "26th September";  17:00 / 5:00 PM -> "5 PM"
  IRDAI, ULIP, PED, TPA, GST, KYC, FY -> spoken forms;  markdown, bullets, emojis, URLs stripped.
split_sentences() cuts a reply into TTS-sized chunks.
"""
from __future__ import annotations

import re

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
ABBREV = [  # (pattern, spoken) - word-bounded, case-sensitive for acronyms
    (r"\bIRDAI\b", "I R D A I"), (r"\bIRDA\b", "I R D A"), (r"\bULIPs\b", "U-lips"), (r"\bULIP\b", "U-lip"),
    (r"\bPEDs?\b", "pre-existing disease"), (r"\bTPA\b", "T P A"), (r"\bGST\b", "G S T"), (r"\bKYC\b", "K Y C"),
    (r"\bUIN\b", "U I N"), (r"\bNRI\b", "N R I"), (r"\bOTP\b", "O T P"), (r"\bFY\s?(?=\d)", "financial year "),
    (r"\bFY\b", "financial year"), (r"\bROP\b", "return of premium"), (r"\bSA\b", "sum assured"),
    (r"\be\.g\.", "for example"), (r"\bi\.e\.", "that is"), (r"\betc\.", "etcetera"), (r"\bvs\.?\b", "versus"),
    (r"\bw\.e\.f\.?", "with effect from"), (r"\bapprox\.", "approximately"),
]
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF️‍]")


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return str(n) + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def indian_amount(n: float) -> str:
    """5,00,000 -> '5 lakh'; 1,00,00,000 -> '1 crore'; 25,000 -> '25,000' (commas help Bulbul)."""
    if n >= 1e7:
        return f"{_fmt(n / 1e7)} crore"
    if n >= 1e5:
        return f"{_fmt(n / 1e5)} lakh"
    return f"{int(n):,}" if n == int(n) else _fmt(n)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _money(m):
    amount, unit = m.group("amt"), (m.group("unit") or "").lower()
    if unit in ("lakh", "lakhs", "lac", "lacs", "l"):
        return f"{_fmt(_num(amount))} lakh rupees"
    if unit in ("crore", "crores", "cr"):
        return f"{_fmt(_num(amount))} crore rupees"
    return f"{indian_amount(_num(amount))} rupees"


def _time(h: int, mi: int, ampm: str | None) -> str:
    if ampm:
        ampm = ampm.replace(".", "").upper()
    else:
        ampm = "PM" if h >= 12 else "AM"
        h = h - 12 if h > 12 else (12 if h == 0 else h)
    return f"{h} {ampm}" if mi == 0 else f"{h}:{mi:02d} {ampm}"


def normalize(text: str) -> str:
    if not text:
        return ""
    t = text
    # URLs, markdown, bullets, emojis
    t = re.sub(r"https?://\S+|www\.\S+", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"(\*\*|__|`|~~)", "", t)
    t = re.sub(r"(?m)^\s*(#+|[-*•·]|\d+\.)\s+", "", t)
    t = re.sub(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", t)
    t = EMOJI.sub("", t)
    # money: ₹ / Rs / INR prefix, optional lakh/crore unit
    t = re.sub(r"(?:₹|\bRs\.?|\bINR)\s?(?P<amt>\d[\d,]*(?:\.\d+)?)(?:\s*(?P<unit>lakhs?|lacs?|crores?|cr\b|L\b))?",
               _money, t, flags=re.I)
    # "5 lakh rupees" already fine; bare Indian-grouped numbers >= 1 lakh -> lakh/crore
    t = re.sub(r"\b\d{1,2}(?:,\d{2})+,\d{3}\b", lambda m: indian_amount(_num(m.group())), t)
    # percent
    t = re.sub(r"(\d)\s?%", r"\1 percent", t)
    # ISO / dd/mm/yyyy dates -> "26th September"
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})(?:T[\d:+.]+)?\b",
               lambda m: f"{ordinal(int(m.group(3)))} {MONTHS[int(m.group(2)) - 1]}", t)
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b",
               lambda m: f"{ordinal(int(m.group(1)))} {MONTHS[int(m.group(2)) - 1]}"
               if 1 <= int(m.group(2)) <= 12 else m.group(), t)
    # times: 5:00 PM -> 5 PM, 5pm -> 5 PM, 17:00 -> 5 PM
    t = re.sub(r"\b(\d{1,2})(?::(\d{2}))?\s?([ap]\.?m\.?)(?![a-z])",
               lambda m: _time(int(m.group(1)), int(m.group(2) or 0), m.group(3)), t, flags=re.I)
    t = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s?[AP]M)", lambda m: _time(int(m.group(1)), int(m.group(2)), None), t)
    # ranges of small numbers: 18-65 / 18–65 / 18 - 65 -> "18 to 65"
    t = re.sub(r"\b(\d{1,3})\s?[-–—]\s?(\d{1,3})\b(?!-)", r"\1 to \2", t)
    t = re.sub(r"\byrs?\b\.?", "years", t, flags=re.I)
    t = re.sub(r"\bmths?\b\.?", "months", t, flags=re.I)
    t = re.sub(r"\s&\s", " and ", t)
    for pat, spoken in ABBREV:
        t = re.sub(pat, spoken, t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([,.?!])", r"\1", t)
    return t.strip()


def split_sentences(text: str, min_len: int = 40, max_len: int = 400) -> list:
    """Sentence chunks for TTS. Short sentences merge with the next one; overlong ones split at commas."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?।])\s+", text.strip()) if p.strip()]
    out, buf = [], ""
    for p in parts:
        buf = f"{buf} {p}".strip() if buf else p
        if len(buf) >= min_len:
            out.append(buf)
            buf = ""
    if buf:
        if out and len(buf) < min_len // 2:
            out[-1] = f"{out[-1]} {buf}"
        else:
            out.append(buf)
    final = []
    for s in out:
        while len(s) > max_len:
            cut = s.rfind(",", 0, max_len)
            cut = cut if cut > max_len // 3 else max_len
            final.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        if s:
            final.append(s)
    return final


def split_for_tts(text: str, first_min: int = 12, first_max: int = 70) -> list:
    """Chunks for streaming TTS: a SHORT first chunk (one short sentence or clause) so audio starts sooner, then
    the rest in normal sentence chunks. TTS time grows with text length, and the first chunk is what the
    customer waits for."""
    text = text.strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?।])\s+", text) if p.strip()]
    first = parts[0]
    i = 1
    while len(first) < first_min and i < len(parts):  # "Sure." alone is too short to sound natural
        first = f"{first} {parts[i]}"
        i += 1
    rest = " ".join(parts[i:])
    if len(first) > first_max:  # long first sentence: cut at the first clause break
        m = re.search(r"[,;:—–]\s+", first[first_min:first_max])
        if m:
            cut = first_min + m.end()
            first, rest = first[:cut].strip(), f"{first[cut:].strip()} {rest}".strip()
    return [first] + (split_sentences(rest) if rest else [])
