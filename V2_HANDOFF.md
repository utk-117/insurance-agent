# v2 handoff — paste this to Claude Code

Copy the files in this folder over the repo (same paths), then tell Claude Code:

> Read CLAUDE.md, especially the "v2 DESIGN" section, and do milestone **M2b**. Keep the M0–M2 adapters,
> knowledge.py, actions, time parsing, CLI and evals runner; replace the v1 stage machine with the v2 phase
> controller (greet -> identity -> 5-question intake in code -> `profile_snapshot()` -> free consult with tools ->
> guarded close). Use `data/knowledge/intake_rules.py` as the reference for eligibility, max cover and indicative
> premiums. Delete `prompts/stages.md` once the v2 flow runs. Stop after M2b so I can review transcripts.

## Files in this update
| Path | Change |
|---|---|
| `CLAUDE.md` | v2 design (3 phases, tools, pricing rules), new eval cases + scorecard, M2b milestone |
| `prompts/system.md` | rewritten for v2: consultative selling, pricing with disclaimer, claims-paid framing |
| `prompts/phases.md` | NEW, replaces `prompts/stages.md` |
| `prompts/objections.md` | now guidance, not a classifier |
| `data/knowledge/underwriting_rules.json` | NEW: 5 intake questions, max cover rule, not-working options, gates |
| `data/knowledge/pricing.json` | NEW: brochure premium/benefit examples (with pages) + labelled estimate model |
| `data/knowledge/intake_rules.py` | NEW: max_cover, estimate_term_premium, savings_illustration, profile_snapshot |
| `data/knowledge/need_fit.json` | gates removed (moved to underwriting_rules.json) |
| `data/knowledge/check_integrity.py` | also checks pricing + rules |
| `data/knowledge/README.md` | documents the new files |

Sanity check after copying: `python data/knowledge/check_integrity.py` and `python data/knowledge/intake_rules.py`.
