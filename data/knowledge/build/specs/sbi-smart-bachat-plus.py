SOURCE = "SBI_Life_-_Smart_Bachat_Plus_Brochure_eng.pdf"

CARD = {
    "id": "sbi-smart-bachat-plus",
    "name": "SBI Life - Smart Bachat Plus",
    "insurer": "SBI Life",
    "uin": "111N170V01",
    "plan_type": "endowment_participating",
    "product_class": "Individual, Non-Linked, Participating, Life Insurance, Savings Product",
    "goals": ["savings_protection"],
    "pitch_line": "Traditional savings plan: life cover plus a lump sum at maturity (sum assured + bonuses, if declared), with an option for extra accident cover.",
    "key_benefits": [
        "Maturity: Sum Assured + vested reversionary bonuses + terminal bonus (if declared), as a lump sum",
        "Two options: Life, or Life Plus (adds accidental death cover and accidental total permanent disability cover)",
        "Life Plus: on accidental total permanent disability, Sum Assured paid and future premiums waived",
        "Pay regularly, or for 7, 10 or 15 years",
        "Participating plan: bonuses are not guaranteed and depend on company performance",
    ],
    "plan_options": ["life", "life_plus"],
    "premium_payment_options": ["regular", "limited_7", "limited_10", "limited_15"],
    "premium_frequency": ["yearly", "half_yearly", "monthly"],
    "cover_up_to_age": 65,
    "min_sum_assured_inr": 200000,
    "riders": [],
    "ideal_for": "Conservative savers building a lump sum for a goal 15-30 years away (child's marriage, retirement corpus) who also want life cover.",
    "not_for": "People wanting guaranteed returns (bonuses are not guaranteed) or high cover per rupee.",
    "available_online": True,
    "source_file": SOURCE,
}

_B = dict(product_id=CARD["id"], entry_age_max=50, maturity_age_min=None, maturity_age_max=65,
          min_sum_assured_inr=200000, max_sum_assured_inr=None, channel="all", source_page=10)
ELIGIBILITY = []
for opt, amin in [("life", 3), ("life_plus", 18)]:
    note = {"notes": "Minor life assured: parent or legal guardian is the proposer."} if amin < 18 else {}
    ELIGIBILITY += [
        {**_B, **note, "plan_option": [opt], "entry_age_min": amin, "pay_type": "regular", "ppt": "=policy_term",
         "policy_term_min": 15, "policy_term_max": 30, "min_annual_premium_inr": 12000},
        {**_B, **note, "plan_option": [opt], "entry_age_min": amin, "pay_type": "limited", "ppt": 7,
         "policy_term_min": 15, "policy_term_max": 30, "min_annual_premium_inr": 15000},
        {**_B, **note, "plan_option": [opt], "entry_age_min": amin, "pay_type": "limited", "ppt": 10,
         "policy_term_min": 20, "policy_term_max": 30, "min_annual_premium_inr": 15000},
        {**_B, **note, "plan_option": [opt], "entry_age_min": amin, "pay_type": "limited", "ppt": 15,
         "policy_term_min": 20, "policy_term_max": 30, "min_annual_premium_inr": 15000},
    ]

SPANS = {
    "key_features": [("Key Features", "Beneﬁts\nDeath Beneﬁt")],
    "plan_options": [("• Choose one of the following 2", "• Lumpsum beneﬁt"),
                     ("• Beneﬁt option once chosen", "• If the life assured is minor, date")],
    "death_benefit": [("Death Beneﬁt\ni. If You", "Maturity Beneﬁt\nIf the Policy")],
    "maturity_benefit": [("Maturity Beneﬁt\nIf the Policy", "Let us now analyse")],
    "free_look": [("• Free Look Period", "• Grace Period")],
    "grace_period": [("• Grace Period", "• Tax Beneﬁt")],
    "tax": [("• Tax Beneﬁt", "• Lapse")],
    "surrender_and_paid_up": [("• Lapse", "• Revival")],
    "revival": [("• Revival", "• Policy Loan")],
    "loan": [("• Policy Loan", "• Nomination & Assignment")],
    "suicide_exclusion": [("• Suicide Claim Provisions", "• Exclusions for Accidental")],
    "other_exclusions": [("• Exclusions for Accidental", "Discount\n1) High")],
    "non_disclosure_sec45": [("Non-Disclosure", "Note: This document does not purport")],
}
NOTES = {
    "optional_benefits": "No separate optional benefits; accident cover comes built into the Life Plus option.",
    "riders": "No riders are offered with this plan.",
    "claims": "Brochure does not describe the claim process. Offer an advisor callback.",
    "maturity_benefit": "Bonus figures in the brochure's illustrations (4% / 8%) are not guaranteed. Never quote them.",
}
