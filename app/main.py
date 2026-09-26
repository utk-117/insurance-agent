"""FastAPI app: POST /api/session, WS /ws/{session_id}, static UI, /healthz, /ws/echo.

WebSocket protocol
  client -> server  {"type":"hello","mime":"audio/webm"}   first message (also after a reconnect)
                    <binary>                              one push-to-talk recording = one turn
                    {"type":"text","text":"..."}           typed turn (fallback / testing)
                    {"type":"hangup"}
  server -> client  transcript · state · audio {turn,seq,mime,data} · audio_end · latency ·
                    purchase_link_sent · callback_booked · end · error · notice
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import time
from collections import deque

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

from app import pipeline, sheets  # noqa: E402
from app.adapters.base import ProviderError  # noqa: E402
from app.agent import controller  # noqa: E402

log = logging.getLogger("main")
ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

MAX_TURNS = int(os.getenv("MAX_TURNS", "40"))
MAX_SESSION_S = int(os.getenv("MAX_SESSION_SECONDS", "600"))
MAX_SESSIONS_PER_HOUR = int(os.getenv("MAX_SESSIONS_PER_HOUR", "20"))
MAX_AUDIO_BYTES = int(os.getenv("MAX_AUDIO_BYTES", str(1_500_000)))  # ~30 s of browser opus is ~150 KB
RECONNECT_GRACE_S = 90

app = FastAPI(title="Insurance voice agent")
SESSIONS: dict = {}
_created: deque = deque()


class Session:
    def __init__(self, state):
        self.state = state
        self.created = time.time()
        self.turns = 0
        self.greeted = False
        self.finished = False
        self.lock = asyncio.Lock()
        self.ws = None
        self.mime = "audio/webm"
        self.reaper = None


class NewSession(BaseModel):
    name: str
    phone: str
    access_code: str


@app.get("/health")  # Cloud Run's front end reserves paths ending in "z" (/healthz 404s there)
@app.get("/healthz")
def healthz():
    return {"ok": True, "stt": os.getenv("STT_PROVIDER", "sarvam"), "tts": os.getenv("TTS_PROVIDER", "sarvam"),
            "llm": os.getenv("LLM_PROVIDER", "sarvam"), "sessions": len(SESSIONS),
            "leads": sheets.status()["leads"], "sheets_errors": sheets.status()["sheets_errors"]}


@app.post("/api/session")
def new_session(body: NewSession):
    code = os.getenv("ACCESS_CODE")
    if not code or body.access_code.strip() != code:
        raise HTTPException(403, "Wrong access code.")
    name, phone = body.name.strip()[:40], "".join(ch for ch in body.phone if ch.isdigit() or ch == "+")[:15]
    if not name or len(phone) < 8:
        raise HTTPException(400, "Please enter a name and a valid phone number.")
    now = time.time()
    while _created and now - _created[0] > 3600:
        _created.popleft()
    if len(_created) >= MAX_SESSIONS_PER_HOUR:
        raise HTTPException(429, "The demo is busy right now (hourly session limit). Please try again later.")
    _created.append(now)
    state = controller.new_session(name, phone)
    SESSIONS[state.session_id] = Session(state)
    log.info(json.dumps({"event": "session_created", "session": state.session_id}))
    return {"session_id": state.session_id, "max_turns": MAX_TURNS, "max_seconds": MAX_SESSION_S}


async def finalize(s: Session, reason: str):
    if s.finished:
        return
    s.finished = True
    try:
        await controller.finish(s.state)
    except Exception:
        log.exception("finish failed")
    # full record to logs (Cloud Logging) - transcripts on Cloud Run's disk don't survive restarts
    log.info(json.dumps({"event": "session_end", "reason": reason, "session": s.state.session_id,
                         "state": s.state.to_dict()}, ensure_ascii=False, default=str))


async def reap_later(sid: str):
    await asyncio.sleep(RECONNECT_GRACE_S)
    s = SESSIONS.get(sid)
    if s and s.ws is None:
        await finalize(s, "disconnected")
        SESSIONS.pop(sid, None)


@app.websocket("/ws/echo")
async def ws_echo(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("text") is not None:
                await ws.send_text(msg["text"])
            elif msg.get("bytes") is not None:
                await ws.send_bytes(msg["bytes"])
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/{session_id}")
async def ws_session(ws: WebSocket, session_id: str):
    await ws.accept()
    s = SESSIONS.get(session_id)
    if not s or s.finished:
        await ws.send_json({"type": "error", "fatal": True, "message": "This session has ended. Please start a new one."})
        await ws.close()
        return
    if s.reaper:
        s.reaper.cancel()
        s.reaper = None
    s.ws = ws

    async def send(msg: dict):
        if s.ws is ws:
            try:
                await ws.send_json(msg)
            except Exception:  # client went away mid-turn; keep the turn's state changes
                pass

    async def end_limit():
        reply = controller.snippet("LIMIT_REACHED")
        await send({"type": "transcript", "role": "agent", "text": reply, "lang": "en-IN"})
        await pipeline.speak(send, reply, "en-IN", s.turns + 1, time.perf_counter())
        await finalize(s, "limit")
        await send({"type": "end", "outcome": s.state.outcome})

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data, text = msg.get("bytes"), msg.get("text")
            if text is not None:
                try:
                    j = json.loads(text)
                except ValueError:
                    continue
                if j.get("type") == "hello":
                    s.mime = j.get("mime") or s.mime
                    async with s.lock:
                        if not s.greeted:
                            s.greeted = True
                            await pipeline.greet(s.state, send)
                        else:  # reconnect: replay transcript + state, no new greeting
                            for t in s.state.transcript:
                                await send({"type": "transcript", "role": t["role"], "text": t["text"],
                                            "lang": t["lang"], "replay": True})
                            await send(pipeline.state_event(s.state))
                    continue
                if j.get("type") == "hangup":
                    await finalize(s, "hangup")
                    await send({"type": "end", "outcome": s.state.outcome})
                    break
                if j.get("type") != "text" or not str(j.get("text", "")).strip():
                    continue
            elif data is not None and len(data) > MAX_AUDIO_BYTES:
                await send({"type": "notice", "message": "That recording was too long. Please keep turns under 30 seconds."})
                continue

            async with s.lock:
                if s.finished:
                    await send({"type": "end", "outcome": s.state.outcome})
                    continue
                if s.turns >= MAX_TURNS or time.time() - s.created > MAX_SESSION_S:
                    await end_limit()
                    continue
                s.turns += 1
                await send({"type": "thinking"})
                try:
                    if data is not None:
                        await pipeline.run_turn(s.state, send, s.turns, audio=data, mime=s.mime)
                    else:
                        await pipeline.run_turn(s.state, send, s.turns, text=str(j["text"])[:1000])
                except ProviderError as e:
                    log.warning("turn failed: %s", e)
                    await send({"type": "error", "message": "Sorry, the speech service had a hiccup. Please try again."})
                if s.state.stage.value == "END":
                    s.finished = True  # controller.finish already logged the lead row
                    log.info(json.dumps({"event": "session_end", "reason": "completed",
                                         "session": s.state.session_id, "state": s.state.to_dict()},
                                        ensure_ascii=False, default=str))
    except WebSocketDisconnect:
        pass
    finally:
        if s.ws is ws:
            s.ws = None
            if not s.finished:
                s.reaper = asyncio.create_task(reap_later(session_id))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
