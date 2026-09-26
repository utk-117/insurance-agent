"""Side effects the controller runs. The LLM never calls these directly."""
from __future__ import annotations

from app import sheets
from app.agent import knowledge
from app.agent.state import SessionState, now_ist


def share_purchase_link(state: SessionState, product_id: str) -> dict | None:
    """UI event for the product's official page, or None if purchase_url is not filled in."""
    card = knowledge.cards().get(product_id)
    if not card or not card.get("purchase_url"):
        return None
    state.purchase_link = card["purchase_url"]
    return {"type": "purchase_link", "product_id": product_id, "name": card["name"],
            "insurer": card["insurer"], "url": card["purchase_url"]}


def _row(state: SessionState) -> dict:
    p, snap = state.profile, state.snapshot or {}
    lat = [x["total_first_audio_ms"] for x in state.latencies if x.get("total_first_audio_ms")]
    return {
        "timestamp_ist": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": state.session_id, "name": state.lead.get("name"), "phone": state.lead.get("phone"),
        "age": p.get("age"), "gender": p.get("gender"), "employment_type": p.get("employment_type"),
        "annual_income_inr": p.get("annual_income_inr"), "tobacco": p.get("tobacco"),
        "max_cover": snap.get("max_cover"),
        "eligible_products": ";".join(e["product_id"] for e in snap.get("eligible", [])),
        "intents": "; ".join(state.intents), "discussed_products": ";".join(state.discussed_products),
        "quoted_ranges": "; ".join(f"{q['product_id']}@{q['sum_assured']}:{q['range'][0]}-{q['range'][1]}"
                                   for q in state.quoted),
        "objections": "; ".join(state.objections), "outcome": state.outcome,
        "callback_time_ist": state.callback_time, "purchase_link": state.purchase_link, "summary": state.summary,
        "turns": sum(1 for t in state.transcript if t["role"] == "user"),
        "tool_calls": len(state.tool_calls),
        "avg_first_audio_ms": round(sum(lat) / len(lat)) if lat else None,
    }


def log_callback(state: SessionState, iso: str) -> dict:
    state.callback_time = iso
    state.outcome = "purchase_link_and_callback" if state.purchase_link else "callback_scheduled"
    sheets.upsert(_row(state))
    return {"type": "callback_booked", "callback_time_ist": iso}


def log_outcome(state: SessionState) -> str:
    if not state.outcome:
        state.outcome = "dropped"
    return sheets.upsert(_row(state))
