SOURCE = "ICICI_Pru_iProtect_Smart_Plus_Brochure.pdf"

CARD = {
    "id": "icici-iprotect-smart-plus",
    "name": "ICICI Pru iProtect Smart Plus",
    "insurer": "ICICI Prudential Life",
    "uin": "105N205V07",
    "plan_type": "term",
    "product_class": "Non-Participating, Non-linked, Life, Individual, Pure Risk Premium product",
    "goals": ["pure_protection"],
    "pitch_line": "Term plan with high cover, optional accidental death cover, ₹3 lakh paid within a working day of a claim, and a one-year premium break if money is tight.",
    "key_benefits": [
        "3 variants: Life; Life Plus (adds accidental death cover); Life Rebalancing (higher accident cover in early years)",
        "Cover up to age 85, or whole life to 99 (Life variant)",
        "Terminal illness diagnosis pays the death benefit early",
        "Insta payment: ₹3 lakh advance on claim intimation for covers of ₹1 crore or more (after 3 policy years)",
        "Raise cover at marriage, child birth or home loan (Regular Pay); Premium Break after 5 years",
        "Smart Exit: get total premiums back after 25 years if aged 60+",
    ],
    "plan_options": ["life", "life_plus", "life_rebalancing"],
    "premium_payment_options": ["single", "regular", "limited_5", "limited_7", "limited_10", "limited_15", "limited_to_age_60"],
    "premium_frequency": ["single", "yearly", "half_yearly", "monthly"],
    "cover_up_to_age": 99,
    "min_sum_assured_inr": 5000000,
    "riders": ["ICICI Pru Non-linked Health Protect Rider (critical illness), and other riders as made available"],
    "ideal_for": "Salaried earners with loans or young dependants who want large cover (₹50 lakh+) and flexibility as life changes.",
    "not_for": "Anyone needing cover below ₹50 lakh or wanting a maturity payout.",
    "available_online": True,
    "purchase_url": None,
    "source_file": SOURCE,
}

_B = dict(product_id=CARD["id"], entry_age_min=18, maturity_age_min=None, min_sum_assured_inr=5000000,
          max_sum_assured_inr=None, min_annual_premium_inr=None, channel="all", source_page=12)
_LLP = ["life", "life_plus"]
ELIGIBILITY = [
    # Life and Life Plus
    {**_B, "plan_option": _LLP, "pay_type": "single", "ppt": 1, "policy_term_min": 5, "policy_term_max": 20,
     "entry_age_max": 65, "maturity_age_max": 75},
    {**_B, "plan_option": _LLP, "pay_type": "regular", "ppt": "=policy_term", "policy_term_min": 5,
     "policy_term_max": None, "entry_age_max": 65, "maturity_age_max": 85},
    {**_B, "plan_option": _LLP, "pay_type": "limited", "ppt": [5, 7, 10, 15], "policy_term_min": 10,
     "policy_term_max": None, "entry_age_max": 65, "maturity_age_max": 85},
    {**_B, "plan_option": _LLP, "pay_type": "limited", "ppt": "to_age_60", "policy_term_min": 10,
     "policy_term_max": None, "entry_age_max": 55, "maturity_age_max": 85},
    # Whole life (Life variant only)
    {**_B, "plan_option": ["life"], "pay_type": "regular", "ppt": "=policy_term", "policy_term_min": "whole_life",
     "policy_term_max": "whole_life", "entry_age_max": 65, "maturity_age_max": 99,
     "notes": "Whole Life: policy term = 99 less age at entry."},
    {**_B, "plan_option": ["life"], "pay_type": "limited", "ppt": 10, "policy_term_min": "whole_life",
     "policy_term_max": "whole_life", "entry_age_max": 65, "maturity_age_max": 99},
    {**_B, "plan_option": ["life"], "pay_type": "limited", "ppt": "to_age_60", "policy_term_min": "whole_life",
     "policy_term_max": "whole_life", "entry_age_max": 55, "maturity_age_max": 99},
    # Life Rebalancing
    {**_B, "plan_option": ["life_rebalancing"], "pay_type": "single", "ppt": 1, "policy_term_min": 15,
     "policy_term_max": 20, "entry_age_max": 45, "maturity_age_max": 75, "source_page": 13},
    {**_B, "plan_option": ["life_rebalancing"], "pay_type": "regular", "ppt": "=policy_term", "policy_term_min": 15,
     "policy_term_max": None, "entry_age_max": 45, "maturity_age_max": 85, "source_page": 13},
    {**_B, "plan_option": ["life_rebalancing"], "pay_type": "limited", "ppt": [5, 7, 10, 15, "to_age_60"],
     "policy_term_min": 15, "policy_term_max": None, "entry_age_max": 45, "maturity_age_max": 85, "source_page": 13,
     "notes": "Life Rebalancing is not available through POS."},
]

SPANS = {
    "key_features": [("Key features", "How does this plan protect you")],
    "plan_options": [("How does this plan protect you", "Plan Variants\nThis Policy"),
                     ("Life stage protection\nResponsibilities", "Eligibility conditions"),
                     ("Change in Premium Payment Term", "Salaried customer discount")],
    "death_benefit": [("Plan Variants\nThis Policy", "Life stage protection\nResponsibilities"),
                      ("Accidental Death Beneﬁt:\ni.", "Insta Payment on Claim Intimation")],
    "maturity_benefit": [("Maturity or paid-up or survival beneﬁt", "Surrender\nSurrender beneﬁt")],
    "optional_benefits": [("Smart Exit Beneﬁt\ni.", "Mr. Kumar is a 35"),
                          ("Health Management and Well-being Services", "Eligibility & Communication:")],
    "surrender_and_paid_up": [("Surrender\nSurrender beneﬁt", "Smart Exit Beneﬁt\ni."),
                              ("Premium discontinuance:", "Policy revival:")],
    "claims": [("Insta Payment on Claim Intimation", "Exclusions\n5.1")],
    "other_exclusions": [("Exclusions\n5.1", "Tax beneﬁts:")],
    "tax": [("Tax beneﬁts:", "Suicide clause:")],
    "suicide_exclusion": [("Suicide clause:", "Grace period:")],
    "grace_period": [("Grace period:", "Limited pay option:")],
    "revival": [("Policy revival:", "13. No loans")],
    "loan": [("13. No loans", "Modal loadings:")],
    "free_look": [("Free look period:", "Life stage protection:")],
    "riders": [("Enhance your policy by selecting", "Choose your policy term")],
    "non_disclosure_sec45": [("Section 45 of the Insurance Act, 1938,", "20. The product")],
}
NOTES = {
    "riders": "Brochure only names the Health Protect Rider (critical illness); rider terms are in separate rider brochures.",
    "claims": "Covers only the ₹3 lakh insta payment on claim intimation; full claim documents are listed in the policy document.",
}
