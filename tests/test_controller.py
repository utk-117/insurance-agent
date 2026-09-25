"""M2: stage machine + field normalisers, without calling an LLM."""
import unittest
from datetime import datetime, timedelta
from unittest import mock

from app.agent import controller as c
from app.agent.state import IST, Stage

NOW = datetime(2026, 9, 25, 23, 32, tzinfo=IST)  # Friday


def out(intent="answered", **kw):
    ex = kw.pop("extracted", {})
    return c.TurnOut.model_validate({"reply": "ok", "intent": intent, "extracted": ex, **kw})


class TestParsers(unittest.TestCase):
    def test_time_text(self):
        cases = {"Tomorrow at 5 pm": (26, 17, 0), "kal shaam 5 baje": (26, 17, 0), "Saturday 11 am": (26, 11, 0),
                 "parso subah 10:30 baje": (27, 10, 30), "Monday morning at 9": (28, 9, 0)}
        for text, (d, h, m) in cases.items():
            with self.subTest(text=text):
                dt = c.parse_time_text(text, NOW)
                self.assertEqual((dt.day, dt.hour, dt.minute), (d, h, m))
        self.assertIsNone(c.parse_time_text("aaj 6 baje", NOW))  # already past
        self.assertIsNone(c.parse_time_text("no idea", NOW))

    def test_income(self):
        for v, want in {"18 lakh": "10–25L", "about 18 lakh a year": "10–25L", "<5L": "<5L", "below 5 lakh": "<5L",
                        "5-10L": "5–10L", "10 se 25 lakh": "10–25L", "30 lakh": "25L+", "25L+": "25L+",
                        "1 crore": "25L+", "4 lakh": "<5L"}.items():
            with self.subTest(v=v):
                self.assertEqual(c.norm_income(v), want)

    def test_goal_dependents_gender(self):
        self.assertEqual(c.norm_goal("child's future"), "child_future")
        self.assertEqual(c.norm_goal("savings + protection"), "savings_protection")
        self.assertEqual(c.norm_dependents("wife and one kid"), "spouse+kids")
        self.assertEqual(c.norm_dependents("none"), "none")
        self.assertEqual(c.norm_gender("F"), "female")

    def test_turn_out_lenient(self):
        t = c.TurnOut.model_validate({"reply": "hi", "intent": "weird", "objection_type": "price",
                                      "extracted": {"age": "34", "dependents": "none", "city": "null"},
                                      "product_refs": ["click 2 protect", "nope"], "topics_needed": ["claims", "x"]})
        self.assertEqual((t.intent, t.objection_type), ("unclear", "other"))
        self.assertEqual((t.extracted.age, t.extracted.dependents, t.extracted.city), (34, "none", None))
        self.assertEqual(t.product_refs, ["hdfc-c2p-supreme"])
        self.assertEqual(t.topics_needed, ["claims"])


class TestTransitions(unittest.TestCase):
    def setUp(self):
        self.s = c.new_session("Rahul", "9876543210")
        self.s.stage = Stage.CONFIRM_IDENTITY

    def test_identity(self):
        c.transition(self.s, out("question"), "Yes, this is Rahul")  # mislabelled intent still moves on
        self.assertEqual(self.s.stage, Stage.DISCOVERY)
        s2 = c.new_session("X", "1")
        s2.stage = Stage.CONFIRM_IDENTITY
        c.transition(s2, out("confirm_no"), "No, wrong number")
        self.assertEqual((s2.stage, s2.outcome), (Stage.END, "wrong_person"))

    def test_not_interested_one_soft_retry(self):
        self.s.stage = Stage.DISCOVERY
        c.transition(self.s, out("not_interested"), "not interested")
        self.assertEqual(self.s.stage, Stage.DISCOVERY)
        self.assertTrue(self.s.soft_retry_used)
        c.transition(self.s, out("not_interested"), "no really")
        self.assertEqual((self.s.stage, self.s.outcome), (Stage.END, "not_interested"))

    def test_repeated_objection_ends(self):
        self.s.stage = Stage.RECOMMEND
        c.transition(self.s, out("objection", objection_type="too_expensive"), "too costly")
        self.assertEqual(self.s.stage, Stage.RECOMMEND)
        c.transition(self.s, out("objection", objection_type="too_expensive"), "still too costly")
        self.assertEqual(self.s.stage, Stage.END)

    def test_discovery_to_need_check(self):
        self.s.stage = Stage.DISCOVERY
        self.s.profile.update(goal="pure_protection", age=34, dependents="spouse+kids", income_band="10–25L",
                              gender="male", city="Pune", motivation="new baby")
        c.transition(self.s, out("answered"), "Pune")
        self.assertEqual(self.s.stage, Stage.NEED_CHECK)
        self.assertEqual(len(self.s.shortlist), 3)
        c.transition(self.s, out("answered"), "Yes, that's right")
        self.assertEqual(self.s.stage, Stage.RECOMMEND)
        self.assertEqual(self.s.pitched_product, self.s.shortlist[0])

    @mock.patch("app.agent.controller.actions.log_callback", return_value={"type": "callback_booked"})
    def test_callback_needs_readback_then_yes(self, log_cb):
        self.s.stage = Stage.QA
        self.s.shortlist = ["hdfc-c2p-supreme"]
        iso = (datetime.now(IST) + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0).isoformat()
        c.transition(self.s, out("wants_callback", extracted={"callback_time_iso": iso}), "tomorrow 5 pm")
        self.assertEqual(self.s.stage, Stage.CALLBACK)
        self.assertIsNotNone(self.s.pending_callback_iso)
        log_cb.assert_not_called()
        # the LLM repeats the same time on the confirming turn: must book, not loop
        ev = c.transition(self.s, out("confirm_yes", extracted={"callback_time_iso": iso}), "Yes")
        log_cb.assert_called_once()
        self.assertEqual(self.s.stage, Stage.END)
        self.assertEqual(ev, [{"type": "callback_booked"}])

    def test_buy_now_without_link_goes_to_callback(self):
        self.s.stage = Stage.RECOMMEND
        self.s.shortlist = ["icici-iprotect-smart-plus"]
        c.transition(self.s, out("wants_to_buy_now"), "I want to buy now")
        self.assertEqual(self.s.stage, Stage.CALLBACK)
        self.assertEqual(self.s.selected_product, "icici-iprotect-smart-plus")

    def test_buy_now_with_link(self):
        self.s.stage = Stage.CLOSE
        self.s.selected_product = "hdfc-c2p-supreme"
        with mock.patch.dict(c.knowledge.cards()["hdfc-c2p-supreme"], {"purchase_url": "https://example.com/p"}):
            ev = c.transition(self.s, out("wants_to_buy_now"), "buy now")
        self.assertEqual(self.s.stage, Stage.PURCHASE_LINK)
        self.assertEqual(ev[0]["type"], "purchase_link")
        self.assertEqual(self.s.outcome, "purchase_link_sent")

    def test_price_asked_flag(self):
        self.s.stage = Stage.QA
        c.transition(self.s, out("asks_price"), "kitna lagega?")
        self.assertTrue(self.s.price_asked)


class TestPrompt(unittest.TestCase):
    def test_no_unfilled_placeholders_and_static_first(self):
        import re
        s = c.new_session("Rahul", "9876543210")
        s.stage = Stage.QA
        s.shortlist = ["hdfc-c2p-supreme"]
        route = c.knowledge.route_topics("claim kaise milega?", {"selected_product": "hdfc-c2p-supreme"})
        blocks = c.build_system(s, Stage.QA, route, objection=True, user_text="claim kaise milega?")
        text = blocks[0]["text"] + blocks[1]["text"]
        self.assertEqual(set(re.findall(r"\{(\w+)\}", text)), set())
        self.assertTrue(blocks[0]["cache"])
        self.assertIn("PRODUCT CARDS", blocks[0]["text"])
        self.assertIn("PROCESS KNOWLEDGE", blocks[0]["text"])
        self.assertNotIn("CURRENT DATE AND TIME NOW", blocks[0]["text"])  # per-turn time stays out of cache
        self.assertIn("too_expensive", blocks[1]["text"])  # playbook loaded
        self.assertIn("claims", blocks[1]["text"])


if __name__ == "__main__":
    unittest.main()
