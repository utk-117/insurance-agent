"""FastAPI app. M0: health check, WebSocket echo (to prove WS works on Cloud Run), static files.
POST /api/session and WS /ws/{session_id} arrive in M4."""
from __future__ import annotations

import logging
import os
import pathlib

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="Insurance voice agent")


@app.get("/healthz")
def healthz():
    return {"ok": True, "stt": os.getenv("STT_PROVIDER", "sarvam"), "tts": os.getenv("TTS_PROVIDER", "sarvam"),
            "llm": os.getenv("LLM_PROVIDER", "sarvam")}


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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
