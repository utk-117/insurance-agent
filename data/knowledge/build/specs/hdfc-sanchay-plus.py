SOURCE = "Sanchay-Plus-brochure.pdf"

CARD = {
    "id": "hdfc-sanchay-plus",
    "name": "HDFC Life Sanchay Plus",
    "insurer": "HDFC Life",
    "uin": "101N134V29",
    "plan_type": "guaranteed_savings",
    "product_class": "Individual non-participating, non-linked savings life insurance plan",
    "goals": ["savings_protection"],
    "pitch_line": "Guaranteed savings plan with four ways to receive your money: a lump sum, income for 10-12 years, income for 25-30 years, or income for life till age 99.",
    "key_benefits": [
        "4 options: Guaranteed Maturity (lump sum), Guaranteed Income (10/12 yrs), Long Term Income (25/30 yrs), Life Long Income (till 99)",
        "All maturity benefits guaranteed if all premiums are paid",
        "Life Long and Long Term Income options also return total premiums paid at the end of the payout",
        "Single Pay or pay for 5-12 years (up to 20 for Guaranteed Maturity)",
        "Can cover a child from 30 days of age",
        "Enhanced benefits for annual premiums above ₹1.5 lakh",
    ],
    "plan_options": ["guaranteed_maturity", "guaranteed_income", "life_long_income", "long_term_income"],
    "premium_payment_options": ["single", "limited_5_to_12", "limited_15", "limited_20"],
    "premium_frequency": ["single", "yearly", "half_yearly", "quarterly", "monthly"],
    "cover_up_to_age": 85,
    "min_sum_assured_inr": None,
    "riders": ["HDFC Life Income Benefit on Accidental Disability", "HDFC Life Protect Plus", "HDFC Life Health Plus",
               "HDFC Life Waiver of Premium Rider", "HDFC Life LiveWell Rider"],
    "ideal_for": "Risk-averse savers who want a guaranteed lump sum or a guaranteed income stream for retirement, children's education or a lifelong pension-like income.",
    "not_for": "People wanting high life cover per rupee, or market-linked growth.",
    "available_online": None,
    "source_file": SOURCE,
}

_GI = {"single": (5, 20), 5: (5, 15), 6: (6, 15), 7: (7, 15), 8: (8, 15), 9: (9, 15), 10: (10, 20), 11: (11, 20), 12: (12, 20)}
_LLI = {"single": (5, 10), 5: (5, 15), 6: (6, 15), 7: (7, 15), 8: (8, 15), 9: (9, 15), 10: (10, 20), 11: (11, 20), 12: (12, 20)}
_LTI = {"single": (5, 15), **{p: (p, 15) for p in range(5, 13)}}
_GM = {"single": (5, 20), **{p: (10, 30) for p in range(5, 11)}, 12: (12, 30), 15: (15, 30), 20: (20, 30)}
_AGES = {  # option: (entry_min, entry_max, mat_min, mat_max, payout)
    "guaranteed_maturity": (0, 60, 18, 85, "lump sum at maturity"),
    "guaranteed_income": (0, 65, 18, 85, "income for 10 or 12 years after the policy term"),
    "life_long_income": (50, 65, 55, 85, "income from the year after the policy term till age 99"),
    "long_term_income": (3, 60, 18, 75, "income for 25 or 30 years after the policy term"),
}
_TERMS = {"guaranteed_maturity": _GM, "guaranteed_income": _GI, "life_long_income": _LLI, "long_term_income": _LTI}

ELIGIBILITY = []
for opt, terms in _TERMS.items():
    emin, emax, mmin, mmax, payout = _AGES[opt]
    for ppt, (ptmin, ptmax) in terms.items():
        row = {"product_id": CARD["id"], "plan_option": [opt],
               "pay_type": "single" if ppt == "single" else "limited", "ppt": 1 if ppt == "single" else ppt,
               "policy_term_min": ptmin, "policy_term_max": ptmax, "entry_age_min": emin, "entry_age_max": emax,
               "maturity_age_min": mmin, "maturity_age_max": mmax, "min_sum_assured_inr": None,
               "max_sum_assured_inr": None, "min_annual_premium_inr": 30000, "channel": "all", "source_page": 3,
               "payout": payout}
        if emin == 0:
            row["entry_age_min_note"] = "30 days; risk cover starts immediately, policy vests in the child at 18"
        ELIGIBILITY.append(row)
        pos = dict(row, entry_age_max=min(emax, 60), maturity_age_max=65, max_sum_assured_inr=2500000,
                   channel="pos", source_page=4, notes="POSP variant: sum assured on death capped at ₹25 lakh; no riders.")
        if pos["entry_age_min"] <= pos["entry_age_max"]:
            ELIGIBILITY.append(pos)

SPANS = {
    "key_features": [("KEY FEATURES OF HDFC LIFE SANCHAY PLUS", "ELIGIBILITY\nEligibility Criteria")],
    "plan_options": [("HOW THIS PLAN WORKS?", "BENEFITS IN DETAIL")],
    "maturity_benefit": [("BENEFITS IN DETAIL", "Rider Options:")],
    "death_benefit": [("BENEFITS IN DETAIL", "Rider Options:")],
    "riders": [("Rider Options:", "Sample Illustration")],
    "grace_period": [("Grace period:\nGrace period is not", "Lapse, Paid-up and Surrender:")],
    "surrender_and_paid_up": [("Lapse, Paid-up and Surrender:", "Revival:")],
    "revival": [("Revival:", "TERMS & CONDITIONS")],
    "suicide_exclusion": [("B) Suicide Exclusions:", "C) Tax Benefits")],
    "tax": [("C) Tax Benefits", "D) Cancellation"), ("Q) Taxes:", "R) A policyholder")],
    "free_look": [("D) Cancellation in the Free-Look period:", "E) Alterations:")],
    "loan": [("Policy Loan: Once your policy", "G) Enhanced Benefit")],
    "optional_benefits": [("E) Alterations:", "Policy Loan: Once your policy"),
                          ("G) Enhanced Benefit", "I) Guaranteed Surrender")],
    "non_disclosure_sec45": [("N) Non-Disclosure:", "P) This is not")],
}
NOTES = {
    "maturity_benefit": "Maturity and death benefits are described together, option by option. Guaranteed Additions and income rates vary by age, term and premium. Never quote amounts.",
    "death_benefit": "Maturity and death benefits are described together, option by option.",
    "claims": "Brochure does not describe the claim process. Offer an advisor callback.",
    "other_exclusions": "Brochure lists no exclusions other than the suicide clause; rider exclusions are in rider brochures.",
}
