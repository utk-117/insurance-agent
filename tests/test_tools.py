"""M2b: every consult tool, incl. the Phase 3 guards (book_callback, share_purchase_link, end_conversation)."""
import pathlib
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from app import sheets
from app.agent import knowledge, tools
from app.agent.state import Phase, SessionState, now_ist

PROFILE = {"age": 30, "gender": "male", "employment_type": "salaried", "annual_income_inr": 1_200_000, "tobacco": False}


def consult_state():
    s = SessionState(lead={"name": "Rahul", "phone": "9876543210"})
    s.profile = dict(PROFILE)
    s.snapshot = knowledge.profile_snapshot(dict(PROFILE))
    s.phase = Phase.CONSULT
    return s


def say(state, agent_text, user_text="yes"):
    state.add("agent", agent_text)
    state.add("user", user_text)


class TestInfoTools(unittest.TestCase):
    def setUp(self):
        self.s = consult_state()

    def test_product_info(self):
        r = tools.run(self.s, "get_product_info", {"product_id": "hdfc-c2p-supreme", "topics": ["free_look", "tax"]})
        self.assertTrue(r["ok"])
        self.assertEqual([x["topic"] for x in r["sections"]], ["free_look", "tax"])
        self.assertTrue(r["sections"][0]["pages"])
        self.assertIn("hdfc-c2p-supreme", self.s.discussed_products)

    def test_premium_estimate(self):
        r = tools.run(self.s, "get_premium_estimate", {"product_id": "sbi-smart-shield-plus", "sum_assured": 20_000_000})
        self.assertTrue(r["ok"])
        lo, hi = r["annual_premium_range"]
        self.assertLess(lo, hi)
        self.assertIn("indicative", r["disclaimer"].lower())
        self.assertEqual(self.s.quoted[-1]["sum_assured"], 20_000_000)
        above = tools.run(self.s, "get_premium_estimate", {"product_id": "sbi-smart-shield-plus", "sum_assured": 50_000_000})
        self.assertIn("above_max_cover", above)
        bad = tools.run(self.s, "get_premium_estimate", {"product_id": "icici-assured-savings", "sum_assured": 10_000_000})
        self.assertFalse(bad["ok"])  # excluded for this customer
        sav = tools.run(self.s, "get_premium_estimate", {"product_id": "hdfc-sanchay-plus", "sum_assured": 10_000_000})
        self.assertFalse(sav["ok"])  # savings plan -> use the illustration tool

    def test_savings_illustration(self):
        r = tools.run(self.s, "get_savings_illustration", {"product_id": "sbi-smart-bachat-plus", "annual_premium": 100_000})
        self.assertTrue(r["ok"])
        self.assertIn("4%", r["must_say"])
        self.assertFalse(tools.run(self.s, "get_savings_illustration",
                                   {"product_id": "hdfc-c2p-supreme", "annual_premium": 100_000})["ok"])

    def test_claims_compare_process(self):
        r = tools.run(self.s, "get_claims_record", {"insurer_slug": "sbi-life"})
        self.assertTrue(r["ok"] and r["rows"][0]["paid_pct_by_amount"])
        c = tools.run(self.s, "compare_products", {"product_ids": ["hdfc-c2p-supreme", "icici-iprotect-smart-plus"]})
        self.assertTrue(c["ok"])
        self.assertEqual(len(c["products"]), 2)
        self.assertTrue(c["products"][0]["price_ranges"])
        self.assertFalse(tools.run(self.s, "compare_products", {"product_ids": ["hdfc-c2p-supreme"]})["ok"])
        p = tools.run(self.s, "get_process_info", {"topic": "medical_tests", "insurer_slug": "hdfc-life"})
        self.assertTrue(p["ok"] and p["text"] and p["insurer_notes"])
        self.assertFalse(tools.run(self.s, "get_process_info", {"topic": "astrology"})["ok"])

    def test_bad_calls_never_raise(self):
        self.assertFalse(tools.run(self.s, "nope", {})["ok"])
        self.assertFalse(tools.run(self.s, "get_claims_record", {"wrong_arg": 1})["ok"])
        self.assertEqual(sum(not c["ok"] for c in self.s.tool_calls), 2)


class TestCloseGuards(unittest.TestCase):
    def setUp(self):
        self.s = consult_state()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name
        self.patch = mock.patch.object(sheets, "CSV_PATH", self.tmp)
        self.patch.start()
        self.when = (now_ist() + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)

    def tearDown(self):
        self.patch.stop()

    def test_callback_needs_confirmation(self):
        say(self.s, f"So that's {self.when:%A}, {self.when.day}th at 5 PM, okay?")
        r = tools.run(self.s, "book_callback", {"datetime_iso": self.when.isoformat(), "customer_confirmed": False})
        self.assertFalse(r["ok"])
        self.assertIsNone(self.s.callback_time)

    def test_callback_rejects_past_and_far_future(self):
        say(self.s, "Booking it.")
        past = tools.run(self.s, "book_callback", {"datetime_iso": (now_ist() - timedelta(hours=1)).isoformat(),
                                                   "customer_confirmed": True})
        far = tools.run(self.s, "book_callback", {"datetime_iso": (now_ist() + timedelta(days=20)).isoformat(),
                                                  "customer_confirmed": True})
        self.assertFalse(past["ok"])
        self.assertIn("past", past["error"])
        self.assertFalse(far["ok"])
        self.assertFalse(tools.run(self.s, "book_callback", {"datetime_iso": "kal", "customer_confirmed": True})["ok"])

    def test_callback_needs_read_back(self):
        say(self.s, "Sure, when would suit you?", "tomorrow 5 pm")
        r = tools.run(self.s, "book_callback", {"datetime_iso": self.when.isoformat(), "customer_confirmed": True})
        self.assertFalse(r["ok"])
        self.assertIn("read back", r["error"])

    def test_callback_books_and_logs(self):
        say(self.s, f"Just to confirm: {self.when:%A}, {self.when.day} {self.when:%B} at 5 PM on 9876543210?", "Yes")
        r = tools.run(self.s, "book_callback", {"datetime_iso": self.when.isoformat(), "customer_confirmed": True,
                                                "product_ids": ["hdfc-c2p-supreme"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.s.outcome, "callback_scheduled")
        self.assertEqual(self.s.phase, Phase.WRAP_UP)
        self.assertEqual(self.s.events[-1]["type"], "callback_booked")
        rows = pathlib.Path(self.tmp).read_text()
        self.assertIn("callback_scheduled", rows)
        self.assertIn(self.s.session_id, rows)

    def test_purchase_link(self):
        r = tools.run(self.s, "share_purchase_link", {"product_id": "sbi-smart-shield-plus"})
        self.assertFalse(r["ok"])  # purchase_url is null in cards.json
        with mock.patch.dict(knowledge.cards()["hdfc-c2p-supreme"], {"purchase_url": "https://example.com/c2p"}):
            r = tools.run(self.s, "share_purchase_link", {"product_id": "hdfc-c2p-supreme"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.s.outcome, "purchase_link_sent")
        self.assertEqual(self.s.events[-1]["type"], "purchase_link")

    def test_end_conversation_cannot_fake_a_close(self):
        r = tools.run(self.s, "end_conversation", {"outcome": "callback_scheduled"})
        self.assertEqual(r["outcome"], "dropped")  # no callback was booked
        self.assertEqual(self.s.phase, Phase.END)
        s2 = consult_state()
        s2.callback_time = "2026-09-27T17:00+05:30"
        self.assertEqual(tools.run(s2, "end_conversation", {"outcome": "not_interested"})["outcome"],
                         "callback_scheduled")

    def test_specs_valid(self):
        names = [t["name"] for t in tools.tool_specs()]
        self.assertEqual(set(names), set(tools.IMPL))
        for t in tools.tool_specs():
            self.assertEqual(t["parameters"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
