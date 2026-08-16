"""Phase 1 — AI intake (contractor operating layer).

Turns a customer's free-text description into a structured job brief per
vertical. Starts with CCTV; add more categories to ``CATEGORY_PROMPTS``.

The LLM call is provider-agnostic (see app/services/llm.py) and every path has a
safe offline fallback so the app still works with no API keys configured.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.services.llm import get_provider

logger = logging.getLogger("services.intake")


class CCTVJobBrief(BaseModel):
    site_type: Optional[str] = None          # home|business|warehouse|retail|other
    camera_count: Optional[int] = None
    indoor_outdoor: Optional[str] = None     # both|indoor|outdoor
    key_features: list[str] = Field(default_factory=list)
    existing_wiring: Optional[str] = None    # none|partial|full
    internet_available: Optional[bool] = None
    budget_range: Optional[str] = None       # low|mid|high
    urgency: Optional[str] = None            # low|medium|high|emergency
    access_difficulty: Optional[str] = None  # easy|moderate|hard
    notes: str = ""


class JobBrief(BaseModel):
    category: str
    raw_description: str
    cctv: Optional[CCTVJobBrief] = None
    confidence: str = "low"
    requires_review: bool = False


# Vertical -> intake instructions. The model returns strict JSON matching the
# corresponding pydantic model.
CATEGORY_PROMPTS: dict[str, str] = {
    "cctv": (
        "You are an intake specialist for a CCTV / video-surveillance installation "
        "business. Convert the customer's request into a structured job brief. "
        "Extract: site_type (home|business|warehouse|retail|other), "
        "camera_count (integer estimate), indoor_outdoor (both|indoor|outdoor), "
        "key_features (subset of: recording, remote_viewing, night_vision, "
        "motion_alerts, two_way_audio, cloud_storage, local_storage), "
        "existing_wiring (none|partial|full), internet_available (boolean), "
        "budget_range (low|mid|high or null), urgency (low|medium|high|emergency), "
        "access_difficulty (easy|moderate|hard or null), notes (string). "
        "Return strict JSON only."
    ),
}


def _strip_code_fences(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()


async def intake_job(description: str, category: str = "cctv", provider=None) -> JobBrief:
    """Produce a structured JobBrief from a free-text description.

    Falls back to a low-confidence, human-review-required brief when no LLM is
    configured or the call fails — so the flow never breaks offline.
    """
    provider = provider or get_provider()
    instructions = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["cctv"])
    prompt = f"{instructions}\n\nCustomer request:\n{description}"

    try:
        text = await provider.complete(prompt, json_mode=True, temperature=0.2)
        data = json.loads(_strip_code_fences(text))
        if category == "cctv":
            cctv = CCTVJobBrief(**{k: data.get(k) for k in CCTVJobBrief.model_fields})
            return JobBrief(
                category=category, raw_description=description, cctv=cctv,
                confidence="high",
            )
    except Exception as exc:  # offline / model error -> never block the flow
        logger.warning("CCTV intake failed, using fallback brief: %s", exc)

    return JobBrief(
        category=category, raw_description=description, confidence="low",
        requires_review=True,
    )
