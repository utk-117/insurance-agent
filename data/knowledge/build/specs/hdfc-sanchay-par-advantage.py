SOURCE = "HDFC-Life-Sanchay-Par-Advantage-Retail-Brochure.pdf"

CARD = {
    "id": "hdfc-sanchay-par-advantage",
    "name": "HDFC Life Sanchay Par Advantage",
    "insurer": "HDFC Life",
    "uin": "101N136V04",
    "plan_type": "participating_income",
    "product_class": "Individual Non-Linked, Participating, Savings Life Insurance Plan",
    "goals": ["savings_protection"],
    "pitch_line": "Participating plan with life cover up to age 100: yearly cash bonuses (if declared) from year one, or a guaranteed income after premiums end, plus a lump sum legacy at maturity.",
    "key_benefits": [
        "Immediate Income option: cash bonus (if declared) every year from the 1st policy year",
        "Deferred Income option: Guaranteed Income for up to 25 years after the premium term, plus cash bonuses (if declared)",
        "Maturity: Sum Assured on Maturity + accrued bonuses/income not taken + terminal bonus (if declared)",
        "Cover can run to age 100 (whole life) or for a fixed 20-40 years",
        "Payouts can be left to accumulate, and paid on a date of your choice",
        "Bonuses are not guaranteed",
    ],
    "plan_options": ["immediate_income", "deferred_income"],
    "premium_payment_options": ["limited_5", "limited_6", "limited_7", "limited_8", "limited_9", "limited_10", "limited_12"],
    "premium_frequency": ["yearly", "half_yearly", "quarterly", "monthly"],
    "cover_up_to_age": 100,
    "min_sum_assured_inr": 300000,
    "riders": ["HDFC Life Waiver of Premium Rider", "HDFC Life Protect Plus Rider", "other HDFC Life riders as listed"],
    "ideal_for": "People who want a lifelong income stream and a legacy for their children, and are comfortable with part of the return being non-guaranteed bonuses.",
    "not_for": "Anyone needing fully guaranteed returns or maximum life cover per rupee.",
    "available_online": None,
    "purchase_url": None,
    "source_file": SOURCE,
}

_B = dict(product_id=CARD["id"], pay_type="limited", entry_age_min=0,
          entry_age_min_note="30 days; for age below 1, risk starts from the first policy anniversary",
          maturity_age_min=None, maturity_age_max=100, min_sum_assured_inr=300000, max_sum_assured_inr=None,
          min_annual_premium_inr=25000, channel="all", source_page=2,
          notes="Policy term: 100 minus age at entry (whole life), or a fixed 20-40 years.")
ELIGIBILITY = []
for ppt, emax in [(5, 50), (6, 65), (7, 65), (8, 65), (9, 65), (10, 65), (12, 65)]:
    ELIGIBILITY += [{**_B, "plan_option": ["immediate_income"], "ppt": ppt, "entry_age_max": emax,
                     "policy_term_min": 20, "policy_term_max": 40},
                    {**_B, "plan_option": ["immediate_income"], "ppt": ppt, "entry_age_max": emax,
                     "policy_term_min": "whole_life", "policy_term_max": "whole_life"}]
for ppt, emax in [(7, 55), (8, 55), (9, 60), (10, 60), (12, 60)]:
    ELIGIBILITY += [{**_B, "plan_option": ["deferred_income"], "ppt": ppt, "entry_age_max": emax,
                     "policy_term_min": 20, "policy_term_max": 40},
                    {**_B, "plan_option": ["deferred_income"], "ppt": ppt, "entry_age_max": emax,
                     "policy_term_min": "whole_life", "policy_term_max": "whole_life"}]

SPANS = {
    "key_features": [("KEY FEATURES OF HDFC LIFE SANCHAY PAR ADVANTAGE", "ELIGIBILITY\nThis plan")],
    "plan_options": [("PLAN OPTIONS", "PREMIUMS\nYou can"), ("HOW DOES THIS PLAN WORK?", "BENEFITS IN DETAIL:")],
    "maturity_benefit": [("a) Survival Benefit:", "c) Death Benefit:"),
                         (("a) Survival Benefit:", 1), "c) Death Benefit:")],
    "death_benefit": [("c) Death Benefit:", "Illustration for a Male"),
                      (("c) Death Benefit:", 1), "Illustration for a Male"),
                      ("DEATH MULTIPLE (Applicable", "BONUSES:")],
    "optional_benefits": [("BONUSES:", "NON-FORFEITURE BENEFITS:"), ("E) Alterations:", "F) An underwriting"),
                          ("H) ADDITIONAL BENEFIT", "I) Guaranteed Surrender")],
    "grace_period": [("Grace period:", "Lapse, Paid-up and Surrender:")],
    "surrender_and_paid_up": [("Lapse, Paid-up and Surrender:", "Revival:")],
    "revival": [("Revival:", "RIDERS")],
    "riders": [("RIDERS", "TERMS & CONDITIONS")],
    "suicide_exclusion": [("B) Suicide Exclusions:", "C) Tax Benefits")],
    "tax": [("C) Tax Benefits", "D) Cancellation"), ("R) Taxes:", "S) A policyholder")],
    "free_look": [("D) Cancellation in the Free-Look period:", "E) Alterations:")],
    "loan": [("G) Policy Loan:", "H) ADDITIONAL")],
    "non_disclosure_sec45": [("O) Non-Disclosure:", "Q) This is not")],
}
NOTES = {
    "maturity_benefit": "Cash and terminal bonuses are not guaranteed. The brochure's 4%/8% illustrations have been left out on purpose; never quote them.",
    "claims": "Brochure does not describe the claim process. Offer an advisor callback.",
    "other_exclusions": "Brochure lists no exclusions other than the suicide clause; rider exclusions are in rider brochures.",
}
