"""Sarvam Bulbul text-to-speech (REST). Docs: https://docs.sarvam.ai/api-reference/text-to-speech/convert"""
from __future__ import annotations

import base64
import os

import httpx

from app.adapters.base import ProviderError, log_call, timed

URL = "https://api.sarvam.ai/text-to-speech"
SUPPORTED = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}
MIME = {"wav": "audio/wav", "mp3": "audio/mpeg", "opus": "audio/ogg", "aac": "audio/aac", "flac": "audio/flac"}


class SarvamTTS:
    name = "sarvam"

    def __init__(self):
        self.key = os.getenv("SARVAM_API_KEY", "")
        self.model = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
        self.speaker = os.getenv("SARVAM_TTS_SPEAKER", "priya")
        self.codec = os.getenv("SARVAM_TTS_CODEC", "mp3")
        self.sample_rate = int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "22050"))
        self.pace = float(os.getenv("SARVAM_TTS_PACE", "1.0"))
        self.client = httpx.AsyncClient(timeout=30)

    async def speak(self, text: str, language_code: str = "en-IN") -> dict:
        lang = language_code if language_code in SUPPORTED else "en-IN"
        body = {"text": text, "language_code": lang, "model": self.model, "speaker": self.speaker,
                "pace": self.pace, "speech_sample_rate": self.sample_rate, "output_audio_codec": self.codec}
        with timed() as t:
            try:
                r = await self.client.post(URL, headers={"api-subscription-key": self.key}, json=body)
            except httpx.HTTPError as e:
                raise ProviderError(f"sarvam {type(e).__name__}: {e}") from e
        log_call("tts", self.name, self.model, t["ms"], status=r.status_code, chars=len(text), lang=lang)
        if r.status_code != 200:
            raise ProviderError(f"sarvam tts {r.status_code}: {r.text[:300]}")
        audio = base64.b64decode(r.json()["audios"][0])
        return {"audio": audio, "mime": MIME.get(self.codec, "audio/wav"), "provider_ms": t["ms"]}
