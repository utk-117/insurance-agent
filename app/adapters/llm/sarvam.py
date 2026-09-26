"""Sarvam chat completions (OpenAI-shaped). Docs: https://docs.sarvam.ai/api-reference/chat/chat-completions-v1

system may be a string or a list of {"text", "cache"} blocks (cache is ignored here - Sarvam has no prompt caching).
"""
from __future__ import annotations

import json
import os

import httpx

from app.adapters.base import (LLMParseError, ProviderError, check_required, count_parse_failure,
                               count_tool_error, extract_json, log_call, prompt_section, timed)

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

    # ---- tool calling (v2 consult phase) --------------------------------------------------------
    # SARVAM_TOOL_MODE=native uses the API's OpenAI-style `tools`; json uses the prompt protocol in
    # prompts/tools_json.md. native falls back to json for the rest of the process if the API rejects tools.

    @property
    def tool_mode(self) -> str:
        return os.getenv("SARVAM_TOOL_MODE", "native") if not getattr(self, "_forced_json", False) else "json"

    async def chat_with_tools(self, system, messages: list, tools: list, allow_tools: bool = True) -> dict:
        if self.tool_mode == "json":
            return await self._chat_json_protocol(system, messages, tools, allow_tools)
        msgs = [{"role": "system", "content": system_text(system)}] + _to_openai(messages)
        body = {"model": self.model, "messages": msgs, "temperature": 0.3, "max_tokens": self.max_tokens,
                "reasoning_effort": None if self.reasoning == "none" else self.reasoning}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
            body["tool_choice"] = "auto" if allow_tools else "none"
        with timed() as t:
            try:
                r = await self.client.post(URL, headers={"api-subscription-key": self.key}, json=body)
            except httpx.HTTPError as e:
                raise ProviderError(f"sarvam {type(e).__name__}: {e}") from e
        if r.status_code == 400 and "tool" in r.text.lower():
            log_call("llm", self.name, self.model, t["ms"], status=400, tool_mode="native", fallback="json")
            self._forced_json = True
            return await self._chat_json_protocol(system, messages, tools, allow_tools)
        if r.status_code != 200:
            log_call("llm", self.name, self.model, t["ms"], status=r.status_code, tool_mode="native")
            raise ProviderError(f"sarvam llm {r.status_code}: {r.text[:300]}")
        j = r.json()
        msg, usage = j["choices"][0]["message"], j.get("usage") or {}
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            try:
                args = fn.get("arguments") or "{}"
                args = json.loads(args) if isinstance(args, str) else args
            except ValueError:
                try:
                    args = extract_json(fn.get("arguments"))
                except ValueError:
                    count_tool_error(self.name, str(fn.get("arguments")))
                    args = {}
            calls.append({"id": tc.get("id") or f"call_{i}", "name": fn.get("name"), "args": args})
        log_call("llm", self.name, self.model, t["ms"], status=200, tool_mode="native",
                 finish=j["choices"][0].get("finish_reason"), tool_calls=[c["name"] for c in calls],
                 input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"))
        return {"reply": (msg.get("content") or "").strip() or None, "tool_calls": calls, "raw": None,
                "provider_ms": t["ms"], "input_tokens": usage.get("prompt_tokens", 0) or 0,
                "output_tokens": usage.get("completion_tokens", 0) or 0, "provider": self.name, "model": self.model,
                "tool_mode": "native"}

    async def _chat_json_protocol(self, system, messages, tools, allow_tools):
        tool_list = "\n".join(f"- {t['name']}: {t['description']} args: {json.dumps(t['parameters']['properties'])}"
                              for t in tools)
        sys_text = system_text(system) + "\n\n" + prompt_section("tools_json.md", "PROTOCOL").replace(
            "{tools}", tool_list)
        if not allow_tools:
            sys_text += "\n\n" + prompt_section("tools_json.md", "NO_MORE_TOOLS")
        schema = {"type": "object", "properties": {
            "reply": {"type": ["string", "null"]},
            "tool_calls": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "args": {"type": "object"}}, "required": ["name"]}}},
            "required": ["reply", "tool_calls"]}
        r = await self.complete_json(sys_text, _to_text(messages), schema)
        d = r["data"]
        calls = []
        for i, c in enumerate(d.get("tool_calls") or []):
            if not isinstance(c, dict) or not c.get("name"):
                count_tool_error(self.name, json.dumps(c)[:200])
                continue
            calls.append({"id": f"call_{i}", "name": c["name"],
                          "args": c.get("args") if isinstance(c.get("args"), dict) else {}})
        if not allow_tools:
            calls = [c for c in calls if c["name"] in ("book_callback", "share_purchase_link", "end_conversation")]
        reply = d.get("reply")
        return {"reply": reply.strip() if isinstance(reply, str) and reply.strip() else None, "tool_calls": calls,
                "raw": None, "provider_ms": r["provider_ms"], "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"], "provider": self.name, "model": self.model, "tool_mode": "json"}


def _to_openai(messages: list) -> list:
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or "",
                        "tool_calls": [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                                       for c in m["tool_calls"]]})
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


def _to_text(messages: list) -> list:
    """Neutral messages -> plain chat for the JSON protocol (tool turns become JSON / result text)."""
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": json.dumps(
                {"reply": m.get("content"), "tool_calls": [{"name": c["name"], "args": c["args"]}
                                                          for c in m["tool_calls"]]}, ensure_ascii=False)})
        elif m["role"] == "tool":
            text = f"TOOL RESULT {m.get('name')}: {m['content']}"
            if out and out[-1]["role"] == "user" and out[-1]["content"].startswith("TOOL RESULT"):
                out[-1]["content"] += "\n" + text
            else:
                out.append({"role": "user", "content": text})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out
