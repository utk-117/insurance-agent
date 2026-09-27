"""Assemble the 3-layer knowledge base from specs/*.py into out/.

out/cards.json          Layer 1 - short card per product (always in the prompt)
out/eligibility.json    Layer 2 - eligibility rows (code-only filter)
out/sections/<id>.json  Layer 3 - verbatim brochure text by topic, with page refs (loaded on demand)
"""
import importlib.util, json, pathlib, re, datetime
import slice as slicer

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "out"
TODAY = datetime.date.today().isoformat()


def load(pid):
    spec = importlib.util.spec_from_file_location(pid, ROOT / "specs" / f"{pid}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def main():
    ids = sorted(p.stem for p in (ROOT / "specs").glob("*.py"))
    cards, rows = [], []
    (OUT / "sections").mkdir(parents=True, exist_ok=True)
    for pid in ids:
        m = load(pid)
        card = dict(m.CARD)
        assert card["id"] == pid, pid
        sec = slicer.build(pid, m.SOURCE)
        card["topics_available"] = [s["topic"] for s in sec["sections"] if s["available"]]
        cards.append(card)
        rows += m.ELIGIBILITY
        sec["_meta"] = {"extracted_on": TODAY, "method": "verbatim brochure text sliced between anchors; page numbers are PDF page indices",
                        "how_to_use": "Answer only from 'text'. If available=false, say the brochure does not cover it and offer an advisor callback. Never quote premiums or illustration figures."}
        (OUT / "sections" / f"{pid}.json").write_text(json.dumps(sec, ensure_ascii=False, indent=2))
    meta = {"extracted_on": TODAY, "source": "Official product brochures (English) downloaded from sbilife.co.in, iciciprulife.com, hdfclife.com",
            "review_status": "machine-built from brochures and hand-checked against the rendered eligibility tables; human review pending"}
    (OUT / "cards.json").write_text(json.dumps({"_meta": {**meta, "how_to_use": "Always in the prompt (minus topics_available, source_file, uin). Pitch from pitch_line/key_benefits. No prices here: premiums only as ranges from SNAPSHOT / the pricing tools (pricing.json)."}, "products": cards}, ensure_ascii=False, indent=2))
    (OUT / "eligibility.json").write_text(json.dumps({"_meta": {**meta, "how_to_use": "Code-only filter (see eligibility.py). Use channel='all' rows for this agent; 'pos' rows are for POSP sales and are kept for completeness."}, "rows": rows}, ensure_ascii=False, indent=2))
    print(f"{len(cards)} cards, {len(rows)} eligibility rows, {len(ids)} section files")


if __name__ == "__main__":
    main()
