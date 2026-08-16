"""Phase 1 — AI quote builder (contractor operating layer).

Given a structured job brief and the contractor's rates, draft a proposal with
line items and a total estimate. Provider-agnostic with an offline fallback.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.services.llm import get_provider

logger = logging.getLogger("services.quote")


class QuoteLineItem(BaseModel):
    description: str
    qty: Optional[int] = None
    unit_price: Optional[float] = None
    total: Optional[float] = None


class JobQuote(BaseModel):
    category: str
    line_items: list[QuoteLineItem] = Field(default_factory=list)
    labor_total: Optional[float] = None
    materials_total: Optional[float] = None
    total_estimate: Optional[float] = None
    currency: str = "USD"
    notes: str = ""
    assumptions: list[str] = Field(default_factory=list)
    confidence: str = "low"


def _strip_code_fences(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()


async def draft_quote(
    brief: dict, contractor, category: str = "cctv", provider=None
) -> JobQuote:
    """Draft a proposal from a structured brief + the contractor's profile/rates."""
    provider = provider or get_provider()
    prof = getattr(contractor, "profession", None) or "CCTV"
    rate = getattr(contractor, "base_pricing", None)
    prompt = (
        f"You are a {prof} contractor preparing a customer quote. "
        f"Your typical labor rate is {rate}. Use the job brief to build a clear, "
        f"itemised proposal.\n\nJob brief (JSON):\n{json.dumps(brief, default=str)}\n\n"
        "Return strict JSON with: line_items (array of {description, qty, "
        "unit_price, total}), labor_total, materials_total, total_estimate, "
        "currency, assumptions (array of strings), notes (string)."
    )

    try:
        text = await provider.complete(prompt, json_mode=True, temperature=0.3)
        data = json.loads(_strip_code_fences(text))
        return JobQuote(
            category=category,
            line_items=[QuoteLineItem(**li) for li in (data.get("line_items") or [])],
            labor_total=data.get("labor_total"),
            materials_total=data.get("materials_total"),
            total_estimate=data.get("total_estimate"),
            currency=data.get("currency") or "USD",
            notes=data.get("notes") or "",
            assumptions=data.get("assumptions") or [],
            confidence="high",
        )
    except Exception as exc:
        logger.warning("quote draft failed, using fallback: %s", exc)
        return JobQuote(
            category=category,
            notes="Could not generate an AI quote. Please prepare a manual quote.",
            confidence="low",
        )
