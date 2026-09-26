import unittest

from app.normalize import normalize as n, split_for_tts, split_sentences

CASES = [
    ("Cover of ₹5,00,000 is available.", "Cover of 5 lakh rupees is available."),
    ("Minimum cover Rs. 5 lakh.", "Minimum cover 5 lakh rupees."),
    ("Up to ₹2 crore on terminal illness.", "Up to 2 crore rupees on terminal illness."),
    ("Sum assured 1,00,00,000 for this plan.", "Sum assured 1 crore for this plan."),
    ("₹3 lakh paid on claim intimation.", "3 lakh rupees paid on claim intimation."),
    ("₹1,50,00,000 cover", "1.5 crore rupees cover"),
    ("Premium of ₹25,000 is illustrative.", "Premium of 25,000 rupees is illustrative."),
    ("98.06% of claims by amount", "98.06 percent of claims by amount"),
    ("Entry age 18-65 yrs", "Entry age 18 to 65 years"),
    ("Policy term 10–40 years", "Policy term 10 to 40 years"),
    ("Callback on 2026-09-26 at 17:00", "Callback on 26th September at 5 PM"),
    ("Call at 5:00 PM tomorrow", "Call at 5 PM tomorrow"),
    ("Call at 5pm", "Call at 5 PM"),
    ("Call at 11:30 AM", "Call at 11:30 AM"),
    ("As per IRDAI data for FY 2024-25", "As per I R D A I data for financial year 2024-25"),
    ("ULIP, PED, TPA and GST", "U-lip, pre-existing disease, T P A and G S T"),
    ("**Key benefit**: see https://example.com/plan 🙂", "Key benefit: see"),
    ("- first point\n- second point", "first point\nsecond point"),
    ("Date 01/10/2026", "Date 1st October"),
    ("22nd and 3rd", "22nd and 3rd"),
    ("Life & Life Plus", "Life and Life Plus"),
    ("claim within 15 days, 45 days with investigation", "claim within 15 days, 45 days with investigation"),
]


class TestNormalize(unittest.TestCase):
    def test_cases(self):
        self.assertGreaterEqual(len(CASES), 15)
        for raw, want in CASES:
            with self.subTest(raw=raw):
                self.assertEqual(n(raw), want)

    def test_phone_untouched(self):
        self.assertIn("9876543210", n("We'll call you on 9876543210."))

    def test_split(self):
        s = split_sentences("Hi Rahul. This plan covers you up to age 85, with a lump sum for your family. "
                            "Shall I explain the claim process? Or the plan options?")
        self.assertEqual(len(s), 2)  # the two short questions merge
        self.assertTrue(s[0].startswith("Hi Rahul. This plan"))
        long = "word, " * 200
        self.assertTrue(all(len(x) <= 400 for x in split_sentences(long)))
        self.assertEqual(split_sentences("Haan ji। Bilkul theek hai, main advisor ka call book kar deti hoon।"),
                         ["Haan ji। Bilkul theek hai, main advisor ka call book kar deti hoon।"])


class TestSplitForTTS(unittest.TestCase):
    def test_short_first_chunk(self):
        c = split_for_tts("Got it. For 30 crore cover, the indicative yearly premium is roughly 8.6 lakh to 13.45 lakh "
                          "for HDFC. However, 30 crore is above your limit. Shall I set up an advisor call?")
        self.assertEqual(c[0], "Got it. For 30 crore cover,")  # "Got it." is too short alone; cut at the clause
        self.assertLessEqual(len(c[0]), 70)
        self.assertEqual(" ".join(c).replace("  ", " "), "Got it. For 30 crore cover, the indicative yearly premium is "
                         "roughly 8.6 lakh to 13.45 lakh for HDFC. However, 30 crore is above your limit. Shall I set "
                         "up an advisor call?")

    def test_short_reply_is_one_chunk(self):
        self.assertEqual(split_for_tts("Sure, cutting the call now. Have a nice day, Rahul!"),
                         ["Sure, cutting the call now.", "Have a nice day, Rahul!"])
        self.assertEqual(split_for_tts(""), [])


if __name__ == "__main__":
    unittest.main()
