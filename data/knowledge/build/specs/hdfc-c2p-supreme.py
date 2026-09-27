SOURCE = "HDFC-Life-click-2-protect-supreme.pdf"

CARD = {
    "id": "hdfc-c2p-supreme",
    "name": "HDFC Life Click 2 Protect Supreme",
    "insurer": "HDFC Life",
    "uin": "101N183V01",
    "plan_type": "term",
    "product_class": "Non-Linked, Non-Participating, Individual, Pure Risk Premium/ Savings Life Insurance Plan",
    "goals": ["pure_protection"],
    "pitch_line": "Flexible term plan: level or rising cover, optional return of all premiums at maturity, extra accident cover, and add-ons for spouse and parents.",
    "key_benefits": [
        "3 plan options: Life, Life Plus (adds accidental death cover), Life Goal (cover reduces over time, e.g. to match a loan)",
        "Life option can increase cover up to 200% over the term (variants B and C)",
        "Optional Return of Premium: 100% of premiums paid back on survival (Life and Life Plus)",
        "Terminal illness diagnosis pays out early (up to ₹2 crore under Life), till age 80",
        "Add-ons: spouse cover, waiver of premium on critical illness or disability, Parent Secure, death benefit in instalments",
        "Immediate payout on claim intimation, Premium Break, Smart Exit",
    ],
    "plan_options": ["life", "life_plus", "life_goal"],
    "premium_payment_options": ["single", "regular", "limited"],
    "premium_frequency": ["single", "yearly", "half_yearly", "quarterly", "monthly"],
    "cover_up_to_age": 85,
    "min_sum_assured_inr": 10000,
    "riders": ["HDFC Life Income Benefit on Accidental Disability", "HDFC Life Protect Plus",
               "HDFC Life Health Plus", "HDFC Life LiveWell Rider"],
    "ideal_for": "Families wanting a customisable term plan: growing cover, a loan-linked reducing cover, or premiums back at maturity.",
    "not_for": "People looking for savings or income; without Return of Premium there is no maturity benefit.",
    "available_online": True,
    "source_file": SOURCE,
}

_B = dict(product_id=CARD["id"], entry_age_min=18, maturity_age_max=85, min_sum_assured_inr=10000,
          max_sum_assured_inr=None, min_annual_premium_inr=None, policy_term_max=None, channel="all", source_page=2)
ELIGIBILITY = [
    {**_B, "plan_option": ["life"], "pay_type": "single", "ppt": 1, "entry_age_max": 84, "maturity_age_min": 18,
     "policy_term_min": "1_month", "notes": "Entry above 65: Single Pay only, max basic sum assured ₹50,000."},
    {**_B, "plan_option": ["life", "life_plus"], "pay_type": "regular", "ppt": "=policy_term", "entry_age_max": 65,
     "maturity_age_min": 18, "policy_term_min": 2},
    {**_B, "plan_option": ["life", "life_plus"], "pay_type": "limited", "ppt": "2_to_policy_term_minus_1",
     "entry_age_max": 65, "maturity_age_min": 18, "policy_term_min": 3},
    {**_B, "plan_option": ["life_plus"], "pay_type": "single", "ppt": 1, "entry_age_max": 65, "maturity_age_min": 18,
     "policy_term_min": "1_month"},
    {**_B, "plan_option": ["life_goal"], "pay_type": "single", "ppt": 1, "entry_age_max": 65, "maturity_age_min": 23,
     "policy_term_min": 5},
    {**_B, "plan_option": ["life_goal"], "pay_type": "limited", "ppt": "2_to_policy_term_minus_1", "entry_age_max": 65,
     "maturity_age_min": 23, "policy_term_min": 7, "notes": "Life Goal has no Regular Pay."},
]

EXCLUDE = [("Example: Mr. Bansal", "Death Benefit:\n“Death Benefit”")]

SPANS = {
    "key_features": [("Key Features", "Eligibility\nPlan Option")],
    "plan_options": [("Plan Options\nFollowing options", "Benefits payable under various plan options:")],
    "death_benefit": [("Benefits payable under various plan options:", "Additional benefits available under the Product:")],
    "maturity_benefit": [("Maturity Benefit:\nOn survival until Maturity", "2. Life Plus Option"),
                         ("1) Return of Premium (ROP) Option", "2) Waiver of Premium on CI")],
    "optional_benefits": [("Additional benefits available under the Product:", "12) Immediate Payout on Claim Intimation"),
                          ("13) Premium Break Benefit", "14) Health management"),
                          ("Smart Exit Benefit:", "Revival\nYes, If")],
    "claims": [("12) Immediate Payout on Claim Intimation", "13) Premium Break Benefit")],
    "grace_period": [("Non Payment of Premiums", "Paid-Up\nA policy")],
    "surrender_and_paid_up": [("Paid-Up\nA policy", "Smart Exit Benefit:")],
    "revival": [("Revival\nYes, If", "Riders\nWe offer")],
    "riders": [("Riders\nWe offer", "Terms and Conditions\nWe recommend")],
    "suicide_exclusion": [("a. Suicide Exclusion", "b. Age Admitted")],
    "other_exclusions": [("c. Exclusions for Accidental Death benefit", "C) Tax Benefits")],
    "tax": [("C) Tax Benefits", "D) Cancellation"), ("M) Taxes:", "N) A policyholder")],
    "free_look": [("D) Cancellation in the Free-Look period:", "E) An underwriting")],
    "loan": [("F) Policy Loan:", "G) Nomination")],
    "non_disclosure_sec45": [("J) Non-Disclosure:", "L) This is not")],
}
NOTES = {
    "claims": "Covers only the immediate payout on claim intimation; the full claim process is in the policy document.",
}
