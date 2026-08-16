"""CALL-E Developer API client for ServiceSync Voice.

Matches the official CALL-E Developer API (https://docs.heycall-e.com):

    POST /v1/calls            Create a call task (one recipient or batch)
    GET  /v1/calls/{call_id} Read status, summary, structured result, transcript
    GET  /v1/calls/{call_id}/events   List developer events
    POST /calle/webhook       Terminal result webhooks (no signature; dedup
                              via the CALL-E-Event-Id header)

A call is described by a free-text ``task`` (the call goal) plus a list of
``recipients`` (E.164 phones). An optional JSON ``result_schema`` asks CALL-E
to return the outcome as structured data — which we map onto our
``ServiceCallResult`` schema, removing the need to parse the transcript.

Configure with ``CALL_E_API_KEY`` (+ optional ``CALL_E_BASE_URL`` /
``CALL_E_FROM_PHONE``). Until set, ``create_call`` / ``get_call`` raise
``CallENotConfigured`` so demo mode keeps working.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("services.calle")

# Official CALL-E Developer API base (override via CALL_E_BASE_URL if needed).
DEFAULT_BASE_URL = "https://api.heycall-e.com"


class CallENotConfigured(RuntimeError):
    """Raised when CALL-E is not enabled (no API key)."""


def _base() -> str:
    return (settings.CALL_E_BASE_URL or DEFAULT_BASE_URL).rstrip("/")


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.CALL_E_API_KEY}"}


async def create_call(
    task: str,
    phone: str,
    *,
    region: Optional[str] = None,
    locale: Optional[str] = None,
    result_schema: Optional[dict] = None,
    idempotency_key: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> str:
    """Create a CALL-E call task for one provider. Returns the call id."""
    if not settings.CALL_E_API_KEY:
        raise CallENotConfigured("CALL_E_API_KEY is not set")
    if not phone:
        raise ValueError("provider phone number is required to place a call")

    recipient: dict = {"phones": [phone]}
    if region:
        recipient["region"] = region
    if locale:
        recipient["locale"] = locale

    body: dict = {"task": task, "recipients": [recipient]}
    if result_schema:
        body["result_schema"] = result_schema
    if webhook_url:
        body["webhook_url"] = webhook_url
    if settings.CALL_E_FROM_PHONE:
        body["from"] = settings.CALL_E_FROM_PHONE

    headers = _headers()
    headers["Idempotency-Key"] = idempotency_key or f"servicesync:{uuid.uuid4().hex}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{_base()}/v1/calls", headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        call_id = data.get("call_id") or data.get("id")
        if not call_id:
            raise RuntimeError(f"CALL-E did not return a call id: {data}")
        return call_id


async def get_call(call_id: str) -> dict:
    """Read a call task's status, summary, structured result, and transcript."""
    if not settings.CALL_E_API_KEY:
        raise CallENotConfigured("CALL_E_API_KEY is not set")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{_base()}/v1/calls/{call_id}", headers=_headers())
        resp.raise_for_status()
        return resp.json()
