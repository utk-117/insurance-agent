SOURCE = "SBI_Life_-_Smart_Swadhan_Supreme__brochure__eng.pdf"

CARD = {
    "id": "sbi-smart-swadhan-supreme",
    "name": "SBI Life - Smart Swadhan Supreme",
    "insurer": "SBI Life",
    "uin": "111N140V02",
    "plan_type": "term_return_of_premium",
    "product_class": "Individual, Non-Linked, Non-Participating, Life Insurance Savings product with Return of Premium",
    "goals": ["pure_protection", "savings_protection"],
    "pitch_line": "Term life cover that gives back 100% of the premiums you paid if you survive the policy term.",
    "key_benefits": [
        "Death: higher of Basic Sum Assured, 11x annualised premium, or 105% of premiums paid",
        "Maturity: 100% of total premiums paid returned in a lump sum",
        "Pay regularly, or only for 7, 10 or 15 years",
        "Policy term 10 to 30 years",
    ],
    "plan_options": [],
    "premium_payment_options": ["regular", "limited_7", "limited_10", "limited_15"],
    "premium_frequency": ["yearly", "half_yearly", "monthly"],
    "cover_up_to_age": 75,
    "min_sum_assured_inr": 2500000,
    "riders": ["SBI Life - Accident Benefit Rider (ADB / APPD)"],
    "ideal_for": "Someone who wants a family safety net but dislikes 'losing' premiums on a pure term plan.",
    "not_for": "People looking for investment growth or income; maturity only returns premiums, no returns on top.",
    "available_online": True,
    "purchase_url": None,
    "source_file": SOURCE,
}

_BASE = dict(product_id=CARD["id"], plan_option=None, entry_age_min=18, entry_age_max=60,
             maturity_age_min=None, maturity_age_max=75, min_sum_assured_inr=2500000,
             max_sum_assured_inr=None, min_annual_premium_inr=6000, channel="all", source_page=7)
ELIGIBILITY = [
    {**_BASE, "pay_type": "limited", "ppt": 7, "policy_term_min": 15, "policy_term_max": 30},
    {**_BASE, "pay_type": "limited", "ppt": 10, "policy_term_min": 15, "policy_term_max": 30},
    {**_BASE, "pay_type": "limited", "ppt": 15, "policy_term_min": 20, "policy_term_max": 30},
    {**_BASE, "pay_type": "regular", "ppt": "=policy_term", "policy_term_min": 10, "policy_term_max": 30},
]

SPANS = {
    "key_features": [("Key Features", "Benefits\nDeath Benefit")],
    "death_benefit": [("Death Benefit (Applicable only", "Maturity Benefit (Applicable only")],
    "maturity_benefit": [("Maturity Benefit (Applicable only", "Illustration I")],
    "riders": [("Rider Benefit", "Grievance Redressal")],
    "free_look": [("Free look Period", "Applicable Tax")],
    "grace_period": [("Grace Period\nA grace period", "Reduced Paid-up Value")],
    "suicide_exclusion": [("Suicide Claim Provision", "Staff Discount")],
    "surrender_and_paid_up": [("Reduced Paid-up Value", "Revival\nIn case"),
                              ("Surrender Benefit", "Rider Benefit")],
    "loan": [("Policy Loans", "Free look Period")],
    "revival": [("Revival\nIn case", "Surrender Benefit")],
    "tax": [("Applicable Tax", "Suicide Claim Provision")],
    "non_disclosure_sec45": [("Non-Disclosure", "Toll free No.")],
}
NOTES = {
    "plan_options": "Single plan; only choice is premium payment term (Regular or Limited 7/10/15).",
    "optional_benefits": "No optional benefits other than the Accident Benefit Rider.",
    "claims": "Brochure does not describe the claim process. Offer an advisor callback.",
    "other_exclusions": "Only the suicide clause is listed in the brochure; rider exclusions are in the rider brochure.",
}
