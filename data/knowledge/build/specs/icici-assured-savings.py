SOURCE = "ICICI Pru Assured Savings Insurance Plan.pdf"

CARD = {
    "id": "icici-assured-savings",
    "name": "ICICI Pru Assured Savings Insurance Plan",
    "insurer": "ICICI Prudential Life",
    "uin": "105N144V10",
    "plan_type": "guaranteed_savings",
    "product_class": "Non-Linked Non-Participating Individual Savings Life Insurance Plan",
    "goals": ["savings_protection"],
    "pitch_line": "High-premium guaranteed savings plan: yearly guaranteed additions of 9-11% of premiums paid, plus a guaranteed lump sum at maturity, with life cover throughout.",
    "key_benefits": [
        "Guaranteed Additions every year: 9%, 10% or 11% of total premiums paid, depending on the policy term",
        "Guaranteed Maturity Benefit plus accrued Guaranteed Additions, paid as a lump sum at maturity",
        "Pay for 5, 7, 8, 10 or 12 years; policy term 10 to 20 years",
        "Life cover for the full term (death benefit at least 10x annual premium plus additions)",
        "Minimum annual premium is ₹20 lakh (non-POS)",
    ],
    "plan_options": [],
    "premium_payment_options": ["limited_5", "limited_7", "limited_8", "limited_10", "limited_12"],
    "premium_frequency": ["yearly", "half_yearly", "monthly"],
    "cover_up_to_age": 72,
    "min_sum_assured_inr": None,
    "riders": [],
    "ideal_for": "High-income savers (₹20 lakh+ a year) who want a fully guaranteed lump sum for a goal 10-20 years away.",
    "not_for": "Anyone who cannot commit ₹20 lakh a year, or who mainly needs protection.",
    "available_online": True,
    "purchase_url": None,
    "source_file": SOURCE,
    "data_caveats": ["Brochure is dated FY 2023-24 (Advt L/II/1494/2023-24); interest rates quoted inside are from Dec 2023. Confirm the current version with ICICI before relying on it."],
}

_NON_POS = [(5, 10, 8, 60), (5, 15, 3, 57), (7, 10, 8, 60), (7, 12, 6, 60), (7, 15, 3, 57), (8, 16, 2, 56),
            (8, 20, 0, 52), (10, 12, 6, 60), (10, 15, 3, 57), (10, 20, 0, 52), (12, 20, 0, 52)]
_POS = [(5, 10, 8, 55), (5, 15, 3, 50), (7, 10, 8, 55), (7, 12, 6, 53), (7, 15, 3, 50), (8, 16, 2, 49),
        (8, 20, 0, 45), (10, 12, 6, 53), (10, 15, 3, 50), (10, 20, 0, 45), (12, 20, 0, 45)]
_NOTE = "Sum Assured on death = 10x annualised premium. Minors can be covered; the policy vests in them at 18."
ELIGIBILITY = [
    {"product_id": CARD["id"], "plan_option": None, "pay_type": "limited", "ppt": ppt, "policy_term_min": pt,
     "policy_term_max": pt, "entry_age_min": amin, "entry_age_max": amax, "maturity_age_min": 18,
     "maturity_age_max": 72, "min_sum_assured_inr": None, "max_sum_assured_inr": None,
     "min_annual_premium_inr": 2000000, "channel": "all", "source_page": 4, "notes": _NOTE}
    for ppt, pt, amin, amax in _NON_POS
] + [
    {"product_id": CARD["id"], "plan_option": None, "pay_type": "limited", "ppt": ppt, "policy_term_min": pt,
     "policy_term_max": pt, "entry_age_min": amin, "entry_age_max": amax, "maturity_age_min": 18,
     "maturity_age_max": 65, "min_sum_assured_inr": None, "max_sum_assured_inr": None,
     "min_annual_premium_inr": 250000, "max_annual_premium_inr": 250000, "channel": "pos", "source_page": 4,
     "notes": "POS channel: annual premium fixed at ₹2.5 lakh; no medical examination. " + _NOTE}
    for ppt, pt, amin, amax in _POS
]

SPANS = {
    "key_features": [("Key benefits", "BUY\nONLINE")],
    "maturity_benefit": [("Maturity benefit\nOn survival", "Calculation of Guaranteed Additions:"),
                         ("Guaranteed Maturity Benefit\nYour GMB", "Annual Premium per")],
    "death_benefit": [("Death benefit\nOn death", "Surrender benefit\nYour policy")],
    "surrender_and_paid_up": [("Surrender benefit\nYour policy", "Revival of the policy")],
    "revival": [("Revival of the policy", "Beneﬁt Illustration for")],
    "loan": [("Taking a Policy Loan", "Terms & Conditions")],
    "suicide_exclusion": [("1. Suicide clause:", "2. Free look period:")],
    "free_look": [("2. Free look period:", "3. Tax benefits:")],
    "tax": [("3. Tax benefits:", "4. Grace Period:")],
    "grace_period": [("4. Grace Period:", "5. Premium, premium payment term")],
    "non_disclosure_sec45": [("12. Section 45", "13. POS Policies")],
}
NOTES = {
    "plan_options": "Single plan; the customer chooses the premium payment term and policy term. These cannot be changed later.",
    "optional_benefits": "No optional benefits in the brochure.",
    "riders": "No riders are mentioned in the brochure.",
    "claims": "Brochure does not describe the claim process. Offer an advisor callback.",
    "other_exclusions": "Brochure lists no exclusions other than the suicide clause.",
    "maturity_benefit": "The brochure's premium-per-₹1000-GMB rate table has been left out on purpose; never quote maturity amounts.",
}
