"""ServiceSync Voice — AI phone dispatcher.

Given a customer job and a set of candidate contractors, this orchestrates the
agentic workflow the CALL-E hackathon rewards:

    1. build a phone script per provider
    2. place the call via CALL-E        (app/services/calle_client.py)
    3. extract a structured ServiceCallResult from the transcript
                                     (provider-agnostic LLM — app/services/llm.py)
    4. rank providers and flag outcomes needing human approval

Design notes
------------
* The LLM and the telephony layer are both swappable. Extraction works with
  Gemini / Groq / Ollama; calling works with any configured CALL-E account.
* Every call must resolve to the canonical ``ServiceCallResult`` schema, so a
  messy human conversation ("around two, twenty-fiveish thousand") becomes
  usable structured data.
* ``requires_human_approval`` is set whenever an offer is ambiguous / very
  expensive / missing info — the agent never commits the customer silently.
* No CALL-E key -> ``CallENotConfigured``; callers should treat that as a
  "pending / unavailable" state, not a crash.

This is a scaffold: wiring it into the job/booking flow (a new
``/api/v1/voice/dispatch`` route + admin/status UI) is the next step.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

from app.core.config import settings
from app.services.llm import get_provider
from app.services.calle_client import create_call, get_call, CallENotConfigured
from app.models.all_models import User, Job

logger = logging.getLogger("services.voice_dispatch")

# In-memory dispatch ledger (single instance). Swap for a DB table if you need
# persistence across restarts / multiple workers.
DISPATCH_STATE: dict[int, list["ProviderOffer"]] = {}


class ServiceCallResult(BaseModel):
    """Canonical structured offer extracted from a provider phone call."""

    availability: Optional[bool] = None
    earliest_time: Optional[str] = None
    estimated_price: Optional[float] = None
    service_scope: Optional[str] = None
    travel_fee: Optional[float] = None
    warranty: Optional[str] = None
    confidence: str = "low"
    evidence: str = ""
    requires_human_approval: bool = False


# JSON Schema handed to CALL-E so it returns the call outcome pre-structured.
SERVICECALL_RESULT_SCHEMA = {
    "type": "object",
    "required": ["availability"],
    "properties": {
        "availability": {"type": ["boolean", "null"]},
        "earliest_time": {"type": ["string", "null"]},
        "estimated_price": {"type": ["number", "null"]},
        "service_scope": {"type": ["string", "null"]},
        "travel_fee": {"type": ["number", "null"]},
        "warranty": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "evidence": {"type": "string"},
        "requires_human_approval": {"type": "boolean"},
    },
}


@dataclass
class ProviderOffer:
    contractor_id: int
    call_id: Optional[str] = None
    raw_transcript: str = ""
    result: ServiceCallResult = field(default_factory=ServiceCallResult)
    error: Optional[str] = None


def _brief_context(job: Job) -> str:
    """Short, call-ready summary of a structured job brief (CCTV-aware)."""
    if not job.brief:
        return ""
    cat = (job.brief.get("category") or job.category or "").lower()
    if cat == "cctv":
        c = job.brief.get("cctv") or {}
        bits = []
        if c.get("site_type"):
            bits.append(f"site: {c['site_type']}")
        if c.get("camera_count") is not None:
            bits.append(f"cameras: {c['camera_count']}")
        if c.get("indoor_outdoor"):
            bits.append(f"coverage: {c['indoor_outdoor']}")
        if c.get("key_features"):
            bits.append("features: " + ", ".join(c["key_features"]))
        if c.get("existing_wiring"):
            bits.append(f"wiring: {c['existing_wiring']}")
        if c.get("internet_available") is not None:
            bits.append(f"internet on site: {'yes' if c['internet_available'] else 'no'}")
        if c.get("budget_range"):
            bits.append(f"budget: {c['budget_range']}")
        if c.get("urgency"):
            bits.append(f"urgency: {c['urgency']}")
        if bits:
            return "Structured brief — " + "; ".join(bits) + "."
    return ""


def _build_task(job: Job, contractor: User) -> str:
    name = contractor.full_name or "the service provider"
    brief = _brief_context(job)
    brief_line = f" Structured brief: {brief}" if brief else ""
    return (
        f"You are calling {name} on behalf of a ServiceSync customer. "
        f"The customer needs the following job: {job.description}.{brief_line} "
        f"Please confirm: (1) Are you available, and what is your earliest start time? "
        f"(2) What is your estimated total price, and any separate travel fee? "
        f"(3) What does that price include (scope and warranty)? "
        f"Keep answers concise and end by summarizing your offer."
    )


def _parse_structured(data: dict) -> Optional[ServiceCallResult]:
    """Pull a ServiceCallResult from a CALL-E call payload (task- or recipient-level)."""
    sr = data.get("structured_result")
    if not sr and data.get("recipients"):
        sr = (data.get("recipients") or [{}])[0].get("structured_result")
    if isinstance(sr, dict):
        try:
            return ServiceCallResult(**{k: sr.get(k) for k in ServiceCallResult.model_fields})
        except Exception:
            return None
    return None


async def extract_result(transcript: str, job: Job) -> ServiceCallResult:
    """Turn a CALL-E transcript into a canonical ServiceCallResult via the LLM."""
    prompt = f"""
    Extract a structured service-provider offer from this phone-call transcript.
    Job: {job.description}

    Transcript:
    {transcript}

    Return strictly valid JSON matching this schema:
    {{
      "availability": boolean|null,
      "earliest_time": string|null,
      "estimated_price": number|null,
      "service_scope": string|null,
      "travel_fee": number|null,
      "warranty": string|null,
      "confidence": "high"|"medium"|"low",
      "evidence": string,
      "requires_human_approval": boolean
    }}
    Set requires_human_approval=true if the offer is ambiguous, very expensive,
    or missing key information. Output JSON only, no markdown.
    """
    try:
        text = await get_provider().complete(prompt, json_mode=True, temperature=0.2)
        return ServiceCallResult(**json.loads(text.replace("```json", "").replace("```", "").strip()))
    except Exception as exc:  # extraction failure -> route to a human, never guess
        logger.warning("voice dispatch extraction failed: %s", exc)
        return ServiceCallResult(confidence="low", evidence="extraction failed", requires_human_approval=True)


async def dispatch_calls(job: Job, contractors: list[User]) -> list[ProviderOffer]:
    """Place a CALL-E call to each candidate contractor and capture the offers.

    Calls are placed asynchronously; results are resolved later (via
    ``resolve_offer`` polling or the CALL-E terminal webhook). If CALL-E is not
    configured, each offer is marked with an error and left pending.
    """
    offers: list[ProviderOffer] = []
    for contractor in contractors:
        offer = ProviderOffer(contractor_id=contractor.id)
        try:
            task = _build_task(job, contractor)
            region = _region_hint(contractor)
            call_id = await create_call(
                task,
                contractor.phone or "",
                region=region,
                result_schema=SERVICECALL_RESULT_SCHEMA,
                idempotency_key=f"servicesync:job:{job.id}:contractor:{contractor.id}",
                webhook_url=(
                    f"{settings.CALL_E_WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/calle"
                    if settings.CALL_E_WEBHOOK_BASE_URL else None
                ),
            )
            offer.call_id = call_id
            # Placeholder until the call completes; resolution pulls the result.
            offer.result = ServiceCallResult(confidence="low", requires_human_approval=True)
        except CallENotConfigured as exc:
            offer.error = f"voice dispatch unavailable: {exc}"
        except Exception as exc:
            offer.error = str(exc)
            logger.warning("voice dispatch call failed for contractor %s: %s", contractor.id, exc)
        offers.append(offer)
    return offers


def _region_hint(contractor: User) -> Optional[str]:
    """Best-effort region hint for CALL-E routing (e.g. 'NG', 'US')."""
    country = (contractor.country or "").strip()
    if not country:
        return None
    return country[:2].upper() if len(country) == 2 else country


async def resolve_offer(job: Job, offer: ProviderOffer) -> ProviderOffer:
    """Fetch a completed CALL-E call and extract its structured result.

    Prefers CALL-E's own ``structured_result`` (we sent it a schema); falls back
    to LLM extraction from the transcript when that is missing.
    """
    if not offer.call_id:
        return offer
    try:
        data = await get_call(offer.call_id)
        transcript = data.get("transcript") or ""
        offer.raw_transcript = transcript
        parsed = _parse_structured(data)
        if parsed:
            offer.result = parsed
        elif transcript:
            offer.result = await extract_result(transcript, job)
    except CallENotConfigured as exc:
        offer.error = f"voice dispatch unavailable: {exc}"
    except Exception as exc:
        offer.error = str(exc)
        logger.warning("voice dispatch resolve failed for call %s: %s", offer.call_id, exc)
    return offer


def apply_webhook_event(payload: dict) -> Optional[ProviderOffer]:
    """Update an in-flight offer from a CALL-E terminal webhook event.

    Returns the updated offer (if its call_id matched a tracked dispatch) so the
    caller can persist/notify. Dedup of the event itself is the caller's job.
    """
    call_id = payload.get("call_id")
    if not call_id:
        return None
    for job_id, offers in DISPATCH_STATE.items():
        for offer in offers:
            if offer.call_id == call_id:
                transcript = payload.get("transcript") or offer.raw_transcript
                offer.raw_transcript = transcript
                parsed = _parse_structured(payload) or (
                    _parse_structured({"recipients": payload.get("recipients", [])}) if payload.get("recipients") else None
                )
                if parsed:
                    offer.result = parsed
                elif transcript:
                    # LLM extraction needs the Job; defer to a poll if unknown here.
                    pass
                return offer
    return None


def rank_offers(offers: list[ProviderOffer]) -> list[ProviderOffer]:
    """Return offers sorted by price (cheapest valid offer first)."""
    valid = [o for o in offers if o.result.availability and o.result.estimated_price is not None]
    valid.sort(key=lambda o: (o.result.estimated_price or 0))
    return valid


def best_offer(offers: list[ProviderOffer]) -> Optional[ProviderOffer]:
    ranked = rank_offers(offers)
    return ranked[0] if ranked else None

