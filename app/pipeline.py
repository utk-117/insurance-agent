"""One voice turn: audio -> STT -> controller -> normalize -> TTS (sentences in parallel) -> client, in order.

`send` is an async callable that takes a JSON-able dict (the WebSocket sender in main.py).
Timings per turn: stt_ms, llm_ms, tts_first_ms, total_first_audio_ms (audio received -> first audio sent).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import shutil
import time

from app.adapters.base import ProviderError, get_stt, get_tts
from app.agent import controller, knowledge
from app.agent.state import SessionState
from app.normalize import normalize, split_sentences

log = logging.getLogger("pipeline")


def ms_since(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


async def to_wav(audio: bytes) -> bytes | None:
    """ffmpeg -> 16 kHz mono WAV. Only used if STT rejects the browser's format."""
    if not shutil.which("ffmpeg"):
        return None
    p = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav",
        "pipe:1", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate(audio)
    if p.returncode != 0:
        log.warning("ffmpeg failed: %s", err.decode()[:300])
        return None
    return out


async def transcribe(audio: bytes, mime: str) -> dict:
    """Sarvam accepts webm/ogg/mp4 directly; fall back to ffmpeg WAV on a format error."""
    stt = get_stt()
    try:
        return await stt.transcribe(audio, mime, None)
    except ProviderError as e:
        if "400" not in str(e) and "422" not in str(e):
            raise
        wav = await to_wav(audio)
        if wav is None:
            raise
        log.info("stt retry with ffmpeg wav (%s)", str(e)[:120])
        return await stt.transcribe(wav, "audio/wav", None)


async def speak(send, text: str, lang: str, turn_id: int, t0: float) -> dict:
    """Normalize + split, fire TTS for all chunks at once, send audio in order as each is ready."""
    chunks = split_sentences(normalize(text)) or [normalize(text)]
    tts = get_tts()
    tasks = [asyncio.create_task(tts.speak(c, lang)) for c in chunks if c.strip()]
    first_ms = first_total = None
    for seq, task in enumerate(tasks):
        try:
            r = await task
        except ProviderError as e:
            log.warning("tts chunk %d failed: %s", seq, e)
            continue
        if first_ms is None:
            first_ms, first_total = r["provider_ms"], ms_since(t0)
        await send({"type": "audio", "turn": turn_id, "seq": seq, "mime": r["mime"],
                    "data": base64.b64encode(r["audio"]).decode()})
    await send({"type": "audio_end", "turn": turn_id, "chunks": len(tasks)})
    return {"tts_first_ms": first_ms, "total_first_audio_ms": first_total}


def state_event(state: SessionState) -> dict:
    snap = state.snapshot or {}
    cards = knowledge.cards()
    return {"type": "state", "stage": state.phase.value, "phase": state.phase.value,
            "profile": {k: v for k, v in state.profile.items() if v is not None},
            "max_cover": snap.get("max_cover"),
            "shortlist": [{"id": e["product_id"], "name": cards[e["product_id"]]["name"],
                           "insurer": cards[e["product_id"]]["insurer"],
                           "quotes": [{"sum_assured": q["sum_assured"], "range": q["annual_premium_range"]}
                                      for q in e.get("quotes", [])]} for e in snap.get("eligible", [])],
            "discussed": state.discussed_products, "outcome": state.outcome,
            "callback_time": state.callback_time, "callback_confirmed": bool(state.callback_time),
            "tool_calls": len(state.tool_calls)}


async def greet(state: SessionState, send) -> dict:
    t0 = time.perf_counter()
    res = await controller.start(state)
    await send({"type": "transcript", "role": "agent", "text": res["reply"], "lang": res["reply_language"]})
    await send(state_event(state))
    timing = await speak(send, res["reply"], res["reply_language"], 0, t0)
    lat = {"turn": 0, "stt_ms": None, "llm_ms": res["llm_ms"], **timing}
    await send({"type": "latency", **lat})
    return lat


async def run_turn(state: SessionState, send, turn_id: int, audio: bytes | None = None, mime: str = "audio/webm",
                   text: str | None = None) -> dict:
    """A customer turn from audio (voice) or text (typed fallback). Returns the latency row."""
    t0 = time.perf_counter()
    stt_ms, lang = None, None
    if audio is not None:
        r = await transcribe(audio, mime)
        stt_ms, text, lang = r["provider_ms"], r["text"], r["language_code"]
    text = (text or "").strip()
    if not text:  # silence / nothing recognised: don't spend an LLM call
        reply = controller.snippet("FALLBACK_REPLY")
        await send({"type": "transcript", "role": "agent", "text": reply, "lang": "en-IN"})
        timing = await speak(send, reply, "en-IN", turn_id, t0)
        return {"turn": turn_id, "stt_ms": stt_ms, "llm_ms": 0, **timing, "empty": True}

    await send({"type": "transcript", "role": "user", "text": text, "lang": lang})
    filler = {"sent": False}

    async def on_tool_round(rnd, llm_ms):
        # a tool round means another LLM call: say a short filler if the customer has already waited > 1.5 s
        if filler["sent"] or ms_since(t0) < 1500:
            return
        filler["sent"] = True
        hi = controller.customer_language(state) != "English"
        line = controller.snippet("FILLER_HI" if hi else "FILLER_EN")
        asyncio.create_task(speak(send, line, "hi-IN" if hi else "en-IN", turn_id - 0.5, time.perf_counter()))

    res = await controller.handle_turn(state, text, lang, on_tool_round=on_tool_round)
    await send({"type": "transcript", "role": "agent", "text": res["reply"], "lang": res["reply_language"]})
    for ev in res["events"]:
        await send(ev)
    await send(state_event(state))
    timing = await speak(send, res["reply"], res["reply_language"], turn_id, t0)
    lat = {"turn": turn_id, "stt_ms": stt_ms, "llm_ms": res["llm_ms"], **timing}
    state.latencies[-1].update(lat)  # handle_turn appended {"llm_ms"}; complete the row
    await send({"type": "latency", **lat})
    log.info(json.dumps({"event": "turn_latency", "session": state.session_id, **lat}))
    return lat
