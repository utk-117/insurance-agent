"""Lead log: one row per session, upserted by session_id. Google Sheets if configured (M5), else data/leads.csv."""
from __future__ import annotations

import csv
import logging
import pathlib
import threading

log = logging.getLogger("sheets")

COLUMNS = ["timestamp_ist", "session_id", "name", "phone", "age", "gender", "city", "goal", "dependents",
           "income_band", "primary_need", "shortlisted", "selected_insurer", "selected_product", "objections",
           "outcome", "callback_time_ist", "purchase_link", "price_asked", "summary", "turns", "avg_first_audio_ms"]
CSV_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "leads.csv"
_lock = threading.Lock()


def upsert(row: dict, path: pathlib.Path = CSV_PATH):
    row = {c: ("" if row.get(c) is None else row.get(c)) for c in COLUMNS}
    with _lock:
        rows = []
        if path.exists():
            with path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        for i, r in enumerate(rows):
            if r.get("session_id") == row["session_id"]:
                rows[i] = row
                break
        else:
            rows.append(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
    log.info("lead row upserted to %s (session %s, outcome %s)", path, row["session_id"], row["outcome"])
    return str(path)
