"""Session state (v2). The phase logic lives in controller.py; this is just the data."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


class Phase(str, Enum):
    GREET = "GREET"
    CONFIRM_IDENTITY = "CONFIRM_IDENTITY"
    INTAKE = "INTAKE"
    CONSULT = "CONSULT"
    CLOSE = "CLOSE"
    WRAP_UP = "WRAP_UP"
    END = "END"


@dataclass
class SessionState:
    lead: dict
    llm_provider: Optional[str] = None   # None = LLM_PROVIDER env
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: now_ist().isoformat(timespec="seconds"))
    phase: Phase = Phase.GREET
    profile: dict = field(default_factory=lambda: {"age": None, "gender": None, "employment_type": None,
                                                   "annual_income_inr": None, "tobacco": None})
    snapshot: Optional[dict] = None
    consult_opened: bool = False
    intents: list = field(default_factory=list)            # free text, for the lead sheet only
    objections: list = field(default_factory=list)         # free text, for the lead sheet only
    discussed_products: list = field(default_factory=list)
    quoted: list = field(default_factory=list)             # [{product_id, sum_assured, range}]
    callback_time: Optional[str] = None
    purchase_link: Optional[str] = None
    outcome: Optional[str] = None
    soft_retry_used: bool = False
    summary: Optional[str] = None
    goodbye: Optional[str] = None                          # last line from end_conversation
    events: list = field(default_factory=list)             # UI events raised by tools this turn (drained per turn)
    transcript: list = field(default_factory=list)         # [{role, text, lang, ts}]
    turn_log: list = field(default_factory=list)           # per turn: phase in/out, tool calls, llm_ms
    tool_calls: list = field(default_factory=list)         # [{name, args, ok, ms, error?}]
    latencies: list = field(default_factory=list)          # [{stt_ms, llm_ms, tts_first_ms, total_first_audio_ms}]
    metrics: dict = field(default_factory=lambda: {"llm_calls": 0, "tool_rounds": 0, "parse_fallbacks": 0,
                                                   "input_tokens": 0, "output_tokens": 0, "tool_mode": None})

    @property
    def stage(self) -> Phase:  # v1 name, still read by the voice pipeline / UI
        return self.phase

    def add(self, role: str, text: str, lang: str | None = None):
        self.transcript.append({"role": role, "text": text, "lang": lang,
                                "ts": now_ist().isoformat(timespec="seconds")})

    def to_dict(self) -> dict:
        d = asdict(self)
        d["phase"] = self.phase.value
        return d
