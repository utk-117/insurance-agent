SOURCE = "ICICI_Pru_GIFT_Pro_Brochure.pdf"

CARD = {
    "id": "icici-gift-pro",
    "name": "ICICI Pru GIFT Pro",
    "insurer": "ICICI Prudential Life",
    "uin": "105N201V07",
    "plan_type": "guaranteed_income",
    "product_class": "Non-linked, Non-participating, Individual, Savings Life Insurance plan",
    "goals": ["savings_protection"],
    "pitch_line": "Pay for 5-12 years and get a guaranteed income for 5-30 years (level or rising 5% a year), with an optional lump sum of up to 200% of premiums, plus life cover.",
    "key_benefits": [
        "Guaranteed Income after the policy term, for an income period of 5, 7, 10, 12, 15, 20, 25 or 30 years",
        "Choose level income or income rising 5% a year (simple)",
        "MoneyBack lump sum: pick 0%-200% of total annual premiums and the year you receive it",
        "Low Cover Income Booster: take lower life cover for higher income",
        "Income continues to the family if the life assured dies during the income period",
        "Higher income rates for larger annual premiums",
    ],
    "plan_options": ["level_guaranteed_income", "increasing_guaranteed_income"],
    "premium_payment_options": ["limited_5", "limited_6", "limited_7", "limited_8", "limited_9",
                                "limited_10", "limited_11", "limited_12"],
    "premium_frequency": ["yearly", "half_yearly", "monthly"],
    "cover_up_to_age": 75,
    "min_sum_assured_inr": 250000,
    "riders": [],
    "ideal_for": "Savers planning a guaranteed second income or known future expenses (children's education, retirement top-up) with flexibility on when the lump sum arrives.",
    "not_for": "Pure protection seekers; life cover is only about 11x the annual premium (lower with Income Booster).",
    "available_online": True,
    "source_file": SOURCE,
}

_INCOME = [5, 7, 10, 12, 15, 20, 25, 30]
_MAXMAT = {5: 70, 6: 71, 7: 72, 8: 73, 9: 74, 10: 75, 11: 75, 12: 75}
ELIGIBILITY = [
    {"product_id": CARD["id"], "plan_option": CARD["plan_options"], "pay_type": "limited", "ppt": ppt,
     "policy_term_min": ppt, "policy_term_max": ppt + 5, "income_period": _INCOME,
     "entry_age_min": "18-policy_term", "entry_age_min_note": "Minimum entry age is 18 minus the policy term (minors allowed); minimum age at maturity is 18.",
     "entry_age_max": 60, "maturity_age_min": 18, "maturity_age_max": _MAXMAT[ppt],
     "min_sum_assured_inr": 500000 if ppt <= 6 else 250000, "max_sum_assured_inr": None,
     "min_annual_premium_inr": 100000 if ppt <= 6 else 50000, "channel": "all", "source_page": 4}
    for ppt in range(5, 13)
] + [
    {"product_id": CARD["id"], "plan_option": CARD["plan_options"], "pay_type": "limited", "ppt": ppt,
     "policy_term_min": ppt, "policy_term_max": ppt + 5, "income_period": _INCOME,
     "entry_age_min": "18-policy_term", "entry_age_max": "65-policy_term", "maturity_age_min": 18,
     "maturity_age_max": 65, "min_sum_assured_inr": 500000 if ppt <= 6 else 250000,
     "max_sum_assured_inr": 2500000, "min_annual_premium_inr": 100000 if ppt <= 6 else 50000,
     "channel": "pos", "source_page": 5, "notes": "POS variant: no medical examination; max sum assured on death ₹25 lakh."}
    for ppt in range(5, 13)
]

SPANS = {
    "key_features": [("Salient features that make", "BUY\nONLINE")],
    "plan_options": [("1.\nFlexibility to choose Guaranteed Income option", "Death Beneﬁt\nIn the event")],
    "maturity_benefit": [("You pay premiums for a certain period", "1.\nFlexibility to choose Guaranteed Income option")],
    "death_benefit": [("Death Beneﬁt\nIn the event", "Let us take few examples")],
    "optional_benefits": [("Additional beneﬁts\nHigher Premium Beneﬁt", "Non-Payment of Premiums:"),
                          ("Save the Date: You have", "9.\nAdvance Premium")],
    "surrender_and_paid_up": [("Non-Payment of Premiums:", "Policy Revival\nYou can"),
                              ("Surrender Beneﬁt\nYou can Surrender", "Taking a policy loan")],
    "revival": [("Policy Revival\nYou can", "Surrender Beneﬁt\nYou can Surrender")],
    "loan": [("Taking a policy loan", "Termination of the Policy")],
    "suicide_exclusion": [("Suicide clause:", "2.\nFree look period:")],
    "free_look": [("Free look period:", "3.\nTax Beneﬁts:")],
    "tax": [("Tax Beneﬁts:", "4.\nGrace Period:")],
    "grace_period": [("Grace Period:", "5.\nBeneﬁt Illustrations:")],
    "non_disclosure_sec45": [("17. Section 45", "18. For further details")],
}
NOTES = {
    "riders": "No riders are mentioned in the brochure.",
    "claims": "Brochure does not describe the claim process. Offer an advisor callback.",
    "other_exclusions": "Brochure lists no exclusions other than the suicide clause.",
    "maturity_benefit": "Income amounts in the brochure illustrations depend on age, premium and options. Never quote them.",
}
