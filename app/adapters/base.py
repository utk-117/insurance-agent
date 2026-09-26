"""Provider interfaces + registry. Providers are picked by STT_PROVIDER / TTS_PROVIDER / LLM_PROVIDER.

Adding a provider = one file in app/adapters/<kind>/<name>.py exposing a class with the method below,
plus one line in the matching REGISTRY dict.

  STT.transcribe(audio: bytes, mime: str, lang_hint: str|None) -> {text, language_code, provider_ms}
  TTS.speak(text: str, language_code: str) -> {audio: bytes, mime: str, provider_ms}
  LLM.complete_json(system: str|list, messages: list, schema: dict)
      -> {data: dict, provider_ms, input_tokens, output_tokens}
  LLM.chat_with_tools(system, messages, tools, allow_tools=True)
      -> {reply: str|None, tool_calls: [{id, name, args}], raw, provider_ms, input_tokens, output_tokens}
     messages use one neutral format:  {"role": "user"|"assistant", "content": str}
       assistant tool turn: {"role": "assistant", "content": str|None, "tool_calls": [{id, name, args}], "raw": ...}
       tool result:         {"role": "tool", "tool_call_id": id, "name": name, "content": json str}
     tools: [{name, description, parameters (JSON schema)}]
All methods are async.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import pathlib
import re
import time
from contextlib import contextmanager

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("adapters")

# kind -> provider name -> "module:Class"
REGISTRY = {
    "stt": {"sarvam": "app.adapters.stt.sarvam:SarvamSTT"},
    "tts": {"sarvam": "app.adapters.tts.sarvam:SarvamTTS"},
    "llm": {
        "sarvam": "app.adapters.llm.sarvam:SarvamLLM",
        "anthropic": "app.adapters.llm.anthropic:AnthropicLLM",
    },
}

_instances = {}


def get(kind: str, provider: str | None = None):
    """Return a (cached) adapter instance for kind in {stt, tts, llm}. "anthropic:claude-sonnet-5" picks a model."""
    provider = provider or os.getenv(f"{kind.upper()}_PROVIDER") or "sarvam"
    name, _, model = provider.partition(":")
    name = name.lower()
    key = (kind, provider)
    if key not in _instances:
        try:
            target = REGISTRY[kind][name]
        except KeyError:
            raise ValueError(f"unknown {kind} provider '{name}'; known: {list(REGISTRY[kind])}")
        mod, cls = target.split(":")
        inst = getattr(importlib.import_module(mod), cls)()
        if model:
            inst.model = model
        _instances[key] = inst
    return _instances[key]


def get_stt(provider=None):
    return get("stt", provider)


def get_tts(provider=None):
    return get("tts", provider)


def get_llm(provider=None):
    return get("llm", provider)


class ProviderError(RuntimeError):
    pass


class LLMParseError(ProviderError):
    pass


@contextmanager
def timed():
    """with timed() as t: ...; t['ms'] holds elapsed milliseconds."""
    t = {"ms": 0}
    start = time.perf_counter()
    try:
        yield t
    finally:
        t["ms"] = round((time.perf_counter() - start) * 1000)


def log_call(kind: str, provider: str, model: str, ms: int, **extra):
    """One structured log line per provider call, so latency can be compared across providers."""
    log.info(json.dumps({"event": "provider_call", "kind": kind, "provider": provider,
                         "model": model, "ms": ms, **extra}, ensure_ascii=False))


# ---- JSON robustness shared by LLM adapters -------------------------------------------------

PARSE_FAILURES: dict = {}  # provider -> count of unparseable responses (before repair retry)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def extract_json(text: str) -> dict:
    """Strip code fences / prose and return the first balanced JSON object. Raises ValueError."""
    if text is None:
        raise ValueError("empty response")
    s = _FENCE.sub("", text.strip())
    # drop any <think>...</think> blocks some models emit
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL)
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        start = s.find("{", start + 1)
    raise ValueError("no JSON object found")


def check_required(data: dict, schema: dict):
    """Cheap top-level check; full validation happens in pydantic in the controller."""
    missing = [k for k in schema.get("required", []) if k not in data]
    if missing:
        raise ValueError(f"missing keys: {missing}")


def prompt_section(file: str, name: str) -> str:
    """'## NAME' section of prompts/<file> (adapters keep their protocol text in prompts/, not in code)."""
    text = (pathlib.Path(__file__).resolve().parents[2] / "prompts" / file).read_text()
    m = re.search(rf"(?ms)^## {re.escape(name)}\n(.*?)(?=^## |\Z)", text)
    return m.group(1).strip() if m else ""


TOOL_ERRORS: dict = {}  # provider -> malformed tool calls (bad JSON args / unknown shape)


def count_tool_error(provider: str, detail: str = ""):
    TOOL_ERRORS[provider] = TOOL_ERRORS.get(provider, 0) + 1
    log.warning(json.dumps({"event": "llm_tool_call_error", "provider": provider, "total": TOOL_ERRORS[provider],
                            "detail": detail[:200]}))


def count_parse_failure(provider: str):
    PARSE_FAILURES[provider] = PARSE_FAILURES.get(provider, 0) + 1
    log.warning(json.dumps({"event": "llm_parse_failure", "provider": provider,
                            "total": PARSE_FAILURES[provider]}))
