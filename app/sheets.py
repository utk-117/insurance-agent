"""Lead log: one row per session, upserted by session_id.

Always written to a CSV (data/leads.csv, or LEADS_CSV) as a local backup. If SHEET_ID is set, the same row is
also upserted into the "leads" tab of that Google Sheet, in a background thread so a slow Sheets API never
delays the end of a call. Credentials: GOOGLE_SERVICE_ACCOUNT_JSON (inline JSON or a file path) if set,
otherwise the environment's default identity — on Cloud Run that is the service's own service account, so no
key file is needed: just share the Sheet with that account's email as Editor.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import pathlib
import threading

log = logging.getLogger("sheets")

COLUMNS = ["timestamp_ist", "session_id", "name", "phone", "age", "gender", "employment_type", "annual_income_inr",
           "tobacco", "max_cover", "eligible_products", "intents", "discussed_products", "quoted_ranges", "objections",
           "outcome", "callback_time_ist", "purchase_link", "summary", "turns", "tool_calls", "avg_first_audio_ms"]
CSV_PATH = pathlib.Path(os.getenv("LEADS_CSV") or pathlib.Path(__file__).resolve().parent.parent / "data" / "leads.csv")
_lock = threading.Lock()
_sheet_lock = threading.Lock()
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TAB = "leads"
_ws = None
STATUS = {"sheets_writes": 0, "sheets_errors": 0, "last_error": None}


def upsert(row: dict, path: pathlib.Path | None = None):
    path = pathlib.Path(path or CSV_PATH)
    row = {c: ("" if row.get(c) is None else row.get(c)) for c in COLUMNS}
    with _lock:
        rows = []
        if path.exists():
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                header, rows = reader.fieldnames, list(reader)
            if header and header != COLUMNS:  # older column layout: keep it, start fresh
                old = path.with_name(f"{path.stem}.old-{len(header)}cols{path.suffix}")
                path.rename(old)
                log.warning("lead log columns changed; moved old file to %s", old)
                rows = []
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
    if sheet_id():
        threading.Thread(target=_sheet_upsert_safe, args=(dict(row),), daemon=True).start()
        return f"sheet:{sheet_id()} + {path}"
    return str(path)


# ---- Google Sheets ------------------------------------------------------------------------------

def sheet_id() -> str | None:
    return (os.getenv("SHEET_ID") or "").strip() or None


def _credentials():
    raw = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    if raw:
        from google.oauth2 import service_account
        info = json.loads(raw) if raw.startswith("{") else json.loads(pathlib.Path(raw).read_text())
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    import google.auth
    creds, _ = google.auth.default(scopes=SCOPES)
    return creds


def _worksheet():
    """The 'leads' tab, created with the header row if missing. Cached for the process."""
    global _ws
    if _ws is None:
        import gspread
        book = gspread.authorize(_credentials()).open_by_key(sheet_id())
        try:
            ws = book.worksheet(TAB)
        except gspread.WorksheetNotFound:
            ws = book.add_worksheet(title=TAB, rows=1000, cols=len(COLUMNS))
        if ws.row_values(1) != COLUMNS:
            ws.update(range_name="A1", values=[COLUMNS])
        _ws = ws
    return _ws


def _cell(v):
    if v is None:
        return ""
    return v if isinstance(v, (int, float, bool)) else str(v)


def sheet_upsert(row: dict):
    """Update the row with this session_id, or append it."""
    ws = _worksheet()
    values = [_cell(row.get(c)) for c in COLUMNS]
    ids = ws.col_values(COLUMNS.index("session_id") + 1)
    if row["session_id"] in ids:
        ws.update(range_name=f"A{ids.index(row['session_id']) + 1}", values=[values], value_input_option="RAW")
    else:
        ws.append_row(values, value_input_option="RAW")


def _sheet_upsert_safe(row: dict, attempts: int = 3):
    import time
    with _sheet_lock:  # one writer at a time, so two upserts of the same session can't both append
        for i in range(attempts):
            try:
                sheet_upsert(row)
                STATUS["sheets_writes"] += 1
                log.info("lead row upserted to Google Sheet (session %s, outcome %s)", row["session_id"], row["outcome"])
                return
            except Exception as e:  # network / quota / permission: retry, then keep the CSV copy
                STATUS["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
                log.warning("sheets write failed (attempt %d/%d): %s", i + 1, attempts, STATUS["last_error"])
                time.sleep(1.5 * (i + 1))
        STATUS["sheets_errors"] += 1


def status() -> dict:
    return {"leads": "sheets+csv" if sheet_id() else "csv", **STATUS}
