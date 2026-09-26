"""M1: eligibility / shortlist / router / section loading.  python -m unittest discover -s tests -v"""
import os
os.environ["SHEET_ID"] = ""  # tests never write to the real Google Sheet (load_dotenv won't override)
import subprocess
import sys
import unittest

from app.agent import knowledge as k

TERM = {"sbi-smart-shield-plus", "sbi-smart-swadhan-supreme", "icici-iprotect-smart-plus", "hdfc-c2p-supreme"}
SAVINGS = {"sbi-smart-platina-plus", "sbi-smart-bachat-plus", "icici-gift-pro", "icici-assured-savings",
           "hdfc-sanchay-plus", "hdfc-sanchay-par-advantage"}


class TestEligibility(unittest.TestCase):
    def ranked(self, **profile):
        return set(k.rank_products(profile))

    def test_age_17_savings_only(self):
        got = self.ranked(age=17, income_band="25L+")
        self.assertTrue(got, "some savings plans allow 17")
        self.assertTrue(got <= SAVINGS, got - SAVINGS)
        self.assertEqual(self.ranked(age=17, goal="pure protection"), set())

    def test_age_35_everything_eligible(self):
        self.assertEqual(self.ranked(age=35, income_band="25L+"), TERM | SAVINGS)
        self.assertEqual(self.ranked(age=35, goal="pure protection"), TERM)

    def test_age_62(self):
        self.assertEqual(self.ranked(age=62, goal="pure protection"),
                         {"sbi-smart-shield-plus", "icici-iprotect-smart-plus", "hdfc-c2p-supreme"})
        self.assertEqual(self.ranked(age=62, goal="savings + protection"),
                         {"hdfc-sanchay-plus", "hdfc-sanchay-par-advantage"})

    def test_age_70_only_c2p(self):
        self.assertEqual(k.shortlist({"age": 70}), ["hdfc-c2p-supreme"])
        self.assertEqual(k.shortlist({"age": 70, "goal": "retirement"}), [])

    def test_out_of_range_and_unknown_age(self):
        self.assertEqual(k.shortlist({"age": 90}), [])
        self.assertEqual(k.shortlist({"age": None, "goal": "pure protection"}), [])


class TestShortlist(unittest.TestCase):
    def test_gates_moved_to_underwriting_rules(self):
        # v2: gates live in underwriting_rules.json and are applied by profile_snapshot(), not by need_fit
        self.assertNotIn("gate", k.need_fit()["products"]["icici-assured-savings"])
        self.assertIn("icici-assured-savings", k.underwriting_rules()["gates"])

    def test_need_ranking(self):
        top = k.shortlist({"age": 35, "goal": "retirement", "primary_need": "guaranteed_second_income"})
        for pid in top:
            self.assertTrue(k.need_fit()["products"][pid].get("guaranteed_second_income"), pid)

    def test_one_per_insurer(self):
        sl = k.shortlist({"age": 35, "goal": "pure protection", "primary_need": "premium_back"})
        self.assertEqual(len(sl), 3)
        self.assertEqual(len({k.cards()[p]["insurer"] for p in sl}), 3)

    def test_preferred_insurer_allows_repeats_and_goes_first(self):
        sl = k.shortlist({"age": 35, "goal": "savings + protection", "preferred_insurer": "HDFC",
                          "income_band": "25L+"})
        self.assertEqual({k.cards()[p]["insurer"] for p in sl[:2]}, {"HDFC Life"})


ROUTER_CASES = [
    ("claim kaise milega?", "claims"),
    ("surrender kar sakte hain?", "surrender_and_paid_up"),
    ("What is the free look period?", "free_look"),
    ("pasand nahi aaya toh wapas kar sakte hain?", "free_look"),
    ("grace period kitna hai", "grace_period"),
    ("premium bhool gaya toh kya hoga", "grace_period"),
    ("is suicide covered?", "suicide_exclusion"),
    ("can I take a loan against the policy", "loan"),
    ("tax benefit milega 80C mein?", "tax"),
    ("agar mujhe kuch ho gaya toh family ko kitna milega", "death_benefit"),
    ("maturity pe kya milega", "maturity_benefit"),
    ("policy lapse ho gayi toh chalu kar sakte hain", "revival"),
    ("kya accident rider hai", "riders"),
    ("wife ko bhi cover mil sakta hai?", "optional_benefits"),
    ("agar maine smoking chhupa li toh", "non_disclosure_sec45"),
    ("what is not covered, any exclusions?", "other_exclusions"),
]


class TestRouter(unittest.TestCase):
    def test_phrases(self):
        for phrase, topic in ROUTER_CASES:
            with self.subTest(phrase=phrase):
                self.assertIn(topic, k.match_topics(phrase))

    def test_short_keywords_need_word_boundary(self):
        self.assertEqual(k.match_topics("I am aware this is my existing syntax"), [])
        self.assertIn("other_exclusions", k.match_topics("is war covered?"))

    def test_product_aliases_and_insurer_names(self):
        self.assertEqual(k.match_products("tell me about click 2 protect"), ["hdfc-c2p-supreme"])
        self.assertEqual(k.match_products("swadhan mein paisa wapas milta hai?"), ["sbi-smart-swadhan-supreme"])
        sl = ["hdfc-c2p-supreme", "icici-iprotect-smart-plus", "sbi-smart-shield-plus"]
        self.assertEqual(k.match_products("Which is better, the HDFC one or the ICICI one?", sl),
                         ["hdfc-c2p-supreme", "icici-iprotect-smart-plus"])

    def test_route_max_products_and_topics(self):
        r = k.route_topics("compare iprotect, click 2 protect and smart shield",
                           {"selected_product": "sbi-smart-bachat-plus"})
        self.assertEqual(len(r["products"]), 2)
        self.assertEqual(list(r["products"])[0], "sbi-smart-bachat-plus")
        for topics in r["products"].values():
            self.assertLessEqual(len(topics), 4)

    def test_claims_fallback_to_insurer_notes(self):
        r = k.route_topics("claim kaise milega?", {"selected_product": "sbi-smart-shield-plus"})
        self.assertNotIn("claims", r["products"]["sbi-smart-shield-plus"])
        self.assertEqual(r["claims_fallback"], ["sbi-life"])
        notes = k.insurer_notes("sbi-life", "Death claims")
        self.assertIn("Death claims", notes)
        self.assertNotIn("Medical tests", notes)

    def test_claims_section_used_when_available(self):
        r = k.route_topics("claim kaise milega?", {"selected_product": "hdfc-c2p-supreme"})
        self.assertIn("claims", r["products"]["hdfc-c2p-supreme"])
        self.assertEqual(r["claims_fallback"], [])

    def test_surrender_loaded_first(self):
        r = k.route_topics("surrender kar sakte hain?", {"selected_product": "hdfc-sanchay-plus"})
        self.assertEqual(r["products"]["hdfc-sanchay-plus"][0], "surrender_and_paid_up")

    def test_core_fill_skips_unavailable_and_answered(self):
        r = k.route_topics("hello", {"selected_product": "icici-assured-savings"})
        self.assertNotIn("plan_options", r["products"]["icici-assured-savings"])  # unavailable
        r = k.route_topics("hello", {"selected_product": "hdfc-c2p-supreme",
                                     "answered_topics": {"hdfc-c2p-supreme": ["key_features"]}})
        self.assertNotIn("key_features", r["products"]["hdfc-c2p-supreme"])

    def test_no_product_no_sections(self):
        r = k.route_topics("what's the claim process?", {})
        self.assertEqual(r["products"], {})
        self.assertEqual(r["matched_topics"], ["claims"])


class TestLoaders(unittest.TestCase):
    def test_get_sections(self):
        secs = k.get_sections("hdfc-c2p-supreme", ["free_look", "nope"])
        self.assertTrue(secs[0]["available"] and secs[0]["text"] and secs[0]["pages"])
        self.assertFalse(secs[1]["available"])

    def test_claims_record(self):
        rows = k.claims_record(["HDFC", "icici-iprotect-smart-plus", "sbi-life"])
        self.assertEqual({r["insurer"] for r in rows}, {"HDFC Life", "ICICI Prudential Life", "SBI Life"})
        for r in rows:
            self.assertTrue(r["fy"] and r["paid_pct_by_amount"] and r["paid_pct_by_number"])

    def test_prompt_cards_drop_fields(self):
        c = k.prompt_cards()
        self.assertEqual(len(c), 10)
        self.assertFalse(any(f in c[0] for f in ("topics_available", "source_file", "uin")))

    def test_need_fit_for_hides_gates(self):
        nf = k.need_fit_for(["icici-assured-savings"])
        self.assertNotIn("gate", nf["products"]["icici-assured-savings"])
        self.assertIn("lump_sum_goal", nf["needs"])

    def test_integrity_check_passes(self):
        r = subprocess.run([sys.executable, "data/knowledge/check_integrity.py"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
