"""Knowledge-base integrity check. Run after any rebuild:  python data/knowledge/check_integrity.py
Exits non-zero on any broken reference between cards, eligibility, sections, need_fit, topic_router,
insurers, claims_history and insurer notes.
"""
import json, pathlib, sys

K = pathlib.Path(__file__).parent
ROOT = K.parent  # data/
errors = []
load = lambda p: json.loads((K / p).read_text())

cards = {c["id"]: c for c in load("cards.json")["products"]}
rows = load("eligibility.json")["rows"]
need_fit = load("need_fit.json")
router = load("topic_router.json")
insurers = load("insurers.json")["by_name"]
claims = {i["insurer_slug"] for i in load("claims_history.json")["insurers"]}
sections = {}
for pid in cards:
    f = K / "sections" / f"{pid}.json"
    if not f.exists():
        errors.append(f"sections missing for {pid}")
        continue
    sections[pid] = {s["topic"]: s for s in json.loads(f.read_text())["sections"]}

# cards <-> eligibility / insurers / claims / insurer notes / topics_available
for pid, c in cards.items():
    if not any(r["product_id"] == pid for r in rows):
        errors.append(f"{pid}: no eligibility rows")
    slug = insurers.get(c["insurer"])
    if not slug:
        errors.append(f"{pid}: insurer '{c['insurer']}' not in insurers.json")
    else:
        if slug not in claims:
            errors.append(f"{pid}: {slug} missing from claims_history.json")
        if not (ROOT / "insurers" / slug / "insurer.md").exists():
            errors.append(f"{pid}: data/insurers/{slug}/insurer.md missing")
    for t in c.get("topics_available", []):
        s = sections.get(pid, {}).get(t)
        if not s or not s.get("available"):
            errors.append(f"{pid}: topics_available lists '{t}' but section missing/unavailable")
    if c.get("purchase_url") is None:
        print(f"warn: {pid} purchase_url is null (link option will be skipped)")

for r in rows:
    if r["product_id"] not in cards:
        errors.append(f"eligibility row for unknown product {r['product_id']}")

# need_fit
needs = set(need_fit["needs"])
for pid, m in need_fit["products"].items():
    if pid not in cards:
        errors.append(f"need_fit: unknown product {pid}")
        continue
    for need, feats in m.items():
        if need in ("gate", "soft_gate"):
            continue
        if need not in needs:
            errors.append(f"need_fit: {pid} uses unknown need '{need}'")
        for f in feats:
            s = sections.get(pid, {}).get(f["topic"])
            if not s or not s.get("available"):
                errors.append(f"need_fit: {pid}/{need} -> topic '{f['topic']}' missing/unavailable")
for pid in cards:
    if pid not in need_fit["products"]:
        errors.append(f"need_fit: product {pid} has no need mapping")

# topic router
all_topics = {t for s in sections.values() for t in s}
for t in list(router["keywords"]) + router["core_topics"]:
    if t not in all_topics:
        errors.append(f"topic_router: topic '{t}' not present in any sections file")
for pid in router["product_aliases"]:
    if pid not in cards:
        errors.append(f"topic_router: alias for unknown product {pid}")

if errors:
    print("\n".join("ERROR: " + e for e in errors))
    sys.exit(1)
print(f"OK: {len(cards)} products, {len(rows)} eligibility rows, {len(needs)} needs, all references resolve.")
