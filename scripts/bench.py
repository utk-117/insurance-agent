"""Latency benchmark: fixed audio clips + fixed turns, N runs per provider combo, through the real voice
pipeline (STT -> controller -> normalize -> first-sentence TTS). Prints p50/p90 per stage and total time to
first audio; raw rows go to data/bench/bench-<timestamp>.csv.

  python scripts/bench.py                                   # sarvam vs anthropic (adapter default model)
  python scripts/bench.py --llm sarvam --llm anthropic:claude-sonnet-5 --llm anthropic:claude-opus-5 -n 5
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import os
import pathlib
import statistics
import sys
import time
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
BENCH = ROOT / "data" / "bench"
os.environ.setdefault("LEADS_CSV", str(BENCH / "bench-leads.csv"))
sys.path.insert(0, str(ROOT))

from app import pipeline  # noqa: E402
from app.adapters.base import get_tts  # noqa: E402
from app.agent import controller  # noqa: E402

PROFILE = {"age": 30, "gender": "male", "employment_type": "salaried", "annual_income_inr": 1_200_000,
           "tobacco": False}
# (name, what the customer says, phase to start from). Clips are spoken once by TTS and cached.
TURNS = [
    ("intake_answer", "I'm salaried, working at a private company.", "INTAKE"),
    ("consult_price", "What would one crore cover cost me roughly?", "CONSULT"),
    ("consult_detail", "What is the free look period for the HDFC Click 2 Protect Supreme?", "CONSULT"),
    ("consult_claims", "Does HDFC Life actually pay claims?", "CONSULT"),
]
STAGES = ["stt_ms", "llm_ms", "tts_first_ms", "total_first_audio_ms"]


async def clip(name: str, text: str) -> tuple:
    BENCH.joinpath("clips").mkdir(parents=True, exist_ok=True)
    path = BENCH / "clips" / f"{name}.mp3"
    if not path.exists():
        r = await get_tts().speak(text, "en-IN")
        path.write_bytes(r["audio"])
    return path.read_bytes(), "audio/mpeg"


def base_state(llm: str, phase: str):
    s = controller.new_session("Rahul", "9876543210", llm)
    s.add("agent", "Hello, I'm Asha, an AI assistant. Am I speaking with Rahul?")
    s.add("user", "Yes, speaking")
    if phase == "INTAKE":
        s.phase = controller.Phase.INTAKE
        s.profile.update(age=30, gender="male")
        s.add("agent", "Are you salaried, self-employed, or not working at the moment?")
    else:
        s.profile = dict(PROFILE)
        controller._finish_intake(s)
        s.consult_opened = True
        s.add("agent", "Based on your profile you can get cover of up to about 3 crore. What would you like it to do?")
        s.add("user", "I want my wife and kid protected if something happens to me.")
        s.add("agent", "That's exactly what a term plan does. Would you like to hear the options?")
    return s


async def run_one(llm: str, turn, audio, mime, template):
    async def send(_msg):
        return None
    state = copy.deepcopy(template)
    t0 = time.perf_counter()
    lat = await pipeline.run_turn(state, send, 1, audio=audio, mime=mime)
    tools = [c["name"] for c in state.tool_calls]
    return {"llm": llm, "turn": turn[0], **{k: lat.get(k) for k in STAGES},
            "tool_calls": len(tools), "tools": " ".join(tools), "wall_ms": round((time.perf_counter() - t0) * 1000),
            "input_tokens": state.metrics["input_tokens"], "output_tokens": state.metrics["output_tokens"]}


def pct(vals, p):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo))


async def main(args):
    clips = {t[0]: await clip(t[0], t[1]) for t in TURNS}
    rows = []
    for llm in args.llm:
        templates = {t[0]: base_state(llm, t[2]) for t in TURNS}
        for i in range(args.n):
            for t in TURNS:
                try:
                    rows.append(await run_one(llm, t, *clips[t[0]], templates[t[0]]))
                except Exception as e:  # keep benchmarking; report the failure
                    print(f"  {llm} {t[0]} run {i}: FAILED {e!r}", flush=True)
            print(f"  {llm}: run {i + 1}/{args.n} done", flush=True)
    BENCH.mkdir(parents=True, exist_ok=True)
    out = BENCH / f"bench-{datetime.now():%Y%m%d-%H%M%S}.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\n{'llm':<32} {'stage':<22} {'p50':>7} {'p90':>7}   (ms, n={args.n} x {len(TURNS)} turns)")
    for llm in args.llm:
        rs = [r for r in rows if r["llm"] == llm]
        for st in STAGES:
            print(f"{llm:<32} {st:<22} {pct([r[st] for r in rs], .5)!s:>7} {pct([r[st] for r in rs], .9)!s:>7}")
        tool_turns = sum(1 for r in rs if r["tool_calls"])
        print(f"{llm:<32} {'turns using tools':<22} {tool_turns}/{len(rs)}   "
              f"avg tokens in/out per turn {statistics.mean(r['input_tokens'] for r in rs):.0f}/"
              f"{statistics.mean(r['output_tokens'] for r in rs):.0f}")
    print(f"\nper turn type, total_first_audio_ms p50:")
    for t in TURNS:
        print(f"  {t[0]:<16} " + "  ".join(f"{llm}: {pct([r['total_first_audio_ms'] for r in rows if r['llm'] == llm and r['turn'] == t[0]], .5)}"
                                          for llm in args.llm))
    print(f"\nraw rows -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="append", help="sarvam | anthropic | anthropic:<model> (repeatable)")
    ap.add_argument("-n", type=int, default=5, help="runs per provider combo")
    a = ap.parse_args()
    a.llm = a.llm or ["sarvam", "anthropic"]
    asyncio.run(main(a))
