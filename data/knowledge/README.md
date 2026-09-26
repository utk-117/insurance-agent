# Life insurance knowledge base (10 products)

Built from the 10 official brochures in `Downloads/life-insurance-policies/`. Three layers:

| Layer | File | Used by | When |
|---|---|---|---|
| 1. Cards | `cards.json` | LLM prompt | Always (about 4.5k tokens for all 10) |
| 2. Eligibility | `eligibility.json` + `eligibility.py` | Code only | Before recommending: filter by age (and goal) |
| 3. Sections | `sections/<product_id>.json` | LLM prompt | On demand: one topic of one product per question |

## Products

| id | Insurer | Type |
|---|---|---|
| sbi-smart-shield-plus | SBI Life | Term |
| sbi-smart-swadhan-supreme | SBI Life | Term, return of premium |
| sbi-smart-platina-plus | SBI Life | Guaranteed income |
| sbi-smart-bachat-plus | SBI Life | Participating endowment |
| icici-iprotect-smart-plus | ICICI Pru | Term |
| icici-gift-pro | ICICI Pru | Guaranteed income |
| icici-assured-savings | ICICI Pru | Guaranteed savings (min premium ₹20 lakh/yr) |
| hdfc-c2p-supreme | HDFC Life | Term |
| hdfc-sanchay-plus | HDFC Life | Guaranteed savings / income |
| hdfc-sanchay-par-advantage | HDFC Life | Participating income, whole life |

## Layer 1: card fields
`id, name, insurer, uin, plan_type, product_class, goals[], pitch_line, key_benefits[], plan_options[], premium_payment_options[], premium_frequency[], cover_up_to_age, min_sum_assured_inr, riders[], ideal_for, not_for, available_online (null = brochure doesn't say), purchase_url (fill in), source_file, topics_available[], data_caveats[]`

`goals` uses the discovery values: `pure_protection`, `savings_protection`. None of the 10 fits `child_future` or `retirement` alone; savings plans that allow minors or lifelong income are flagged in `key_benefits`.

## Layer 2: eligibility rows
One row per combination of plan option × pay type × premium payment term (PPT) × channel. The value conventions are:

- `plan_option`: a list of options the row applies to, or `null` when the plan has no options
- `pay_type`: `single` / `regular` / `limited`
- `ppt`: an integer, a list, `"=policy_term"`, `"to_age_60"` or `"2_to_policy_term_minus_1"`
- `policy_term_min` / `policy_term_max`: an integer; `null` means limited only by `maturity_age_max`; `"whole_life"` means the term runs to `maturity_age_max`; `"1_month"` means under a year
- `entry_age_min` / `entry_age_max`: an integer (0 means 30 days, see `entry_age_min_note`), or `"18-policy_term"` / `"65-policy_term"` (GIFT Pro)
- `channel`: `all` (bank, direct, online). The agent uses this. `pos` rows are POSP-only and kept for completeness.
- `min_annual_premium_inr`: this is an eligibility floor, not a quote. Never say it as "your premium".

`eligibility.py → eligible_products(age, goal, channel="all", rows, cards)` returns the products whose rows admit that age. It has been checked against these ages: 17 → savings plans only; 62 → 3 term plans + 2 HDFC savings plans; 66–84 → only HDFC Click 2 Protect Supreme (Single Pay).

## Layer 3: sections
There are 16 fixed topics: `key_features, plan_options, death_benefit, maturity_benefit, optional_benefits, riders, free_look, grace_period, suicide_exclusion, surrender_and_paid_up, loan, revival, tax, claims, non_disclosure_sec45, other_exclusions`.

Each section is `{topic, available, text, pages, note?}`. `text` is the brochure wording word for word, and `pages` are PDF page numbers for citation. If `available: false`, the agent says the brochure doesn't cover it and offers an advisor callback.

Premium illustrations, sample premium tables and 4%/8% bonus projections have been left out on purpose. A regex scan confirms no premium figures remain. The figures that do remain are benefit amounts and limits, for example the ₹3 lakh insta-payout and rider sum-assured caps.

## Known gaps / review before go-live
- **Claims:** only iProtect Smart Plus and Click 2 Protect Supreme brochures cover it, and only the instant/immediate payout part. The full claim process lives in the policy wordings.
- **ICICI Assured Savings** brochure is from FY 2023-24. Check that it is the current version.
- **`purchase_url`** is null for all 10. Fill in each product page URL.
- Eligibility tables were checked by eye against the rendered PDF pages, because the extracted text garbles them. A human spot-check is still recommended.

## Rebuild
The build scripts are `specs/<id>.py` (card, eligibility rows, section anchors), `slice.py` and `build.py`. Run `python build.py`.

## Added for the agent (outside the build pipeline — maintained by hand)
| File | Purpose |
|---|---|
| `need_fit.json` | Customer need -> product features (+ section topic), `gate` / `soft_gate` per product |
| `topic_router.json` | Keyword -> section topic routing (English + Hinglish), core topics, product aliases |
| `insurers.json` | Insurer name in cards -> slug used by `claims_history.json` and `data/insurers/<slug>/insurer.md` |
| `claims_history.json` | IRDAI Handbook 2024-25 Table 15, individual death claims FY23–FY25 |
| `buying_process.md` | Buying, underwriting, disclosure, free-look, claims (IRDAI rules) |
| `check_integrity.py` | Fails if any of the above references a product, topic, need or insurer that doesn't exist |

`eligibility.py` now maps discovery goals `child_future` and `retirement` to `savings_protection` (`GOAL_ALIASES`).
After running `build/build.py`, always run `python check_integrity.py`.

## v2 additions (intake -> consult redesign)
| File | Purpose |
|---|---|
| `underwriting_rules.json` | The 5 intake questions (wording EN/HI), max cover rule (25x income if age <= 35, 20x above; self-employed same with income proof), options for people not working, product gates |
| `pricing.json` | Exact premium / benefit examples from each brochure (with page numbers) + a labelled estimation model (age, tobacco, gender factors, +/- range). Indicative only. |
| `intake_rules.py` | `max_cover()`, `estimate_term_premium()`, `savings_illustration()`, `profile_snapshot()`; run it to see 3 sample profiles |

Gates moved from `need_fit.json` to `underwriting_rules.json`; iProtect's old soft gate is replaced by the
min-cover vs max-cover feasibility check in `profile_snapshot()`.
