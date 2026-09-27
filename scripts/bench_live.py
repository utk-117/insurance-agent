"""Time to first audio on the DEPLOYED service: N scripted sessions over the real WebSocket, with spoken customer
turns (TTS-generated clips, so STT runs too). Prints p50/p90 per stage.

  python scripts/bench_live.py --url https://<service>.run.app -n 5      # ACCESS_CODE read from .env
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import statistics
import sys

import httpx
import websockets
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.adapters.base import get_tts  # noqa: E402

TURNS = ["Yes, this is Rahul speaking.", "Sure, go ahead.",
         "I'm thirty years old, male, salaried, twelve lakh a year, and I have never smoked.",
         "I want my wife and son to be protected if something happens to me.",
         "What would one crore cover cost me?", "Does HDFC Life actually pay claims?"]
STAGES = ["stt_ms", "llm_ms", "tts_first_ms", "total_first_audio_ms"]


async def turn(ws, payload) -> dict:
    await ws.send(payload)
    while True:  # the server sends `latency` after the turn's last audio chunk
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
        if m["type"] == "latency":
            return m
        if m["type"] in ("end", "error"):
            return {}


async def session(url, code, clips):
    host = url.split("://", 1)[1].rstrip("/")
    r = httpx.post(f"{url}/api/session", json={"name": "Rahul", "phone": "9876543210", "access_code": code}, timeout=30)
    r.raise_for_status()
    out = []
    async with websockets.connect(f"wss://{host}/ws/{r.json()['session_id']}", max_size=None) as ws:
        out.append(dict(await turn(ws, json.dumps({"type": "hello", "mime": "audio/mpeg"})), kind="greeting"))
        for clip in clips:
            out.append(dict(await turn(ws, clip), kind="voice"))
        await ws.send(json.dumps({"type": "hangup"}))
    return out


def pct(v, p):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * p
    return round(v[int(k)] + (v[min(int(k) + 1, len(v) - 1)] - v[int(k)]) * (k - int(k)))


async def main(a):
    code = dotenv_values(ROOT / ".env")["ACCESS_CODE"]
    clips = [(await get_tts().speak(t, "en-IN"))["audio"] for t in TURNS]
    rows = []
    failed = 0
    for i in range(a.n):
        try:
            rows += await session(a.url, code, clips)
            print(f"  session {i + 1}/{a.n} done", flush=True)
        except Exception as e:  # a dropped connection is a result too: count it, keep going
            failed += 1
            print(f"  session {i + 1}/{a.n} FAILED: {type(e).__name__}: {e}", flush=True)
    voice = [r for r in rows if r.get("kind") == "voice"]
    print(f"\n{a.url}  ({a.n} sessions, {failed} failed, {len(voice)} voice turns)")
    print(f"{'stage':<22}{'p50':>8}{'p90':>8}  ms")
    for s in STAGES:
        print(f"{s:<22}{pct([r.get(s) for r in voice], .5)!s:>8}{pct([r.get(s) for r in voice], .9)!s:>8}")
    g = [r.get("total_first_audio_ms") for r in rows if r.get("kind") == "greeting"]
    print(f"{'greeting first audio':<22}{pct(g, .5)!s:>8}{pct(g, .9)!s:>8}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://insurance-voice-agent-877719973605.asia-south1.run.app")
    ap.add_argument("-n", type=int, default=5)
    asyncio.run(main(ap.parse_args()))
