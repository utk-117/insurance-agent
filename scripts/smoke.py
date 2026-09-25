"""Call TTS, STT and LLM once each and print latency.

  python scripts/smoke.py              # Sarvam TTS -> Sarvam STT (on that audio) -> Sarvam LLM + Claude
  python scripts/smoke.py --llm sarvam # only one LLM provider
TTS output is fed to STT, so no audio fixture is needed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.adapters import base  # noqa: E402  (loads .env)

TEXT = "Namaste, main Asha hoon. Kya main Rahul se baat kar rahi hoon?"
SCHEMA = {"type": "object", "properties": {"reply": {"type": "string"}, "intent": {"type": "string"}},
          "required": ["reply", "intent"], "additionalProperties": False}
SYSTEM = "You are a test harness. Reply ONLY with a JSON object: {\"reply\": <one short sentence>, \"intent\": \"ok\"}."


def row(name, ms, detail):
    print(f"{name:<22} {str(ms) + ' ms':>9}   {detail}")


async def main(llms):
    ok = True
    audio = None
    if not os.getenv("SARVAM_API_KEY"):
        print("SARVAM_API_KEY not set - skipping Sarvam STT/TTS" + (" and LLM" if "sarvam" in llms else ""))
        llms = [p for p in llms if p != "sarvam"]
    else:
        try:
            r = await base.get_tts().speak(TEXT, "hi-IN")
            audio = r
            row("tts " + base.get_tts().model, r["provider_ms"], f"{len(r['audio'])} bytes {r['mime']}")
        except Exception as e:
            ok = False
            row("tts", "-", f"FAILED {e}")
        if audio:
            try:
                r = await base.get_stt().transcribe(audio["audio"], audio["mime"], None)
                row("stt " + base.get_stt().model, r["provider_ms"], f"[{r['language_code']}] {r['text']}")
            except Exception as e:
                ok = False
                row("stt", "-", f"FAILED {e}")
    for p in llms:
        if p == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY not set - skipping Claude")
            continue
        try:
            llm = base.get_llm(p)
            r = await llm.complete_json(SYSTEM, [{"role": "user", "content": "Say hello to Rahul."}], SCHEMA)
            row(f"llm {llm.model}", r["provider_ms"],
                f"in={r['input_tokens']} out={r['output_tokens']} {r['data']}")
        except Exception as e:
            ok = False
            row(f"llm {p}", "-", f"FAILED {e}")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="append", help="sarvam | anthropic (repeatable; default both)")
    args = ap.parse_args()
    sys.exit(0 if asyncio.run(main(args.llm or ["sarvam", "anthropic"])) else 1)
