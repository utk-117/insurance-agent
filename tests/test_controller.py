"""M2b: v2 phase controller end to end with a scripted fake LLM (no network)."""
import asyncio
import pathlib
import re
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from app import sheets
from app.agent import controller as c
from app.agent.state import Phase, now_ist


class FakeLLM:
    """complete_json / chat_with_tools return scripted responses in order; every system prompt is recorded."""
    tool_mode = "native"

    def __init__(self, json_replies=(), tool_replies=()):
        self.json_replies, self.tool_replies = list(json_replies), list(tool_replies)
        self.systems, self.tool_msgs = [], []

    async def complete_json(self, system, messages, schema):
        self.systems.append(system)
        data = self.json_replies.pop(0) if self.json_replies else {"summary": "test summary", "intents": ["x"]}
        return {"data": data, "provider_ms": 5, "input_tokens": 1, "output_tokens": 1}

    async def chat_with_tools(self, system, messages, tools, allow_tools=True):
        self.systems.append(system)
        self.tool_msgs.append(list(messages))
        r = self.tool_replies.pop(0)
        return {"reply": r.get("reply"), "tool_calls": r.get("tool_calls", []), "raw": None, "provider_ms": 7,
                "input_tokens": 1, "output_tokens": 1}


def sys_text(system):
    return "\n".join(b["text"] for b in system)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name
        self.patches = [mock.patch.object(sheets, "CSV_PATH", self.tmp)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def run_with(self, fake, coro):
        with mock.patch.object(c, "get_llm", return_value=fake):
            return asyncio.run(coro)


class TestFlow(Base):
    def test_full_v2_flow(self):
        when = (now_ist() + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
        readback = f"Just to confirm, {when:%A} {when.day} {when:%B} at 5 PM on 9876543210?"
        fake = FakeLLM(
            json_replies=[
                {"reply": "Hello, I'm Asha, an AI assistant. Am I speaking with Rahul?", "reply_language": "en-IN",
                 "intent": "unclear"},
                {"reply": "Thanks Rahul! Do you have two minutes?", "reply_language": "en-IN", "intent": "confirm_yes"},
                {"reply": "Five quick questions. May I know your age?", "reply_language": "en-IN",
                 "extracted": {}, "intent": "answered"},
                {"reply": "Thanks. And your gender?", "reply_language": "en-IN",
                 "extracted": {"age": 30}, "intent": "answered"},
            ],
            tool_replies=[
                {"reply": "You can get term cover of up to about 3 crore. What would you like it to do for you?"},
                {"reply": None, "tool_calls": [{"id": "t1", "name": "get_premium_estimate",
                                                "args": {"product_id": "sbi-smart-shield-plus",
                                                         "cover": "2 crore"}}]},
                {"reply": "For 2 crore it's roughly in this range, indicative only. Shall I set up an advisor call?"},
                {"reply": readback},
                {"reply": None, "tool_calls": [{"id": "t2", "name": "book_callback",
                                                "args": {"datetime_iso": when.isoformat(),
                                                         "customer_confirmed": True}}]},
                {"reply": "Booked! Anything else?"},
                {"reply": "Thank you Rahul, goodbye!", "tool_calls": [{"id": "t3", "name": "end_conversation",
                                                                        "args": {"outcome": "callback_scheduled"}}]},
            ])

        async def convo():
            s = c.new_session("Rahul", "9876543210")
            await c.start(s)
            self.assertEqual(s.phase, Phase.CONFIRM_IDENTITY)
            await c.handle_turn(s, "Yes, speaking")
            self.assertEqual(s.phase, Phase.INTAKE)
            await c.handle_turn(s, "Sure")
            self.assertIn("NEXT SLOT: age", sys_text(fake.systems[-1]))
            await c.handle_turn(s, "thirty")          # code can't parse it; the LLM's extraction fills age
            self.assertEqual(s.profile["age"], 30)
            await c.handle_turn(s, "male")
            await c.handle_turn(s, "salaried, 12 lakh a year, never smoked")  # completes intake in code
            self.assertEqual(s.phase, Phase.CONSULT)
            self.assertEqual(s.snapshot["max_cover"], 30_000_000)
            self.assertIn("CONSULT (opening)", sys_text(fake.systems[-1]))
            self.assertIn('"max_cover": "₹3 crore"', sys_text(fake.systems[-1]))
            r = await c.handle_turn(s, "What would 2 crore cover cost?")
            self.assertEqual(r["tool_calls"], [{"name": "get_premium_estimate", "ok": True}])
            self.assertEqual(s.quoted[-1]["sum_assured"], 20_000_000)
            await c.handle_turn(s, "Yes, tomorrow at 5 pm")
            self.assertEqual(s.phase, Phase.CLOSE)
            self.assertIn("Code resolved the time", sys_text(fake.systems[-1]))
            r = await c.handle_turn(s, "Yes")
            self.assertEqual(r["events"][0]["type"], "callback_booked")
            self.assertEqual(s.phase, Phase.WRAP_UP)
            r = await c.handle_turn(s, "No, that's all, bye")
            self.assertTrue(r["ended"])
            return s

        s = self.run_with(fake, convo())
        self.assertEqual(s.outcome, "callback_scheduled")
        self.assertEqual(s.summary, "test summary")
        row = pathlib.Path(self.tmp).read_text()
        self.assertIn("callback_scheduled", row)
        self.assertIn("sbi-smart-shield-plus@20000000", row)

    def test_wrong_person(self):
        fake = FakeLLM(json_replies=[
            {"reply": "Hi, am I speaking with Priya?", "reply_language": "en-IN", "intent": "unclear"},
            {"reply": "Sorry for the trouble, goodbye.", "reply_language": "en-IN", "intent": "wrong_person"}])

        async def convo():
            s = c.new_session("Priya", "9876543210")
            await c.start(s)
            return s, await c.handle_turn(s, "No, wrong number")

        s, r = self.run_with(fake, convo())
        self.assertTrue(r["ended"])
        self.assertEqual(s.outcome, "wrong_person")

    def test_not_interested_one_soft_retry(self):
        fake = FakeLLM(json_replies=[
            {"reply": "Hi, Amit?", "reply_language": "en-IN", "intent": "unclear"},
            {"reply": "Totally fine — could I take just two minutes?", "reply_language": "en-IN",
             "intent": "not_interested"},
            {"reply": "Understood, thank you. Goodbye!", "reply_language": "en-IN", "intent": "not_interested"}])

        async def convo():
            s = c.new_session("Amit", "9876543210")
            await c.start(s)
            r1 = await c.handle_turn(s, "Not interested")
            r2 = await c.handle_turn(s, "No really")
            return s, r1, r2

        s, r1, r2 = self.run_with(fake, convo())
        self.assertFalse(r1["ended"])
        self.assertTrue(r2["ended"])
        self.assertEqual(s.outcome, "not_interested")

    def test_several_slots_then_gender_asked(self):
        fake = FakeLLM(json_replies=[{"reply": "And your gender?", "reply_language": "en-IN", "extracted": {},
                                      "intent": "answered"}])

        async def convo():
            s = c.new_session("Rahul", "9876543210")
            s.phase = Phase.INTAKE
            await c.handle_turn(s, "32, salaried, 18 lakh a year, non-smoker")
            return s

        s = self.run_with(fake, convo())
        self.assertEqual(s.profile, {"age": 32, "gender": None, "employment_type": "salaried",
                                     "annual_income_inr": 1_800_000, "tobacco": False})
        self.assertIn("NEXT SLOT: gender", sys_text(fake.systems[-1]))

    def test_tool_rounds_capped(self):
        loop_call = {"reply": None, "tool_calls": [{"id": "x", "name": "get_claims_record",
                                                    "args": {"insurer_slug": "sbi-life"}}]}
        fake = FakeLLM(tool_replies=[loop_call, loop_call, {"reply": "Here's the record.", "tool_calls": []}])

        async def convo():
            s = c.new_session("Rahul", "9876543210")
            s.profile = {"age": 30, "gender": "male", "employment_type": "salaried",
                         "annual_income_inr": 1_200_000, "tobacco": False}
            c._finish_intake(s)
            s.consult_opened = True
            return s, await c.handle_turn(s, "Does SBI pay claims?")

        s, r = self.run_with(fake, convo())
        self.assertEqual(r["reply"], "Here's the record.")
        self.assertEqual(len(r["tool_calls"]), 2)  # 2 rounds, then the model had to answer
        self.assertEqual(s.metrics["tool_rounds"], 2)


class TestIntakeMemory(Base):
    def test_gender_from_identity_turn_is_not_asked_again(self):
        fake = FakeLLM(json_replies=[{"reply": "Salaried hain ya self-employed?", "reply_language": "hi-IN",
                                      "extracted": {}, "intent": "answered"}])

        async def convo():
            s = c.new_session("Rahul", "9876543210")
            s.add("agent", "Kya main Rahul se baat kar rahi hoon?")
            s.add("user", "Haan ji, bol raha hoon")
            s.phase = Phase.INTAKE
            await c.handle_turn(s, "36")
            return s

        s = self.run_with(fake, convo())
        self.assertEqual((s.profile["age"], s.profile["gender"]), (36, "male"))
        self.assertIn("NEXT SLOT: employment_type", sys_text(fake.systems[-1]))


class TestEnding(Base):
    def test_cut_the_call_is_one_llm_call(self):
        # live bug: "cut the call" -> end_conversation, end_conversation again, then a 3rd call for the words
        end = {"id": "e1", "name": "end_conversation",
               "args": {"outcome": "not_interested", "goodbye": "Sure, cutting the call now. Have a nice day, Rahul!"}}
        fake = FakeLLM(tool_replies=[{"reply": None, "tool_calls": [end, dict(end, id="e2")]}])

        async def convo():
            s = c.new_session("Rahul", "9876543210")
            s.profile = {"age": 36, "gender": "male", "employment_type": "self_employed",
                         "annual_income_inr": 10_000_000, "tobacco": True}
            c._finish_intake(s)
            s.consult_opened = True
            return s, await c.handle_turn(s, "cut the call")

        s, r = self.run_with(fake, convo())
        self.assertTrue(r["ended"])
        self.assertEqual(r["reply"], "Sure, cutting the call now. Have a nice day, Rahul!")
        self.assertEqual(fake.tool_replies, [])  # no further LLM call after the goodbye
        self.assertEqual(sum(1 for t in fake.tool_msgs), 1)
        self.assertEqual(s.outcome, "not_interested")


class TestPrompt(unittest.TestCase):
    def test_no_raw_rupee_integers_in_prompt(self):
        s = c.new_session("Rahul", "9876543210")
        s.profile = {"age": 36, "gender": "male", "employment_type": "self_employed", "annual_income_inr": 10_000_000,
                     "tobacco": True}
        c._finish_intake(s)
        s.quoted.append({"product_id": "hdfc-c2p-supreme", "sum_assured": 300_000_000, "range": [860_500, 1_344_500]})
        dyn = c.build_system(s, Phase.CONSULT, c.snippet("OUTPUT_CONSULT"), "i need 30Cr coverage")[1]["text"]
        self.assertIn('"max_cover": "₹20 crore"', dyn)            # 20x at 36 on 1 crore income
        self.assertIn("Code read the amount in the customer's latest message as ₹30 crore", dyn)
        self.assertIn("₹30 crore cover -> ₹8.61 lakh – ₹13.45 lakh a year", dyn)
        snap_and_turn = dyn.split("## PROCESS KNOWLEDGE")[0]
        self.assertNotRegex(snap_and_turn, r"\b\d{6,}\b")         # no 6+ digit raw amounts anywhere
    def test_placeholders_and_cache_split(self):
        s = c.new_session("Rahul", "9876543210")
        s.profile = {"age": 30, "gender": "male", "employment_type": "salaried", "annual_income_inr": 1_200_000,
                     "tobacco": False}
        c._finish_intake(s)
        for phase, out in [(Phase.GREET, c.snippet("OUTPUT_SIMPLE")), (Phase.CONSULT, c.snippet("OUTPUT_CONSULT"))]:
            blocks = c.build_system(s, phase, out, "claim kaise milega? tomorrow 5 pm")
            text = blocks[0]["text"] + blocks[1]["text"]
            self.assertEqual(set(re.findall(r"\{(\w+)\}", text)), set(), phase)
            self.assertTrue(blocks[0]["cache"])
            self.assertIn("PRODUCT CARDS", blocks[0]["text"])
            self.assertNotIn("NOW (IST)", blocks[0]["text"])  # per-turn time stays out of the cached block
        self.assertIn("SNAPSHOT", blocks[1]["text"])
        self.assertIn("paid_pct_by_amount", blocks[1]["text"])

    def test_time_parser_kept(self):
        from datetime import datetime
        from app.agent.state import IST
        now = datetime(2026, 9, 25, 23, 32, tzinfo=IST)
        self.assertEqual(c.parse_time_text("kal shaam 5 baje", now).hour, 17)
        self.assertEqual(c.parse_time_text("Saturday 11 am", now).day, 26)


if __name__ == "__main__":
    unittest.main()
