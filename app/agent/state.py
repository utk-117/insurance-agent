"""Session state. The stage machine lives in controller.py; this is just the data."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


class Stage(str, Enum):
    GREET = "GREET"
    CONFIRM_IDENTITY = "CONFIRM_IDENTITY"
    DISCOVERY = "DISCOVERY"
    NEED_CHECK = "NEED_CHECK"
    RECOMMEND = "RECOMMEND"
    QA = "QA"
    OBJECTION = "OBJECTION"
    CLOSE = "CLOSE"
    PURCHASE_LINK = "PURCHASE_LINK"
    CALLBACK = "CALLBACK"
    WRAP_UP = "WRAP_UP"
    END = "END"


PROFILE_FIELDS = ["goal", "age", "dependents", "income_band", "gender", "city"]  # discovery order


@dataclass
class SessionState:
    lead: dict
    llm_provider: Optional[str] = None   # None = LLM_PROVIDER env
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: now_ist().isoformat(timespec="seconds"))
    profile: dict = field(default_factory=lambda: {k: None for k in PROFILE_FIELDS + [
        "motivation", "primary_need", "preferred_insurer"]})
    stage: Stage = Stage.GREET
    resume_stage: Optional[Stage] = None
    shortlist: list = field(default_factory=list)
    selected_product: Optional[str] = None
    pitched_product: Optional[str] = None
    loaded_products: list = field(default_factory=list)
    product_refs: list = field(default_factory=list)
    objections_handled: list = field(default_factory=list)
    last_intent: Optional[str] = None
    pending_callback_iso: Optional[str] = None
    callback_time: Optional[str] = None
    purchase_link: Optional[str] = None
    outcome: Optional[str] = None
    soft_retry_used: bool = False
    price_asked: bool = False
    summary: Optional[str] = None
    transcript: list = field(default_factory=list)   # [{role, text, lang, ts}]
    turn_log: list = field(default_factory=list)     # per turn: stage in/out, intent, loaded sections, llm_ms
    latencies: list = field(default_factory=list)    # [{stt_ms, llm_ms, tts_first_ms, total_first_audio_ms}]
    metrics: dict = field(default_factory=lambda: {"llm_calls": 0, "router_miss": 0, "objection_followup": 0,
                                                   "parse_fallbacks": 0, "input_tokens": 0, "output_tokens": 0,
                                                   "discovery_turns": 0})

    def missing_fields(self) -> list:
        return [f for f in PROFILE_FIELDS if self.profile.get(f) in (None, "")]

    def add(self, role: str, text: str, lang: str | None = None):
        self.transcript.append({"role": role, "text": text, "lang": lang,
                                "ts": now_ist().isoformat(timespec="seconds")})

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.value
        d["resume_stage"] = self.resume_stage.value if self.resume_stage else None
        return d
