"""Build Layer 3 (topic sections) by slicing verbatim brochure text between anchors.

specs/<id>.py defines SPANS = {topic: [(start_anchor, end_anchor), ...]}.
Anchors are exact substrings of full_<id>.txt (page-marked text). A start anchor may be
given as (anchor, n) to use its n-th occurrence (0-based). end_anchor None = end of doc.
"""
import json, re, sys, importlib.util, pathlib

TOPICS = ["key_features", "plan_options", "death_benefit", "maturity_benefit",
          "optional_benefits", "riders", "free_look", "grace_period", "suicide_exclusion",
          "surrender_and_paid_up", "loan", "revival", "tax", "claims",
          "non_disclosure_sec45", "other_exclusions"]
PAGE = re.compile(r"<<<PAGE (\d+)>>>")


def find(text, anchor, frm=0):
    n = 0
    if isinstance(anchor, tuple):
        anchor, n = anchor
    pos = frm - 1
    for _ in range(n + 1):
        pos = text.find(anchor, pos + 1)
        if pos < 0:
            raise ValueError(f"anchor not found: {anchor!r}")
    return pos


def page_at(text, pos):
    ms = [m for m in PAGE.finditer(text) if m.start() <= pos]
    return int(ms[-1].group(1)) if ms else 1


def clean(chunk):
    out = []
    for line in PAGE.sub("", chunk).splitlines():
        s = line.strip()
        if not s or re.fullmatch(r"\d{1,2}", s):  # blank / page-number lines
            continue
        out.append(s)
    txt = "\n".join(out)
    txt = txt.replace("`", "₹")  # SBI brochures render the rupee glyph as a backtick
    return txt


def build(pid, source_file):
    text = pathlib.Path(f"full_{pid}.txt").read_text()
    spec_path = pathlib.Path(f"specs/{pid}.py")
    spec = importlib.util.spec_from_file_location(pid, spec_path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    # Drop premium illustrations etc. before slicing (keep page markers so page refs stay right)
    for s, e in getattr(mod, "EXCLUDE", []):
        a = find(text, s); b = find(text, e, a + 1)
        markers = "\n".join(PAGE.findall(text[a:b]) and [f"<<<PAGE {n}>>>" for n in PAGE.findall(text[a:b])])
        text = text[:a] + markers + "\n" + text[b:]
    sections = []
    for topic in TOPICS:
        spans = mod.SPANS.get(topic)
        if not spans:
            sections.append({"topic": topic, "available": False, "text": None, "pages": [],
                             "note": getattr(mod, "NOTES", {}).get(topic,
                                     "Not covered in the brochure. Say so and offer an advisor callback.")})
            continue
        parts, pages = [], set()
        for s, e in spans:
            a = find(text, s)
            b = find(text, e, a + 1) if e else len(text)
            b = a + len(re.sub(r"(\s*<<<PAGE \d+>>>\s*)+$", "", text[a:b]).rstrip())
            parts.append(clean(text[a:b]))
            pages.update(range(page_at(text, a), page_at(text, max(a, b - 1)) + 1))
        sec = {"topic": topic, "available": True, "text": "\n\n".join(parts),
               "pages": sorted(pages)}
        if topic in getattr(mod, "NOTES", {}):
            sec["note"] = mod.NOTES[topic]
        sections.append(sec)
    return {"product_id": pid, "source_file": source_file, "sections": sections}


if __name__ == "__main__":
    pid, src = sys.argv[1], sys.argv[2]
    out = build(pid, src)
    pathlib.Path("out/sections").mkdir(parents=True, exist_ok=True)
    pathlib.Path(f"out/sections/{pid}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    for s in out["sections"]:
        print(f"{s['topic']:24s} {'OK ' if s['available'] else '-- '} pages={s['pages']} chars={len(s['text'] or '')}")
