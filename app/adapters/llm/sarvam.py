"""Sarvam chat completions (OpenAI-shaped). Docs: https://docs.sarvam.ai/api-reference/chat/chat-completions-v1

system may be a string or a list of {"text", "cache"} blocks (cache is ignored here - Sarvam has no prompt caching).
"""
from __future__ import annotations

import json
import os

import httpx

from app.adapters.base import (LLMParseError, ProviderError, check_required, count_parse_failure,
                               extract_json, log_call, timed)

URL = "https://api.sarvam.ai/v1/chat/completions"
REPAIR = ("Your previous reply was not a single valid JSON object matching the required schema. "
          "Reply again with ONLY the JSON object, no prose and no code fences.")


def system_text(system) -> str:
    if isinstance(system, str):
        return system
    return "\n\n".join(b["text"] for b in system)


class SarvamLLM:
    name = "sarvam"

    def __init__(self):
        self.key = os.getenv("SARVAM_API_KEY", "")
        self.model = (os.getenv("LLM_MODEL") if os.getenv("LLM_PROVIDER", "sarvam") == "sarvam" else None) \
            or "sarvam-105b-conversations"
        # json_schema | json_object | none  (json_schema = structured outputs per docs)
        self.json_mode = os.getenv("SARVAM_JSON_MODE", "json_schema")
        # "none" sends reasoning_effort: null, which disables reasoning (lowest latency for voice)
        self.reasoning = os.getenv("SARVAM_REASONING_EFFORT", "none")
        self.max_tokens = int(os.getenv("SARVAM_MAX_TOKENS", "1024"))
        self.client = httpx.AsyncClient(timeout=float(os.getenv("SARVAM_LLM_TIMEOUT", "30")))

    def _body(self, msgs, schema):
        body = {"model": self.model, "messages": msgs, "temperature": 0.2, "max_tokens": self.max_tokens,
                "reasoning_effort": None if self.reasoning == "none" else self.reasoning}
        if self.json_mode == "json_schema":
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "reply", "schema": schema, "strict": False}}
        elif self.json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    async def _call(self, msgs, schema):
        with timed() as t:
            try:
                r = await self.client.post(URL, headers={"api-subscription-key": self.key},
                                           json=self._body(msgs, schema))
            except httpx.HTTPError as e:
                raise ProviderError(f"sarvam {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            log_call("llm", self.name, self.model, t["ms"], status=r.status_code)
            raise ProviderError(f"sarvam llm {r.status_code}: {r.text[:300]}")
        j = r.json()
        usage = j.get("usage") or {}
        content = (j["choices"][0]["message"].get("content") or "")
        log_call("llm", self.name, self.model, t["ms"], status=200, finish=j["choices"][0].get("finish_reason"),
                 input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"))
        return content, t["ms"], usage.get("prompt_tokens", 0) or 0, usage.get("completion_tokens", 0) or 0

    async def complete_json(self, system, messages: list, schema: dict) -> dict:
        msgs = [{"role": "system", "content": system_text(system)}] + list(messages)
        content, ms, tin, tout = await self._call(msgs, schema)
        try:
            data = extract_json(content)
            check_required(data, schema)
        except ValueError as e:
            count_parse_failure(self.name)
            msgs = msgs + [{"role": "assistant", "content": content}, {"role": "user", "content": REPAIR}]
            content, ms2, tin2, tout2 = await self._call(msgs, schema)
            ms, tin, tout = ms + ms2, tin + tin2, tout + tout2
            try:
                data = extract_json(content)
                check_required(data, schema)
            except ValueError as e2:
                count_parse_failure(self.name)
                raise LLMParseError(f"sarvam: unparseable after repair ({e}; {e2}): {content[:200]!r}")
        return {"data": data, "provider_ms": ms, "input_tokens": tin, "output_tokens": tout,
                "provider": self.name, "model": self.model}
