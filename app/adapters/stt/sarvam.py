"""Sarvam Saaras speech-to-text (REST, < 30 s audio). Docs: https://docs.sarvam.ai/api-reference/speech-to-text/transcribe"""
from __future__ import annotations

import os

import httpx

from app.adapters.base import ProviderError, log_call, timed

URL = "https://api.sarvam.ai/speech-to-text"
EXT = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/webm": "webm", "audio/ogg": "ogg",
       "audio/mpeg": "mp3", "audio/mp4": "m4a"}


class SarvamSTT:
    name = "sarvam"

    def __init__(self):
        self.key = os.getenv("SARVAM_API_KEY", "")
        self.model = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
        # translit = romanised output ("claim kaise milega"), which is what topic_router keywords expect.
        self.mode = os.getenv("SARVAM_STT_MODE", "translit")
        self.client = httpx.AsyncClient(timeout=30)

    async def transcribe(self, audio: bytes, mime: str = "audio/wav", lang_hint: str | None = None) -> dict:
        base_mime = (mime or "audio/wav").split(";")[0]
        files = {"file": (f"audio.{EXT.get(base_mime, 'wav')}", audio, base_mime)}
        data = {"model": self.model, "language_code": lang_hint or "unknown"}
        if self.model == "saaras:v3":
            data["mode"] = self.mode
        with timed() as t:
            r = await self.client.post(URL, headers={"api-subscription-key": self.key}, data=data, files=files)
        log_call("stt", self.name, self.model, t["ms"], status=r.status_code, bytes=len(audio))
        if r.status_code != 200:
            raise ProviderError(f"sarvam stt {r.status_code}: {r.text[:300]}")
        j = r.json()
        return {"text": (j.get("transcript") or "").strip(), "language_code": j.get("language_code"),
                "provider_ms": t["ms"]}
