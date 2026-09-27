SOURCE = "SBI_Life_-_Smart_Platina_Plus_Brochure_eng.pdf"

CARD = {
    "id": "sbi-smart-platina-plus",
    "name": "SBI Life - Smart Platina Plus",
    "insurer": "SBI Life",
    "uin": "111N133V06",
    "plan_type": "guaranteed_income",
    "product_class": "Individual, Non-Linked, Non-Participating Life Insurance Savings Product",
    "goals": ["savings_protection"],
    "pitch_line": "Pay for 7, 8 or 10 years, then get a fixed guaranteed income for 15-30 years, plus 110% of your premiums back at the end, with life cover throughout.",
    "key_benefits": [
        "Guaranteed regular income during the payout period (yearly, half-yearly, quarterly or monthly)",
        "Maturity: 110% of total premiums paid",
        "Two income options: Life Income or Guaranteed Income (income continues to nominee after death)",
        "Life cover for the whole policy term",
        "Can be bought for a child from 30 days of age, with a parent as proposer",
    ],
    "plan_options": ["life_income", "guaranteed_income"],
    "premium_payment_options": ["limited_7", "limited_8", "limited_10"],
    "premium_frequency": ["yearly", "half_yearly", "monthly"],
    "cover_up_to_age": 99,
    "min_sum_assured_inr": 550000,
    "riders": ["SBI Life - Accident Benefit Rider (ADB / APPD)"],
    "ideal_for": "Savers who want a predictable second income later (children's education, retirement top-up) without market risk.",
    "not_for": "People who want the largest possible life cover per rupee; the sum assured is only about 11x the annual premium.",
    "available_online": True,
    "source_file": SOURCE,
}

_B = dict(product_id=CARD["id"], plan_option=["life_income", "guaranteed_income"], pay_type="limited",
          entry_age_min=0, entry_age_min_note="30 days; for a minor the proposer is a parent or legal guardian",
          maturity_age_min=None, min_sum_assured_inr=550000, max_sum_assured_inr=None,
          min_annual_premium_inr=50000, source_page=9)
ELIGIBILITY = [
    {**_B, "ppt": 7, "payout_period": [15, 20, 25, 30], "policy_term_values": [23, 28, 33, 38],
     "policy_term_min": 23, "policy_term_max": 38, "entry_age_max": 60, "maturity_age_max": 99, "channel": "all"},
    {**_B, "ppt": 8, "payout_period": [15, 20, 25, 30], "policy_term_values": [24, 29, 34, 39],
     "policy_term_min": 24, "policy_term_max": 39, "entry_age_max": 60, "maturity_age_max": 99, "channel": "all"},
    {**_B, "ppt": 10, "payout_period": [15, 20, 25], "policy_term_values": [26, 31, 36],
     "policy_term_min": 26, "policy_term_max": 36, "entry_age_max": 60, "maturity_age_max": 99, "channel": "all"},
    {**_B, "ppt": 6, "payout_period": [13], "policy_term_values": [20], "policy_term_min": 20,
     "policy_term_max": 20, "entry_age_max": 45, "maturity_age_max": 65, "channel": "pos",
     "notes": "POSP / CPSC-SPV channel only; sum assured on death capped at 25 lakh per life; no riders."},
]

SPANS = {
    "key_features": [("Key Features", "How does the plan work?")],
    "plan_options": [("How does the plan work?", "Illustration\n1. For Income Plan")],
    "maturity_benefit": [("Maturity Benefit (For In-force policies)", "Death Benefit (For In-force policies)")],
    "death_benefit": [("Death Benefit (For In-force policies)", "Who can avail this plan?")],
    "loan": [("Policy Loan\nIn emergency", "What Other Benefits do I get?")],
    "free_look": [("Free look Period", "Grace period\nA grace")],
    "grace_period": [("Grace period\nA grace", "Tax Benefit\nYou may")],
    "tax": [("Tax Benefit\nYou may", "Benefits under Paid-up Policies")],
    "surrender_and_paid_up": [("Benefits under Paid-up Policies", "Revival\nIf premiums")],
    "revival": [("Revival\nIf premiums", "Participation in profits")],
    "suicide_exclusion": [("Suicide Claim provisions", "Exclusions, if any")],
    "other_exclusions": [("Exclusions, if any", "Additional Benefit for Staff")],
    "riders": [("Enhanced Protection with SBI Life", "Grievance Redressal")],
    "non_disclosure_sec45": [("Non-Disclosure", "Note: This document does not purport")],
}
NOTES = {
    "optional_benefits": "No optional benefits other than the Accident Benefit Rider; income payout frequency can be changed once, within 9 months of the premium payment term ending.",
    "claims": "Brochure does not describe the claim process. Offer an advisor callback.",
}
