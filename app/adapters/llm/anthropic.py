"""Claude via the official anthropic SDK, with prompt caching and structured JSON output.

system may be a string or a list of {"text", "cache"} blocks: put the static parts (rails, cards,
need_fit, buying_process) first with cache=True and the per-turn context last.
"""
from __future__ import annotations

import os

import anthropic

from app.adapters.base import (LLMParseError, ProviderError, check_required, count_parse_failure,
                               extract_json, log_call, timed)

REPAIR = ("Your previous reply was not a single valid JSON object matching the required schema. "
          "Reply again with ONLY the JSON object.")


def system_blocks(system) -> list:
    if isinstance(system, str):
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    blocks = []
    for b in system:
        block = {"type": "text", "text": b["text"]}
        if b.get("cache"):
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks


class AnthropicLLM:
    name = "anthropic"

    def __init__(self):
        self.model = (os.getenv("LLM_MODEL") if os.getenv("LLM_PROVIDER") == "anthropic" else None) \
            or os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
        self.effort = os.getenv("ANTHROPIC_EFFORT", "low")  # low keeps voice latency down
        self.max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
        self.client = anthropic.AsyncAnthropic()

    async def _call(self, system, messages, schema):
        output_config = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            output_config["effort"] = self.effort
        with timed() as t:
            try:
                resp = await self.client.messages.create(
                    model=self.model, max_tokens=self.max_tokens, system=system_blocks(system),
                    messages=messages, output_config=output_config)
            except anthropic.APIStatusError as e:
                log_call("llm", self.name, self.model, t["ms"], status=e.status_code)
                raise ProviderError(f"anthropic {e.status_code}: {str(e)[:300]}")
            except anthropic.APIConnectionError as e:
                raise ProviderError(f"anthropic connection error: {e}")
        u = resp.usage
        log_call("llm", self.name, self.model, t["ms"], status=200, stop_reason=resp.stop_reason,
                 input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                 cache_read=u.cache_read_input_tokens, cache_write=u.cache_creation_input_tokens)
        if resp.stop_reason == "refusal":
            raise ProviderError("anthropic refusal")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        tin = u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        return text, t["ms"], tin, u.output_tokens

    async def complete_json(self, system, messages: list, schema: dict) -> dict:
        text, ms, tin, tout = await self._call(system, messages, schema)
        try:
            data = extract_json(text)
            check_required(data, schema)
        except ValueError as e:
            count_parse_failure(self.name)
            msgs = list(messages) + [{"role": "assistant", "content": text or "{}"},
                                     {"role": "user", "content": REPAIR}]
            text, ms2, tin2, tout2 = await self._call(system, msgs, schema)
            ms, tin, tout = ms + ms2, tin + tin2, tout + tout2
            try:
                data = extract_json(text)
                check_required(data, schema)
            except ValueError as e2:
                count_parse_failure(self.name)
                raise LLMParseError(f"anthropic: unparseable after repair ({e}; {e2})")
        return {"data": data, "provider_ms": ms, "input_tokens": tin, "output_tokens": tout,
                "provider": self.name, "model": self.model}

    # ---- tool calling (v2 consult phase): native tool use ----------------------------------------
    tool_mode = "native"

    async def chat_with_tools(self, system, messages: list, tools: list, allow_tools: bool = True) -> dict:
        kwargs = dict(model=self.model, max_tokens=self.max_tokens, system=system_blocks(system),
                      messages=_to_anthropic(messages))
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if tools:
            kwargs["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                               for t in tools]
            kwargs["tool_choice"] = {"type": "auto"} if allow_tools else {"type": "none"}
        with timed() as t:
            try:
                resp = await self.client.messages.create(**kwargs)
            except anthropic.APIStatusError as e:
                log_call("llm", self.name, self.model, t["ms"], status=e.status_code)
                raise ProviderError(f"anthropic {e.status_code}: {str(e)[:300]}")
            except anthropic.APIConnectionError as e:
                raise ProviderError(f"anthropic connection error: {e}")
        u = resp.usage
        if resp.stop_reason == "refusal":
            raise ProviderError("anthropic refusal")
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [{"id": b.id, "name": b.name, "args": b.input if isinstance(b.input, dict) else {}}
                 for b in resp.content if b.type == "tool_use"]
        log_call("llm", self.name, self.model, t["ms"], status=200, stop_reason=resp.stop_reason,
                 tool_calls=[c["name"] for c in calls], input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                 cache_read=u.cache_read_input_tokens, cache_write=u.cache_creation_input_tokens)
        tin = u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        return {"reply": text or None, "tool_calls": calls,
                "raw": [b.model_dump(exclude_none=True) for b in resp.content],
                "provider_ms": t["ms"], "input_tokens": tin, "output_tokens": u.output_tokens,
                "provider": self.name, "model": self.model, "tool_mode": "native"}


def _to_anthropic(messages: list) -> list:
    """Neutral messages -> Anthropic. Assistant tool turns reuse their raw blocks (keeps thinking blocks intact);
    consecutive tool results go into one user message."""
    out = []
    for m in messages:
        if m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m["role"] == "assistant" and m.get("raw"):
            out.append({"role": "assistant", "content": m["raw"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + \
                     [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m["tool_calls"]]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out
