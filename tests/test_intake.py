"""M2b: intake parsing + profile_snapshot()."""
import os
os.environ["SHEET_ID"] = ""  # tests never write to the real Google Sheet (load_dotenv won't override)
import unittest

from app.agent import intake, knowledge


class TestParsing(unittest.TestCase):
    def test_income(self):
        cases = {"80k per month": 960_000, "80 hazaar mahina": 960_000, "12-15 lakh": 1_350_000,
                 "18 LPA": 1_800_000, "₹9,60,000 a year": 960_000, "1.2 crore": 12_000_000,
                 "around 18 lakh a year": 1_800_000, "50 thousand monthly": 600_000, "12 se 15 lakh": 1_350_000}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(intake.parse_income(text, True), want)
        self.assertEqual(intake.parse_income("18", True), 1_800_000)   # bare number when income was asked
        self.assertIsNone(intake.parse_income("I'm 32", False))

    def test_employment(self):
        for text, want in {"housewife": "not_working", "I'm a homemaker": "not_working", "student": "not_working",
                           "retired now": "not_working", "salaried, IT company": "salaried",
                           "naukri karta hoon": "salaried", "apna business hai": "self_employed",
                           "I'm self-employed": "self_employed", "freelancer": "self_employed"}.items():
            with self.subTest(text=text):
                self.assertEqual(intake.parse_employment(text, True), want)

    def test_age_gender_tobacco(self):
        self.assertEqual(intake.parse_age("I'm 32", False), 32)
        self.assertEqual(intake.parse_age("meri umar 38 saal hai", False), 38)
        self.assertEqual(intake.parse_age("34", True), 34)
        self.assertIsNone(intake.parse_age("12-15 lakh", False))
        self.assertIsNone(intake.parse_gender("haan ji, bol rahi hoon", False))   # a hint, not an answer
        self.assertEqual(intake.gender_hint("haan ji, bol rahi hoon"), "female")
        self.assertEqual(intake.gender_hint("main naukri karta hoon"), "male")
        self.assertEqual(intake.gender_hint("I'm a housewife"), "female")
        self.assertEqual(intake.parse_gender("female", True), "female")
        self.assertEqual(intake.parse_gender("main mahila hoon", True), "female")
        self.assertIsNone(intake.clean_llm_value("gender", "male"))  # the model's guess never fills the slot
        self.assertFalse(intake.parse_tobacco("no, never", True))
        self.assertFalse(intake.parse_tobacco("nahi", True))
        self.assertFalse(intake.parse_tobacco("I'm a non-smoker", False))
        self.assertTrue(intake.parse_tobacco("haan kabhi kabhi", True))
        self.assertTrue(intake.parse_tobacco("I smoke sometimes", False))
        self.assertIsNone(intake.parse_tobacco("what do you mean?", False))

    def test_several_at_once_then_only_gender(self):
        p = {s: None for s in intake.SLOTS}
        got = intake.parse_turn("32, salaried, 18 lakh a year, non-smoker", p)
        self.assertEqual(got, {"age": 32, "employment_type": "salaried", "annual_income_inr": 1_800_000,
                               "tobacco": False})
        p.update(got)
        self.assertEqual(intake.missing(p), ["gender"])

    def test_not_working_skips_income(self):
        p = {"age": 28, "gender": "female", "employment_type": None, "annual_income_inr": None, "tobacco": None}
        got = intake.parse_turn("I'm a housewife", p)
        self.assertEqual(got, {"employment_type": "not_working"})
        p.update(got)
        self.assertEqual(intake.missing(p), ["tobacco"])

    def test_order(self):
        p = {s: None for s in intake.SLOTS}
        self.assertEqual(intake.next_slot(p), "age")
        p.update(age=30)
        self.assertEqual(intake.next_slot(p), "gender")

    def test_clean_llm_values(self):
        self.assertEqual(intake.clean_llm_value("annual_income_inr", 960000), 960000)
        self.assertEqual(intake.clean_llm_value("annual_income_inr", "80k per month"), 960000)
        self.assertEqual(intake.clean_llm_value("employment_type", "Self-employed"), "self_employed")
        self.assertIsNone(intake.clean_llm_value("age", 140))
        self.assertIs(intake.clean_llm_value("tobacco", False), False)


class TestSnapshot(unittest.TestCase):
    def test_30_male_salaried_12l(self):
        s = knowledge.profile_snapshot({"age": 30, "gender": "male", "employment_type": "salaried",
                                        "annual_income_inr": 1_200_000, "tobacco": False})
        self.assertEqual(s["max_cover"], 30_000_000)
        term = [e for e in s["eligible"] if "quotes" in e]
        self.assertEqual(len(term), 4)
        for e in term:
            self.assertEqual([q["sum_assured"] for q in e["quotes"]], [10_000_000, 30_000_000], e["product_id"])
            for q in e["quotes"]:
                lo, hi = q["annual_premium_range"]
                self.assertLess(lo, hi)
        self.assertIn("icici-assured-savings", [x["product_id"] for x in s["excluded"]])
        iprotect = next(e for e in term if e["product_id"] == "icici-iprotect-smart-plus")
        self.assertEqual(iprotect["quotes"][0]["salaried_first_year_discount"], 0.125)

    def test_42_female_self_employed_tobacco(self):
        s = knowledge.profile_snapshot({"age": 42, "gender": "female", "employment_type": "self_employed",
                                        "annual_income_inr": 2_500_000, "tobacco": True})
        self.assertEqual(s["max_cover"], 50_000_000)  # 20x above 35
        smoker = next(e for e in s["eligible"] if e["product_id"] == "sbi-smart-shield-plus")["quotes"][0]
        s2 = knowledge.profile_snapshot({"age": 42, "gender": "female", "employment_type": "self_employed",
                                         "annual_income_inr": 2_500_000, "tobacco": False})
        non = next(e for e in s2["eligible"] if e["product_id"] == "sbi-smart-shield-plus")["quotes"][0]
        self.assertGreater(smoker["annual_premium_range"][0], non["annual_premium_range"][0])

    def test_not_working(self):
        s = knowledge.profile_snapshot({"age": 28, "gender": "female", "employment_type": "not_working",
                                        "annual_income_inr": None, "tobacco": False})
        self.assertIsNone(s["max_cover"])
        self.assertFalse([e for e in s["eligible"] if "quotes" in e])
        self.assertTrue(s["not_working_options"])

    def test_age_outside_every_product(self):
        s = knowledge.profile_snapshot({"age": 88, "gender": "male", "employment_type": "salaried",
                                        "annual_income_inr": 500_000, "tobacco": False})
        self.assertEqual(s["eligible"], [])


if __name__ == "__main__":
    unittest.main()
