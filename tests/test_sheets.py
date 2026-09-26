"""M5: lead log upsert to Google Sheets (fake worksheet) + CSV backup."""
import pathlib
import tempfile
import unittest
from unittest import mock

from app import sheets


class FakeWorksheet:
    def __init__(self):
        self.rows = [sheets.COLUMNS]

    def col_values(self, col):
        return [r[col - 1] for r in self.rows]

    def update(self, range_name, values, value_input_option=None):
        i = int(range_name[1:]) - 1
        self.rows[i] = values[0]

    def append_row(self, values, value_input_option=None):
        self.rows.append(values)


def row(sid, outcome):
    return {"session_id": sid, "name": "Rahul", "phone": "9876543210", "outcome": outcome, "tobacco": False,
            "max_cover": 30000000, "summary": None}


class TestSheets(unittest.TestCase):
    def setUp(self):
        self.ws = FakeWorksheet()
        self.p = [mock.patch.object(sheets, "_worksheet", return_value=self.ws)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_upsert_updates_same_session(self):
        sheets.sheet_upsert(row("s1", "dropped"))
        sheets.sheet_upsert(row("s2", "not_interested"))
        sheets.sheet_upsert(row("s1", "callback_scheduled"))  # same session again: update, not a new row
        self.assertEqual(len(self.ws.rows), 3)
        r1 = self.ws.rows[1]
        self.assertEqual(r1[sheets.COLUMNS.index("outcome")], "callback_scheduled")
        self.assertEqual(r1[sheets.COLUMNS.index("summary")], "")
        self.assertIs(r1[sheets.COLUMNS.index("tobacco")], False)

    def test_upsert_writes_csv_and_sheet(self):
        tmp = pathlib.Path(tempfile.mkdtemp()) / "leads.csv"
        full = {c: "" for c in sheets.COLUMNS} | row("s9", "callback_scheduled")
        with mock.patch.dict("os.environ", {"SHEET_ID": "abc123"}), \
                mock.patch.object(sheets.threading, "Thread") as T:
            where = sheets.upsert(full, tmp)
            T.assert_called_once()                       # sheet write runs in the background
            T.call_args.kwargs["target"](*T.call_args.kwargs["args"])  # run it here
        self.assertIn("sheet:abc123", where)
        self.assertIn("s9", tmp.read_text())             # CSV backup always written
        self.assertEqual(self.ws.rows[-1][sheets.COLUMNS.index("session_id")], "s9")

    def test_sheet_failure_keeps_csv_and_is_counted(self):
        before = sheets.STATUS["sheets_errors"]
        with mock.patch.object(sheets, "sheet_upsert", side_effect=PermissionError("not shared")), \
                mock.patch("time.sleep"):
            sheets._sheet_upsert_safe(row("s3", "dropped"), attempts=2)
        self.assertEqual(sheets.STATUS["sheets_errors"], before + 1)
        self.assertIn("not shared", sheets.STATUS["last_error"])

    def test_flush_waits_for_pending_writes(self):
        import threading
        done = []
        t = threading.Thread(target=lambda: done.append(1))
        sheets._pending.append(t)
        t.start()
        sheets.flush(2)
        self.assertEqual(done, [1])
        self.assertEqual(sheets._pending, [])

    def test_no_sheet_id_means_csv_only(self):
        tmp = pathlib.Path(tempfile.mkdtemp()) / "leads.csv"
        with mock.patch.dict("os.environ", {"SHEET_ID": ""}):
            self.assertEqual(sheets.upsert({"session_id": "x", "outcome": "dropped"}, tmp), str(tmp))
            self.assertEqual(sheets.status()["leads"], "csv")


if __name__ == "__main__":
    unittest.main()
