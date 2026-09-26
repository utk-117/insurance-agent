"""Text-only chat with the agent (same controller as voice, no audio).

  python -m app.cli --name Rahul --phone 9876543210 [--llm sarvam|anthropic] [--debug]
Type your replies; 'quit' ends the session (logged as dropped). Transcripts go to data/transcripts/.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib

from app.agent import controller, knowledge

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "transcripts"


def show(res, debug, state):
    print(f"\nAsha: {res['reply']}")
    for ev in res["events"]:
        if ev["type"] == "purchase_link":
            print(f"   [card] {ev['insurer']} {ev['name']} -> {ev['url']}")
        elif ev["type"] == "callback_booked":
            print(f"   [callback booked] {ev['callback_time_ist']}")
        elif ev["type"] == "end":
            print(f"   [end] outcome={ev['outcome']}")
    if debug:
        p = {k: v for k, v in state.profile.items() if v is not None}
        snap = state.snapshot
        head = f" | max cover {snap['max_cover']} | eligible {len(snap['eligible'])}" if snap else ""
        tools = " | tools " + ", ".join(f"{c['name']}{'' if c['ok'] else '(ERR)'}" for c in res.get("tool_calls", [])) \
            if res.get("tool_calls") else ""
        print(f"   ({res['phase']} | llm {res['llm_ms']} ms | {res['reply_language']} | profile "
              f"{json.dumps(p, ensure_ascii=False)}{head}{tools})")


async def main(args):
    state = controller.new_session(args.name, args.phone, args.llm)
    show(await controller.start(state), args.debug, state)
    while True:
        try:
            text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            text = "quit"
        if not text:
            continue
        if text.lower() in ("quit", "exit"):
            break
        res = await controller.handle_turn(state, text)
        show(res, args.debug, state)
        if res["ended"]:
            break
    path = await controller.finish(state)
    OUT.mkdir(parents=True, exist_ok=True)
    tfile = OUT / f"{state.session_id}.json"
    tfile.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=1))
    print(f"\n[session {state.session_id}] outcome={state.outcome} | summary: {state.summary}")
    print(f"lead row -> {path}\ntranscript -> {tfile}\nmetrics: {state.metrics}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Utkarsh")
    ap.add_argument("--phone", default="9876543210")
    ap.add_argument("--llm", default=None, help="sarvam | anthropic (default: LLM_PROVIDER)")
    ap.add_argument("--debug", action="store_true", help="show stage/profile/latency and log lines")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO if a.debug else logging.WARNING, format="   %(name)s %(message)s")
    knowledge.cards()
    asyncio.run(main(a))
