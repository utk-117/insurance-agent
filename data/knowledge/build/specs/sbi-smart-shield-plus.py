SOURCE = "SBI_Life_-_Smart_Shield_Plus_Brochure_eng.pdf"

CARD = {
    "id": "sbi-smart-shield-plus",
    "name": "SBI Life - Smart Shield Plus",
    "insurer": "SBI Life",
    "uin": "111N150V01",
    "plan_type": "term",
    "product_class": "Individual, Non-Linked, Non-Participating, Life Insurance, Pure Risk Product",
    "goals": ["pure_protection"],
    "pitch_line": "Pure term cover at a low cost, with cover that can stay level, grow 5% a year, or step up at marriage, child birth or home purchase.",
    "key_benefits": [
        "3 plan options: Level Cover, Increasing Cover (+5% of SA a year, up to 200%), Level Cover with Future Proofing",
        "Cover till age 79, or whole life till 100 (Limited Pay)",
        "Optional Better Half Benefit: spouse gets their own cover if the policyholder dies",
        "Nominee can take the death benefit as lump sum, instalments or both",
        "Lower rates for higher sum assured and for women",
    ],
    "plan_options": ["level_cover", "increasing_cover", "level_cover_future_proofing"],
    "premium_payment_options": ["single", "regular", "limited_10", "limited_15", "limited_20", "limited_25"],
    "premium_frequency": ["single", "yearly", "half_yearly", "monthly"],
    "cover_up_to_age": 100,
    "min_sum_assured_inr": 2500000,
    "riders": ["SBI Life - Accident Benefit Rider (ADB / APPD)"],
    "ideal_for": "Earning members with dependants who want maximum cover per rupee; young families expecting their responsibilities to grow.",
    "not_for": "Anyone who wants money back on survival - there is no maturity benefit.",
    "available_online": True,
    "source_file": SOURCE,
}

_B = dict(product_id=CARD["id"], entry_age_min=18, maturity_age_min=None, min_sum_assured_inr=2500000,
          max_sum_assured_inr=None, channel="all", source_page=21)
_LI = ["level_cover", "increasing_cover"]
ELIGIBILITY = [
    {**_B, "plan_option": _LI, "pay_type": "single", "ppt": 1, "entry_age_max": 65,
     "policy_term_min": 5, "policy_term_max": None, "maturity_age_max": 79, "min_annual_premium_inr": 12000,
     "notes": "Minimum policy term is 10 years for Increasing Cover."},
    {**_B, "plan_option": _LI, "pay_type": "regular", "ppt": "=policy_term", "entry_age_max": 60,
     "policy_term_min": 5, "policy_term_max": None, "maturity_age_max": 79, "min_annual_premium_inr": 2500,
     "notes": "Minimum policy term is 10 years for Increasing Cover."},
    *[{**_B, "plan_option": _LI, "pay_type": "limited", "ppt": ppt, "entry_age_max": 65,
       "policy_term_min": ptmin, "policy_term_max": None, "maturity_age_max": 79, "min_annual_premium_inr": 2500}
      for ppt, ptmin in [(10, 15), (15, 20), (20, 25), (25, 30)]],
    *[{**_B, "plan_option": _LI, "pay_type": "limited", "ppt": ppt, "entry_age_min": 45, "entry_age_max": 65,
       "policy_term_min": "whole_life", "policy_term_max": "whole_life", "maturity_age_max": 100,
       "min_annual_premium_inr": 2500, "notes": "Whole Life: policy term = 100 less age at entry."}
      for ppt in [10, 15, 20, 25]],
    {**_B, "plan_option": ["level_cover_future_proofing"], "pay_type": "regular", "ppt": "=policy_term",
     "entry_age_max": 40, "policy_term_min": 5, "policy_term_max": None, "maturity_age_max": 79,
     "min_annual_premium_inr": 2500, "notes": "Future Proofing is Regular Pay only."},
]

SPANS = {
    "key_features": [("Key Features", "Easy Steps to secure yourself")],
    "plan_options": [("The Product offers Three Plan options", "Beneﬁts in Details")],
    "death_benefit": [("Beneﬁts in Details", "Optional Benefits Available Under the Product")],
    "optional_benefits": [("Optional Benefits Available Under the Product", "Other Beneﬁts")],
    "maturity_benefit": [("Maturity Benefit\nThis plan provides no maturity benefit.", "Lapse\nSingle Pay")],
    "surrender_and_paid_up": [("Lapse\nSingle Pay", "Illustra ons")],
    "grace_period": [("• Grace Period", "• Revival Facility")],
    "revival": [("• Revival Facility", "• Policy Loan")],
    "loan": [("• Policy Loan", "• Nomination & Assignment")],
    "free_look": [("• Free Look Period", "• Tax Benefits")],
    "tax": [("• Tax Benefits", "• Staff Discount")],
    "suicide_exclusion": [("• Suicide Claim provision", "Enhanced Protection with SBI Life")],
    "riders": [("Enhanced Protection with SBI Life", "Grievance Redressal")],
    "non_disclosure_sec45": [("Non-Disclosure", "Note: This document does not purport")],
    "other_exclusions": [("Exclusions for this option:", "Other Beneﬁts")],
}
NOTES = {
    "claims": "Brochure does not describe the claim process. Offer an advisor callback.",
    "other_exclusions": "Only Better Half Benefit exclusions are listed; rider exclusions are in the rider brochure.",
}
