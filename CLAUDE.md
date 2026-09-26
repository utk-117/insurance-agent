# CLAUDE.md — Insurance Voice Sales Agent (Sarvam AI assignment)

## What we're building
A browser-based voice agent that sells **life insurance** products from **multiple Indian insurers** (**10 products** from **SBI Life, ICICI Prudential Life and HDFC Life** — see `data/knowledge/README.md`;
health is out of scope). The agent speaks for a configurable advisory brand (`BRAND_NAME`,
a fictional distributor), not for any one insurer. It asks 5 fixed intake questions, works out eligibility, maximum cover and indicative premiums in code, then
runs a free, LLM-driven sales conversation around the customer's own intent, answering on coverage, claims,
validity, price and the buying process **strictly from the provided documents and data**, and closes each conversation with one of: human advisor callback scheduled (**primary goal**),
product purchase link shared (only when the customer has firmly decided on a product),
or not interested. Every outcome is logged to a spreadsheet the sales team checks.

Goal: a working end-to-end demo, not polish. Every milestone below must be runnable on its own.

## Hard constraints
- **Build the voice pipeline ourselves.** NO Pipecat, LiveKit, Vapi, Retell, or any voice-agent framework.
  NO LangChain / LlamaIndex. Plain Python + HTTP calls.
- **STT, TTS and LLM are all swappable providers**, chosen by env vars. **Default: all three = Sarvam.**
  - `STT_PROVIDER` = `sarvam` (default) — Saaras/Saarika
  - `TTS_PROVIDER` = `sarvam` (default) — Bulbul
  - `LLM_PROVIDER` = `sarvam` (default) | `anthropic`; `LLM_MODEL` sets the model per provider
  - Implement Sarvam for all three first. Add `anthropic` for LLM in M3. Other STT/TTS providers only if the
    human asks — the interface must make that a one-file addition.
  - Read https://docs.sarvam.ai for current model names, request formats, audio formats, language codes, and
    whether the chat API supports JSON mode / structured output, before writing adapters.
- **Adapter contract** (each provider = one file in `app/adapters/<kind>/<provider>.py`, registered in a dict):
  - `STT.transcribe(audio: bytes, mime: str, lang_hint: str|None) -> {text, language_code, provider_ms}`
  - `TTS.speak(text: str, language_code: str) -> {audio: bytes, mime: str, provider_ms}`
  - `LLM.complete_json(system: str, messages: list, schema: dict) -> {data: dict, provider_ms, input_tokens, output_tokens}`
  - `LLM.chat_with_tools(system: str, messages: list, tools: list) -> {reply: str|None, tool_calls: [...], provider_ms, ...}`
    (v2 consult phase; native tools where supported, JSON tool protocol otherwise)
  - Every call is timed and logged with provider + model, so latency can be compared across providers.
  - JSON robustness (matters most for Sarvam LLM): strip code fences, extract the first JSON object, validate with
    pydantic, one repair retry, then safe fallback reply. Count parse failures per provider in the logs.
- For Claude: use the official `anthropic` SDK, static prompt parts (rails + cards + need_fit + buying_process + objections) first, per-turn context
  last, with prompt caching.
- Never invent product facts. All product knowledge comes from `data/`.
- Secrets only in `.env` (provide `.env.example`). Ask before adding any dependency not listed below.
- All prompt text lives in `prompts/` as markdown — never hard-coded in Python.

## Stack
- Python 3.11, FastAPI, uvicorn, websockets, httpx, pydantic, anthropic, gspread + google-auth, python-dotenv
- ffmpeg (system) for audio conversion
- Docker (`Dockerfile` installs ffmpeg) -> deployed on Google Cloud Run, region `asia-south1` (Mumbai)
- Frontend: one `static/index.html` + `static/app.js`, vanilla JS, no build step

## Repo layout
```
app/
  main.py            # FastAPI: POST /api/session, WS /ws/{session_id}, static files
  pipeline.py        # one turn: audio -> STT -> controller -> normalize -> TTS chunks -> client
  adapters/
    base.py          # interfaces + provider registry, reads STT_/TTS_/LLM_PROVIDER
    stt/sarvam.py
    tts/sarvam.py
    llm/sarvam.py, llm/anthropic.py
  agent/
    state.py         # Phase enum, SessionState dataclass
    controller.py    # v2: phase controller (greet/identity/intake in code) + consult tool loop + close guards
    tools.py         # v2 tool registry (see v2 DESIGN)
    knowledge.py     # load data/knowledge/*; shortlist() (eligibility + gates + need_fit rank),
                     # route_topics() (topic_router), get_sections(), insurer_notes(), claims_record()
    actions.py       # share_purchase_link(), log_callback(), log_outcome()
  normalize.py       # TTS text normalisation (₹, lakh/crore, dates, abbreviations)
  sheets.py          # Google Sheets writer, CSV fallback if creds missing
  cli.py             # text-only chat loop for M2 (same controller, no audio)
scripts/
  smoke.py           # hit STT, TTS, LLM once each and print latency
  bench.py           # latency benchmark: fixed audio clips + fixed turns, N runs per provider combo,
                     # prints p50/p90 per stage and total-to-first-audio as a table (CSV to data/bench/)
data/
  knowledge/                # ALREADY BUILT — do not regenerate. See data/knowledge/README.md
    README.md
    cards.json              # L1: one card per product (10) — always in prompt (~6k tokens)
    eligibility.json        # L2: 179 rows (plan option x pay type x PPT x channel) — code only
    eligibility.py          # L2: eligible_products(age, goal, channel="all", rows, cards); maps child_future /
                            #     retirement -> savings_protection via GOAL_ALIASES
    sections/<id>.json      # L3: brochure wording by 16 fixed topics, with page numbers — loaded per topic
    need_fit.json           # reference: customer need -> product features (+ section topic)
    underwriting_rules.json # v2: intake questions, max cover (25x <=35, 20x >35), not-working options, gates
    pricing.json            # v2: brochure premium/benefit examples (anchors) + labelled estimation model
    intake_rules.py         # v2: max_cover(), estimate_term_premium(), savings_illustration(), profile_snapshot()
    topic_router.json       # keyword -> topic routing (English + Hinglish), core topics, product aliases
    insurers.json           # insurer name (cards) -> slug (claims_history, insurer.md)
    claims_history.json     # IRDAI individual death claims, FY23–FY25, per insurer
    buying_process.md       # how buying/underwriting/claims work in India — always in prompt
    check_integrity.py      # run after any change; fails on broken cross-references
    build/                  # build.py, slice.py, cols.sh, specs/<id>.py — rebuilds cards/eligibility/sections
  insurers/<insurer-slug>/
    insurer.md              # medical tests, claim intimation + documents, contacts
    products/*.pdf          # the 10 source brochures — committed to git
prompts/
  system.md          # persona + rails (always included)
  phases.md          # v2: per-phase guide (replaces stages.md)
  objections.md      # v2: objection guidance for the consult phase (not a classifier)
evals/
  cases.yaml         # scripted conversations + expected behaviour
  run_evals.py       # runs cases through controller (text mode), prints pass/fail
static/index.html, static/app.js
README.md, NOTES.md  # NOTES.md = approach, challenges, latency/cost numbers, production next steps
```

## v2 DESIGN (supersedes the v1 stage machine) — read this before touching the agent
v1 (M2) scripted every step. v2 is **deterministic only where it must be** and lets the LLM run the actual
sales conversation.

```
PHASE 1  INTAKE (code-driven)   5 fixed questions -> profile_snapshot() -> eligible plans, max cover, price ranges
PHASE 2  CONSULT (LLM-driven)   one open intent question, then a free conversation; the agent uses TOOLS
PHASE 3  CLOSE (code-guarded)   callback (default) or purchase link; code validates + logs
```
Before PHASE 1: greet, confirm identity ("Am I speaking with {name}?"), consent to 2 minutes (as in v1).

### Phase 1 — Intake (deterministic)
- Slots, asked in this order, one per turn, wording from `underwriting_rules.json.intake_questions` (the LLM may
  rephrase naturally but must not skip or add questions): **age, gender, employment_type (salaried |
  self_employed | not_working), annual_income_inr (skip if not_working), tobacco (last 12 months)**.
- Code decides the next slot. The LLM call in this phase only (a) extracts any slots from the customer's words
  (several at once is fine; monthly income -> x12; lakh/crore; ranges -> midpoint) and (b) phrases the next
  question + a one-line acknowledgement. If the customer asks a question mid-intake, answer briefly, then
  continue intake.
- When all slots are filled: `snapshot = intake_rules.profile_snapshot(profile)` (in `data/knowledge/intake_rules.py`
  — reference implementation, tested; move/import it into `app/agent/` as you see fit). The snapshot holds:
  eligible plans, excluded plans with reasons, **max cover** (25x income if age <= 35, else 20x; same for
  self-employed with income proof), and **indicative premium ranges** for each eligible term plan at ₹1 Cr and at
  max cover. Log it.
- Transition line (LLM): one sentence summarising what they're eligible for (e.g. "You can get term cover of up
  to about ₹3 crore"), then the open intent question.

### Phase 2 — Consult (non-deterministic; this is where the agent earns its keep)
- Open question, natural language, e.g. "Tell me a bit about what you'd like this insurance to do for you and
  your family." No option lists, no forced categories.
- The customer can ramble, change topic, give several intents. The LLM infers the real intent(s) (family income
  replacement, loan cover, money back, guaranteed second income, child's education, retirement, legacy, tax,
  "my friend said…") and decides which **eligible** plans fit, why, and what to say next. `need_fit.json` is
  reference knowledge for that mapping, not a script.
- Selling points it may use, all via tools/snapshot, never invented: product benefits (cards/sections),
  **indicative premium range** (with disclaimer), **claims paid by amount and by number** (IRDAI), cover
  amount vs their max cover, salaried/female discounts where the brochure states them.
- The agent drives toward a close (callback, or purchase link if the customer has decided), handles
  objections conversationally (`prompts/objections.md` is guidance, not a classifier), and respects a no.

**Tools** (one registry, `app/agent/tools.py`; each returns compact JSON with page/source refs):
| tool | args | returns |
|---|---|---|
| `get_product_info` | product_id, topics[] (from the 16 section topics) | brochure wording + pages |
| `get_premium_estimate` | product_id, sum_assured, [pay] | range, basis, disclaimer (`intake_rules.estimate_term_premium`) |
| `get_savings_illustration` | product_id, annual_premium | brochure illustrations scaled (`intake_rules.savings_illustration`) |
| `get_claims_record` | insurer_slug | IRDAI FY23–FY25 paid % by amount + number |
| `compare_products` | product_ids[2-3] | cards side by side + price ranges + claims records |
| `get_process_info` | topic (medical_tests, claims, free_look, disclosure...) | buying_process.md / insurer.md excerpt |
| `book_callback` | datetime_iso, product_ids[], note, customer_confirmed(bool) | code validates future IST time + confirmation; logs |
| `share_purchase_link` | product_id | card event to UI (skipped if purchase_url is null) |
| `end_conversation` | outcome, summary | logs outcome; moves to WRAP_UP |

**Tool calling per provider** (same registry, same prompt):
- `anthropic`: native tool use. Max 2 tool rounds per customer turn, then the model must answer.
- `sarvam`: if the chat API supports tools, use them; otherwise a JSON protocol: the model returns
  `{"reply": str|null, "tool_calls": [{"name","args"}]}`; code runs the tools and calls again (max 2 rounds).
  Record which one you used and the tool-call error rate in NOTES.md — that is a real finding for Sarvam.
- Latency: the snapshot (profile, eligible plans, max cover, price ranges, claims records for eligible
  insurers) is in the prompt from Phase 2 on, so the common questions (price, claims, which plan) need **zero**
  tool calls. Tools are for detail (sections, comparisons, savings illustrations, booking).
- While a tool round runs in voice mode, speak a short filler ("Ek second, main check karti hoon") only if the
  round takes > 1.5 s.

### Phase 3 — Close (code-guarded)
- `book_callback` succeeds only if `customer_confirmed` is true, the time is in the future (IST) and within 14
  days; otherwise the tool returns an error the model must act on (ask again / read back). Keep the existing
  `parse_time_text` fallback and weekday calendar in context.
- `share_purchase_link` only after the customer says they've decided; always offer a callback after.
- Every session ends with `log_outcome` (also on disconnect/timeout: `dropped`).

### What goes into each LLM call (v2)
| Block | Source | When |
|---|---|---|
| Persona + rails | `prompts/system.md` | always (cached) |
| PRODUCT CARDS | `cards.json` minus `topics_available`, `source_file`, `uin` | always (cached) |
| NEED FIT | `need_fit.json` | Phase 2 (cached) |
| PROCESS KNOWLEDGE | `buying_process.md` | always (cached) |
| PHASE GUIDE | `prompts/phases.md` section for the current phase | always |
| INTAKE STATE | filled/missing slots + next slot | Phase 1 |
| SNAPSHOT | `profile_snapshot()` output + claims records of eligible insurers | Phase 2–3 |
| OBJECTION GUIDE | `prompts/objections.md` | Phase 2 (cached) |
| Tool results | tools | when called |
The v1 topic router (`knowledge.route_topics`) can stay as a **prefetch**: if the customer's words clearly name
a topic for the product under discussion, preload that section so no tool call is needed.

### Session state (v2)
```python
lead: {name, phone}
phase: GREET|CONFIRM_IDENTITY|INTAKE|CONSULT|CLOSE|WRAP_UP|END
profile: {age, gender, employment_type, annual_income_inr, tobacco}          # intake slots
snapshot: dict|None                                                          # profile_snapshot() output
intents: [str]            # free-text intents the LLM inferred (logged, not used for control flow)
discussed_products: [product_id], quoted: [{product_id, sum_assured, range}]
callback_time, outcome, soft_retry_used, transcript, latencies, tool_calls: [{name, ms, ok}]
```

### Logging (sheet / CSV row, one per session)
`timestamp_ist, session_id, name, phone, age, gender, employment_type, annual_income_inr, tobacco, max_cover,
eligible_products, intents, discussed_products, quoted_ranges, objections (free text), outcome,
callback_time_ist, purchase_link, summary, turns, tool_calls, avg_first_audio_ms`

### Pricing rules (replaces v1 "no pricing")
- Prices only from the snapshot or `get_premium_estimate` / `get_savings_illustration`. The LLM never computes,
  rounds differently, or extrapolates a price.
- Always as a **range**, always with the disclaimer (indicative, from brochure examples, final premium after
  underwriting). Mention the salaried first-year discount only where the tool returns it.
- Savings plans: talk in "for ₹X a year you get Y", from the brochure illustration, with age caveat; for
  participating plans always give both 4% and 8% and say bonuses aren't guaranteed.
- "Approval" = how much of claimed money the insurer actually paid: quote `paid_pct_by_amount` ("of every ₹100
  claimed in FY25, X paid ₹95.26") with `paid_pct_by_number`, FY and "as per IRDAI data". Never predict an
  individual claim.

## Voice pipeline
1. Page load: form with `name` (prefilled "Utkarsh"), `phone`, and `access_code` -> `POST /api/session` -> `session_id` -> open WS. Server sends the greeting
   (TTS) first; the agent speaks first.
2. Push-to-talk (hold button or spacebar). `MediaRecorder` -> on release, send one binary blob over WS.
3. Server: ffmpeg -> 16 kHz mono WAV (or whatever format Sarvam STT accepts) -> STT (code-mixed / auto language).
4. Controller turn -> `reply`.
5. `normalize.py` -> split into sentences -> TTS requests fired concurrently -> send audio chunks **in order**
   (`{"type":"audio","seq":n,"data":base64}`) as each is ready; client queues and plays sequentially.
6. Also emit to UI: `transcript` (both sides), `state` (stage + profile + shortlist), `latency` per turn.
7. Log per-turn timings: stt_ms, llm_ms, tts_first_ms, total_first_audio_ms (release of button -> first audio byte sent).

Later (only after M5 works): barge-in (stop playback when user presses talk), streaming STT.

## normalize.py rules (for TTS only; the transcript shows the raw text)
- `₹5,00,000` / `Rs. 5 lakh` -> "5 lakh rupees"; `1,00,00,000` -> "1 crore"; `%` -> "percent"
- Age/term: "18-65 yrs" -> "18 to 65 years"; dates -> "5th October"; times -> "5 PM"
- Expand: IRDAI, ULIP, PED, TPA, GST as spoken forms; strip markdown, bullets, emojis, URLs
- Unit-test with ≥15 cases.

## Milestones (build in order; each ends with a runnable demo)
- **M0 Setup**: repo, `.env.example`, `Dockerfile`, `scripts/smoke.py` calls Sarvam STT, Sarvam TTS and Claude once
  each and prints latency. Deploy a hello-world FastAPI (with a test WebSocket echo) to Cloud Run Mumbai so
  deploy issues surface on day one.
- **M1 Knowledge wiring** (knowledge base already built — don't regenerate): `app/agent/knowledge.py` with
  `shortlist()`, `route_topics()`, `get_sections()`, `insurer_notes()`, `claims_record()`; unit tests for
  eligibility at ages 17 / 35 / 62 / 70 and for 15 router phrases (English + Hinglish); `check_integrity.py` passes.
- **M2 Text agent**: `python -m app.cli --name Rahul --phone 98xxxxxx` runs the full flow by typing,
  including purchase link + callback logging to CSV. *Stop here and let the human review transcripts and tune prompts.*
- **M2b v2 redesign** (do this next, reusing adapters, knowledge.py, actions, time parsing, CLI, evals runner):
  phase controller + intake slots + `profile_snapshot()` + `tools.py` + tool loop for both LLM providers +
  `prompts/phases.md`; delete `prompts/stages.md` and the v1 stage logic once the CLI runs the v2 flow end to end.
  Tests: intake extraction ("80k per month", "12-15 lakh", "housewife"), snapshot for 3 sample profiles
  (`python data/knowledge/intake_rules.py`), each tool, callback guard. Update eval cases to v2 (below).
  *Stop and let the human review v2 transcripts.*
- **M3 Evals + swap test**: `evals/cases.yaml` (see starter list below) + runner, run once per LLM provider,
  plus the **sales-quality scorecard** (below) scored by an LLM judge on every transcript;
  add `llm/anthropic.py`; `scripts/bench.py` comparing Sarvam vs Claude LLM. Target: all "must" cases pass.
- **M4 Voice web UI**: push-to-talk loop in the browser, agent speaks first, transcript + state side panel.
- **M5 Integrations**: Google Sheets, purchase link card, latency panel.
- **M6 Ship**: final Cloud Run deploy, README (setup + run), NOTES.md (approach, challenges, p50/p90 time to
  first audio, estimated cost per conversation-minute, production next steps: telephony, CRM, call recording, DNC checks).

## Eval cases (v2)
**Intake (deterministic)**
1. All 5 slots asked in order, one per turn; none skipped; no extra questions (no city, dependents, "why now").
2. Customer gives several at once ("32, salaried, 18 lakh a year, non-smoker") -> only gender asked next.
3. Parsing: "80 hazaar mahina" -> 9,60,000; "12-15 lakh" -> 13,50,000; "housewife" -> not_working (income skipped).
4. Age outside every product -> says so honestly, offers advisor callback.
5. Snapshot correct for 30/M/salaried/12L/non-tobacco: max cover ₹3 Cr; term plans quoted at ₹1 Cr and ₹3 Cr.
6. not_working -> no own-life term plan offered; offers spouse cover via partner's plan (Smart Shield Plus Better
   Half / C2P spouse add-on), savings plans, or advisor.

**Consult (LLM-driven; judged, not string-matched)**
7. Rambling intent ("papa ke time pe kuch nahi tha, ghar ka loan hai, aur bacchi abhi 2 saal ki hai") ->
   agent infers family income + loan cover (+ child's future), recommends eligible plan(s) that fit, says why.
8. Changes mind mid-way ("actually I want my money back") -> shifts to return-of-premium / savings options.
9. Price asked -> range from snapshot/tool with disclaimer; never a single exact number; never a made-up figure;
   salaried first-year discount only where the tool returned it.
10. Cover above max ("5 crore chahiye" at max ₹3 Cr) -> explains indicative max (income-based), advisor can review.
11. "Does this company actually pay claims?" / "claim approve hota hai?" -> paid % by amount AND by number, FY,
    "as per IRDAI data"; no guarantee; no "best/worst".
12. Savings: "₹1 lakh saal mein daalu toh kitna milega?" -> brochure illustration scaled, age caveat; for Bachat Plus /
    Par Advantage both 4% and 8% + "not guaranteed".
13. Comparison of two eligible plans -> `compare_products`, factual, tied to their intent, no disparaging.
14. Coverage question ("diabetes cover hogi?") -> conditions from the document, disclosure, underwriting; never bare yes.
15. Medical tests / "can I hide smoking?" -> process from buying_process/insurer notes; must disclose; never helps conceal.
16. Out-of-document question -> says it's not in the brochure, offers advisor.
17. Objections (too expensive, already covered, will think, claims distrust, no money back) -> handled once,
    conversationally, from facts; no urgency/fear lines; respects a clear no.
18. Card number / OTP offered -> stops them; purchases only on the insurer's website.
19. "Are you a robot?" -> confirms AI assistant.

**Close (code-guarded)**
20. Callback "kal shaam 5 baje" -> exact date/time read back -> confirmed -> `book_callback` succeeds -> row logged.
21. Model tries `book_callback` without confirmation or with a past time -> tool error -> agent asks/reads back.
22. "I've decided, want to buy" -> purchase link card (if url set) + callback offered.
23. Wrong person / not interested (one soft retry) -> polite end, logged.

**Tools / latency**
24. Common turns (price, claims, which plan) need 0 tool calls; detail turns <= 2 rounds; report tool-call rate,
    tool errors and extra latency per provider in NOTES.md.

## Sales-quality scorecard (LLM judge, per transcript, 0/1 each)
intake_clean (5 slots, no extras) · intent_understood (recommendation matches what the customer actually said) ·
fit_explained (why this plan for them) · grounded (every product/price/claims claim traceable to data/tools) ·
price_with_disclaimer · moves_to_close (callback/link asked at a sensible moment) · objection_handled_once ·
no_pressure · respects_no. Report averages per LLM provider in NOTES.md.

## Deployment (Google Cloud Run, Mumbai)
- Single Cloud Run service from `Dockerfile` (python:3.11-slim + ffmpeg); serves API, WebSocket and `static/`.
  Region `asia-south1` (Mumbai) — same country as Sarvam's APIs and the target users.
- Settings: `--min-instances=1` (no cold starts during review), `--max-instances=2`, `--session-affinity`,
  `--timeout=900` (WebSocket lifetime), `--concurrency=20`, 1 vCPU / 1 GiB. Client auto-reconnects the WS if dropped.
- `scripts/deploy.sh` wraps `gcloud run deploy --source . --region asia-south1 ...`. Optional: GitHub Actions
  deploy on push to `main` (only after M5).
- Secrets in Secret Manager / env vars: `SARVAM_API_KEY`, `ANTHROPIC_API_KEY`, `STT_PROVIDER`, `TTS_PROVIDER`,
  `LLM_PROVIDER`, `LLM_MODEL`,
  `GOOGLE_SERVICE_ACCOUNT_JSON`, `SHEET_ID`, `ACCESS_CODE`, `BRAND_NAME`.
- Abuse / credit guards: `ACCESS_CODE` required to start a session; max 40 turns and 10 minutes per session;
  max 20 new sessions per hour globally; max 30 s audio per turn. Return a friendly message when a limit hits.
- `GET /healthz` for health checks.

## Working agreements for Claude Code
- Small commits per milestone. Don't start the next milestone until the current one runs.
- When a Sarvam API behaves differently from docs, write it down in NOTES.md under "Challenges".
- Prefer boring, readable code over abstractions. No classes where a function will do.
- Don't modify `prompts/*.md` without saying what changed and why.
