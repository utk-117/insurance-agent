"""Run evals/cases.yaml through the text controller, check expectations in code, and score every transcript
with an LLM judge (assertions + sales-quality scorecard).

  python -m evals.run_evals                       # all cases, LLM_PROVIDER (default sarvam)
  python -m evals.run_evals --llm anthropic       # swap test
  python -m evals.run_evals --only robot,wrong_person --concurrency 2
Results: evals/results/<provider>-<timestamp>.json (+ the eval leads CSV next to it).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import pathlib
import re
import sys
import time
import uuid
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evals" / "results"
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
os.environ.setdefault("LEADS_CSV", str(RESULTS / f"leads-{STAMP}.csv"))  # keep eval rows out of data/leads.csv
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402  (installed with uvicorn[standard])

from app.adapters.base import LLMParseError, ProviderError  # noqa: E402
from app.adapters.llm.sarvam import SarvamLLM  # noqa: E402
from app.agent import controller, knowledge  # noqa: E402

PREFIX_LEADS = {"intake_hi_f": "Sunita"}
SCORE_KEYS = ["intake_clean", "intent_understood", "fit_explained", "grounded", "price_with_disclaimer",
              "moves_to_close", "objection_handled_once", "no_pressure", "respects_no"]
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "assertions": {"type": "array", "items": {"type": "object", "properties": {
            "i": {"type": "integer"}, "pass": {"type": "boolean"}, "why": {"type": "string"}},
            "required": ["i", "pass", "why"]}},
        "scorecard": {"type": "object", "properties": {k: {"type": ["integer", "null"]} for k in SCORE_KEYS}},
    },
    "required": ["assertions", "scorecard"],
}


def load_cases():
    data = yaml.safe_load((ROOT / "evals" / "cases.yaml").read_text())
    return data["prefixes"], data["cases"]


def expand(turns, prefixes):
    out = []
    for t in turns:
        if isinstance(t, str) and t.startswith("$"):
            out += expand(prefixes[t[1:]], prefixes)
        else:
            out.append(t)
    return out


def judge_llm():
    llm = SarvamLLM()
    llm.model = os.getenv("JUDGE_MODEL", "sarvam-105b")
    llm.reasoning = os.getenv("JUDGE_REASONING", "low")
    llm.max_tokens = int(os.getenv("JUDGE_MAX_TOKENS", "16000"))
    llm.client = __import__("httpx").AsyncClient(timeout=240)
    return llm


# ---- playing conversations --------------------------------------------------------------------

class Runner:
    def __init__(self, provider, prefixes):
        self.provider, self.prefixes = provider, prefixes
        self.prefix_cache, self.locks = {}, {}

    async def play(self, state, turns, events):
        for t in turns:
            if state.phase.value == "END":
                break
            res = await controller.handle_turn(state, t)
            events += res["events"]

    async def prefix_state(self, name):
        lock = self.locks.setdefault(name, asyncio.Lock())
        async with lock:
            if name not in self.prefix_cache:
                state = controller.new_session(PREFIX_LEADS.get(name, "Rahul"), "9876543210", self.provider)
                await controller.start(state)
                events = []
                await self.play(state, expand(self.prefixes[name], self.prefixes), events)
                self.prefix_cache[name] = (state, events)
                snap = state.snapshot or {}
                print(f"  prefix ${name}: phase={state.phase.value} profile={state.profile} "
                      f"max_cover={snap.get('max_cover')}", flush=True)
        state, events = self.prefix_cache[name]
        state = copy.deepcopy(state)
        state.session_id = uuid.uuid4().hex[:12]
        return state, list(events)

    async def run_case(self, case):
        turns = case["turns"]
        first = turns[0] if turns and isinstance(turns[0], str) and turns[0].startswith("$") else None
        if first:
            state, events = await self.prefix_state(first[1:])
            rest = expand(turns[1:], self.prefixes)
        else:
            state = controller.new_session(case.get("lead", "Rahul"), "9876543210", self.provider)
            await controller.start(state)
            events, rest = [], expand(turns, self.prefixes)
        t0 = time.perf_counter()
        await self.play(state, rest, events)
        state.summary = state.summary or "(eval run)"  # skip the summary LLM call
        state.final_phase = state.phase.value  # finish() always sets END; checks need where the conversation was
        await controller.finish(state)
        return state, events, round(time.perf_counter() - t0, 1)


# ---- checks -----------------------------------------------------------------------------------

def agent_replies(state):
    return [t["text"] for t in state.transcript if t["role"] == "agent"]


def reply_to_turn(state, k):
    """Agent reply to the k-th customer message (-1 = last)."""
    pairs, tr = [], state.transcript
    for i, t in enumerate(tr):
        if t["role"] == "user" and i + 1 < len(tr) and tr[i + 1]["role"] == "agent":
            pairs.append(tr[i + 1]["text"])
    return pairs[k] if pairs else ""


def check(case, state, events):
    ex, fails = case.get("expect") or {}, []
    ev_types = [e["type"] for e in events]
    snap = state.snapshot or {}
    eligible = [e["product_id"] for e in snap.get("eligible", [])]
    if "outcome" in ex and state.outcome != ex["outcome"]:
        fails.append(f"outcome={state.outcome} want {ex['outcome']}")
    phase = getattr(state, "final_phase", state.phase.value)
    if "ended" in ex and (phase == "END") != ex["ended"]:
        fails.append(f"ended={phase == 'END'} want {ex['ended']}")
    if "phase_in" in ex and phase not in ex["phase_in"]:
        fails.append(f"phase={phase} want one of {ex['phase_in']}")
    for f, v in (ex.get("profile") or {}).items():
        if state.profile.get(f) != v:
            fails.append(f"profile.{f}={state.profile.get(f)!r} want {v!r}")
    if "max_cover" in ex and snap.get("max_cover") != ex["max_cover"]:
        fails.append(f"max_cover={snap.get('max_cover')} want {ex['max_cover']}")
    for pid in ex.get("eligible_has") or []:
        if pid not in eligible:
            fails.append(f"{pid} not eligible")
    for pid in ex.get("eligible_lacks") or []:
        if pid in eligible:
            fails.append(f"{pid} unexpectedly eligible")
    if ex.get("no_term_plans") and any("quotes" in e for e in snap.get("eligible", [])):
        fails.append("term plans offered to a non-earner")
    for e in ex.get("events") or []:
        if e not in ev_types:
            fails.append(f"missing event {e}")
    if "callback_hour" in ex:
        hour = datetime.fromisoformat(state.callback_time).hour if state.callback_time else None
        if hour != ex["callback_hour"]:
            fails.append(f"callback hour={hour} want {ex['callback_hour']}")
    for pat in ex.get("no_regex") or []:
        for r in agent_replies(state):
            if re.search(pat, r):
                fails.append(f"forbidden /{pat}/ in: {r[:120]}")
                break
    if "reply_regex" in ex:
        rr = ex["reply_regex"]
        reply = reply_to_turn(state, rr.get("turn", -1))
        if not any(re.search(p, reply) for p in rr["any"]):
            fails.append(f"reply lacks {rr['any']}: {reply[:120]}")
    if "tool_used" in ex and not any(c["name"] == ex["tool_used"] and c["ok"] for c in state.tool_calls):
        fails.append(f"tool {ex['tool_used']} never succeeded ({[c['name'] for c in state.tool_calls]})")
    if "no_tools_on_turn" in ex and state.turn_log:
        tl = state.turn_log[ex["no_tools_on_turn"]]
        if tl["tool_calls"]:
            fails.append(f"common turn used tools: {tl['tool_calls']}")
    if "intake_questions" in ex:
        # every INTAKE->INTAKE turn is one intake question asked; the answer to the last one leaves INTAKE
        n = sum(1 for tl in state.turn_log if tl["phase_in"] == "INTAKE" and tl["phase_out"] == "INTAKE")
        if n != ex["intake_questions"]:
            fails.append(f"intake took {n} questions, want {ex['intake_questions']}")
    fb = sum(1 for tl in state.turn_log if tl.get("fallback"))
    if fb:
        fails.append(f"{fb} fallback repl{'y' if fb == 1 else 'ies'} (LLM parse/provider failure)")
    return fails


# ---- judge ------------------------------------------------------------------------------------

def source_documents(state):
    """What the agent could see: cards, snapshot, claims, and re-run results of the info tools it called."""
    results = []
    for c in state.tool_calls:
        if c["name"] == "get_product_info" and c["ok"]:
            for sec in knowledge.get_sections(c["args"]["product_id"], c["args"].get("topics", [])):
                results.append(f"### get_product_info {c['args']['product_id']} — {sec['topic']}\n"
                               f"{(sec.get('text') or 'NOT IN BROCHURE')[:4000]}")
        elif c["name"] == "get_savings_illustration" and c["ok"]:
            ill = knowledge.intake_rules().savings_illustration(c["args"]["product_id"], int(c["args"]["annual_premium"]))
            results.append(f"### get_savings_illustration {json.dumps(c['args'])}\n{json.dumps(ill, ensure_ascii=False)}")
        elif c["name"] in ("get_process_info", "compare_products", "get_claims_record") and c["ok"]:
            results.append(f"### {c['name']} {json.dumps(c['args'])} (ok)")
    if state.quoted:
        results.append("### premium estimates returned\n" + json.dumps(state.quoted))
    snap = controller._snapshot_text(state) if state.snapshot else "(intake not finished)"
    return "\n\n".join([
        "## SNAPSHOT (code: eligibility, max cover, indicative price ranges)\n" + snap,
        "## CLAIMS RECORD\n" + controller._claims_text(state),
        "## TOOL RESULTS\n" + ("\n\n".join(results) or "(none)"),
        "## PRODUCT CARDS\n" + json.dumps(knowledge.prompt_cards(), ensure_ascii=False),
        "## PROCESS KNOWLEDGE\n" + knowledge.buying_process(),
    ])


def transcript_text(state):
    lines, k = [], 0
    for t in state.transcript:
        if t["role"] == "user":
            lines.append(f"CUSTOMER: {t['text']}")
        else:
            tl = state.turn_log[k - 1] if 0 < k <= len(state.turn_log) else None
            tag = (f" [{tl['phase_in']}->{tl['phase_out']}"
                   + (f", tools={[c['name'] for c in tl['tool_calls']]}" if tl["tool_calls"] else "") + "]") if tl \
                else " [GREET]"
            lines.append(f"AGENT{tag}: {t['text']}")
            k += 1
    return "\n".join(lines)


async def judge(llm, case, state):
    assertions = case.get("judge") or []
    user = (f"# SOURCE DOCUMENTS\n{source_documents(state)}\n\n# TRANSCRIPT\n{transcript_text(state)}\n\n"
            f"# FINAL OUTCOME: {state.outcome}\n\n# ASSERTIONS\n"
            + ("\n".join(f"{i}. {a}" for i, a in enumerate(assertions)) or "(none — score the scorecard only)"))
    try:
        r = await llm.complete_json(controller.md_sections("judge.md")["SYSTEM"],
                                    [{"role": "user", "content": user}], JUDGE_SCHEMA)
    except (LLMParseError, ProviderError) as e:
        return [{"i": i, "pass": False, "why": f"judge error: {str(e)[:200]}", "text": a} for i, a in enumerate(assertions)], {}
    got = {a.get("i"): a for a in r["data"].get("assertions", []) if isinstance(a, dict)}
    res = [dict(got.get(i, {"pass": False, "why": "judge skipped it"}), i=i, text=a) for i, a in enumerate(assertions)]
    sc = {k: v for k, v in (r["data"].get("scorecard") or {}).items() if k in SCORE_KEYS and v in (0, 1)}
    return res, sc


# ---- main -------------------------------------------------------------------------------------

async def main(args):
    prefixes, cases = load_cases()
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    provider = args.llm or os.getenv("LLM_PROVIDER", "sarvam")
    runner, jllm = Runner(args.llm, prefixes), judge_llm()
    sem = asyncio.Semaphore(args.concurrency)
    results = []

    async def one(case):
        async with sem:
            try:
                state, events, secs = await runner.run_case(case)
            except Exception as e:  # keep going; report as failure
                results.append({"id": case["id"], "must": case.get("must", False), "name": case["name"],
                                "pass": False, "fails": [f"crashed: {e!r}"], "judge": [], "scorecard": {}})
                print(f"  CRASH {case['id']}: {e!r}", flush=True)
                return
            fails = check(case, state, events)
            try:
                jres, sc = await judge(jllm, case, state) if not args.no_judge else ([], {})
            except Exception as e:
                jres = [{"i": i, "pass": False, "why": f"judge crashed: {e!r}"[:200], "text": a}
                        for i, a in enumerate(case.get("judge") or [])]
                sc = {}
            fails += [f"judge: {a['text']} — {a.get('why')}" for a in jres if not a.get("pass")]
            results.append({"id": case["id"], "must": case.get("must", False), "name": case["name"],
                            "pass": not fails, "fails": fails, "judge": jres, "scorecard": sc,
                            "outcome": state.outcome, "phase": state.final_phase, "secs": secs,
                            "metrics": state.metrics, "tool_calls": state.tool_calls,
                            "transcript": transcript_text(state)})
            print(f"  {'PASS' if not fails else 'FAIL'} {case['id']} ({secs}s)", flush=True)

    plain = [c for c in cases if not c.get("patch_purchase_urls")]
    patched = [c for c in cases if c.get("patch_purchase_urls")]
    print(f"Running {len(cases)} cases with LLM={provider} (judge {jllm.model})", flush=True)
    await asyncio.gather(*(one(c) for c in plain))
    if patched:  # cards are shared module state, so these run alone
        saved = {pid: c.get("purchase_url") for pid, c in knowledge.cards().items()}
        for pid, c in knowledge.cards().items():
            c["purchase_url"] = c.get("purchase_url") or f"https://example.com/test/{pid}"
        try:
            for c in patched:
                await one(c)
        finally:
            for pid, url in saved.items():
                knowledge.cards()[pid]["purchase_url"] = url

    order = {c["id"]: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order[r["id"]])
    print("\n" + "=" * 100)
    for r in results:
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {'must' if r['must'] else '    '}  {r['name']}")
        for f in r["fails"]:
            print(f"        - {f[:220]}")
    musts = [r for r in results if r["must"]]
    print("=" * 100)
    print(f"must: {sum(r['pass'] for r in musts)}/{len(musts)} passed · all: {sum(r['pass'] for r in results)}/{len(results)}")
    avg = {}
    for k in SCORE_KEYS:
        vals = [r["scorecard"][k] for r in results if k in r.get("scorecard", {})]
        avg[k] = round(sum(vals) / len(vals), 2) if vals else None
    scored = [v for v in avg.values() if v is not None]
    print("scorecard: " + " · ".join(f"{k}={v}" for k, v in avg.items())
          + (f" · mean={round(sum(scored) / len(scored), 2)}" if scored else ""))
    tot = {m: sum((r.get("metrics") or {}).get(m) or 0 for r in results)
           for m in ("llm_calls", "tool_rounds", "parse_fallbacks")}
    calls = [c for r in results for c in r.get("tool_calls", [])]
    tot["tool_calls"] = len(calls)
    tot["tool_errors"] = sum(not c["ok"] for c in calls)
    print(f"metrics (summed per case; shared prefix turns counted in each): {tot}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{provider}-{STAMP}.json"
    out.write_text(json.dumps({"provider": provider, "judge": jllm.model, "scorecard": avg, "metrics": tot,
                               "results": results}, ensure_ascii=False, indent=1))
    print(f"results -> {out}")
    return all(r["pass"] for r in musts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default=None, help="sarvam | anthropic (default LLM_PROVIDER)")
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--no-judge", action="store_true", help="code checks only (no judge LLM calls)")
    a = ap.parse_args()
    sys.exit(0 if asyncio.run(main(a)) else 1)
