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
    p = state.profile
    card = knowledge.cards().get(state.selected_product or "", {})
    lat = [x["total_first_audio_ms"] for x in state.latencies if x.get("total_first_audio_ms")]
    return {
        "timestamp_ist": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": state.session_id, "name": state.lead.get("name"), "phone": state.lead.get("phone"),
        "age": p.get("age"), "gender": p.get("gender"), "city": p.get("city"), "goal": p.get("goal"),
        "dependents": p.get("dependents"), "income_band": p.get("income_band"),
        "primary_need": p.get("primary_need"), "shortlisted": ";".join(state.shortlist),
        "selected_insurer": card.get("insurer"), "selected_product": state.selected_product,
        "objections": ";".join(state.objections_handled), "outcome": state.outcome,
        "callback_time_ist": state.callback_time, "purchase_link": state.purchase_link,
        "price_asked": state.price_asked, "summary": state.summary,
        "turns": sum(1 for t in state.transcript if t["role"] == "user"),
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
