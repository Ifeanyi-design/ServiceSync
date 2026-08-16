# ServiceSync Voice — CALL-E Setup & Run Guide

> Companion to [`CALL_E_HACKATHON.md`](./CALL_E_HACKATHON.md). This is the
> **operational** guide: how to install CALL-E, configure the env vars, and make a
> real (or simulated) phone call through ServiceSync Voice. It follows the official
> **CALL-E Integrations** repo / Developer API
> (https://github.com/CALLE-AI/call-e-integrations, https://docs.heycall-e.com).

---

## 0. Which CALL-E repo is which (don't mix them up)

| Repo | What it's for |
|------|--------------|
| **CALL-E Integrations** (`CALLE-AI/call-e-integrations`) | The **tooling** you build with: SDK, API reference, MCP/CLI/SKILL quickstarts, runnable examples. **Use this to set up.** |
| **Awesome Phone Call Agents** (`CALLE-AI/awesome-phone-call-agents`) | The **gallery** you **submit** your finished hackathon project to. |

You develop against the Integrations repo and submit to Awesome Phone Call Agents.

---

## 1. Install

ServiceSync Voice already talks to CALL-E over its Developer API. Two options:

**A. Use our bundled client (default, offline-safe).** No extra package — it uses
`httpx` (already a dependency). Works with zero keys (demo mode) and needs only
`CALL_E_API_KEY` for live calls.

**B. Use the official Python SDK (`calle-ai`).** Recommended by the Integrations
repo; equivalent call shape. Install it if you want the typed SDK:

```bash
pip install calle-ai
```

Both paths hit the same endpoints:
`POST /v1/calls`, `GET /v1/calls/{call_id}`, `GET /v1/calls/{call_id}/events`,
`POST /calle/webhook`.

---

## 2. Configure environment

Copy the example and fill in the key (the rest are optional):

```bash
cp .env.example .env
```

| Variable | Required | Notes |
|----------|----------|-------|
| `CALL_E_API_KEY` | **yes** (for live calls) | Get it from the CALL-E dashboard (https://dashboard.heycall-e.com/account/api-keys). Without it, the app stays in demo mode. |
| `CALL_E_BASE_URL` | no | Defaults to `https://api.heycall-e.com`. Override only if CALL-E gives you a different base. |
| `CALL_E_WEBHOOK_BASE_URL` | no* | Your **public** host, e.g. `https://servicesync.onrender.com`. CALL-E posts terminal results to `{base}/api/v1/webhooks/calle`. *Skip if you use polling instead (see §5). |
| `CALL_E_FROM_PHONE` | no | Optional caller-ID / from-number if CALL-E requires one for your region. |

> Auth is `Authorization: Bearer $CALL_E_API_KEY`. Each create call also sends an
> `Idempotency-Key` (`servicesync:job:{job_id}:contractor:{contractor_id}`) so
> retries never place a duplicate call.

---

## 3. The call contract (real CALL-E shape)

**Request** (`app/services/calle_client.py` → `create_call`):

```json
{
  "task": "You are calling <name> on behalf of a ServiceSync customer. The customer needs: <job>. Confirm availability, price, travel fee, scope+warranty.",
  "recipients": [ { "phones": ["+14155550100"], "region": "US", "locale": "en-US" } ],
  "result_schema":        { "type": "object", "properties": { "contacted_count": {"type":"integer"}, "accepted_count": {"type":"integer"} } },
  "recipient_result_schema": {
    "type": "object",
    "required": ["availability"],
    "properties": {
      "availability": {"type": ["boolean","null"]},
      "earliest_time": {"type": ["string","null"]},
      "estimated_price": {"type": ["number","null"]},
      "service_scope": {"type": ["string","null"]},
      "travel_fee": {"type": ["number","null"]},
      "warranty": {"type": ["string","null"]},
      "confidence": {"type": "string", "enum": ["high","medium","low"]},
      "evidence": {"type": "string"},
      "requires_human_approval": {"type": "boolean"}
    }
  },
  "idempotency_key": "servicesync:job:12:contractor:7",
  "webhook_url": "https://servicesync.onrender.com/api/v1/webhooks/calle"
}
```

**Response** (`GET /v1/calls/{call_id}` or terminal webhook):

```json
{
  "status": "completed",
  "task_completed": true,
  "completion_confidence": { "score": 0.92, "label": "high" },
  "evidence": ["The provider said they can start tomorrow at 9am for ₦150000."],
  "structured_result": { "contacted_count": 1, "accepted_count": 1 },
  "recipients": [
    {
      "structured_result": {
        "availability": true,
        "earliest_time": "tomorrow 9am",
        "estimated_price": 150000,
        "service_scope": "4x camera install",
        "travel_fee": 5000,
        "warranty": "1 year",
        "confidence": "high",
        "evidence": "Provider confirmed availability and price.",
        "requires_human_approval": false
      },
      "attempts": [ { "transcript_turns": [ {"speaker":"bot","text":"..."}, {"speaker":"user","text":"..."} ] } ]
    }
  ]
}
```

ServiceSync reads the **per-recipient** result (`recipients[0].structured_result`)
into its canonical `ServiceCallResult` (`_parse_structured` in
`app/services/voice_dispatch.py`), so the structured offer feeds straight into
ranking + booking. If `recipients[].structured_result` is missing we fall back to
LLM extraction from the transcript.

---

## 4. Make a live test call

### Easiest end-to-end (UI)
1. Set `CALL_E_API_KEY` and run `uvicorn app.main:app --reload`.
2. Make sure the target contractor has a real `phone` on their profile.
3. Create a CCTV job: open `/cctv/intake`, submit a description, get matched
   installers.
4. Open `/voice/{job_id}` and click **"Call matched installers by phone"**
   (`POST /api/v1/voice/dispatch/{job_id}`). CALL-E dials each installer.
5. The page shows each call's structured offer; tap **Book this offer** to close.

### Headless (script) — using our client
```python
import asyncio
from app.core.database import async_session_maker
from sqlmodel import select
from app.models.all_models import Job, User
from app.services.calle_client import create_call

async def main():
    async with async_session_maker() as db:
        job = (await db.exec(select(Job).where(Job.category == "cctv"))).first()
        contractor = (await db.exec(select(User).where(User.role == "contractor"))).first()
    call_id = await create_call(
        task=f"Call {contractor.full_name} about job: {job.description}. Confirm availability, price, travel fee, scope.",
        phone=contractor.phone,
        region="NG",
        locale="en-US",
    )
    print("placed call:", call_id)

asyncio.run(main())
```

### Headless — using the official SDK (`calle-ai`)
```python
from calle_ai import CalleClient
client = CalleClient({"api_key": "<CALLE_API_KEY>"})
call = client.calls.create_and_wait(
    task="Call +14155550100 and confirm availability + price for a CCTV install.",
    recipients=[{"phones": ["+14155550100"], "region": "US", "locale": "en-US"}],
    result_schema={"type":"object","properties":{"contacted_count":{"type":"integer"},"accepted_count":{"type":"integer"}}},
    recipient_result_schema={ "type":"object","required":["availability"],
        "properties":{ "availability":{"type":["boolean","null"]}, "estimated_price":{"type":["number","null"]} } },
    idempotency_key="servicesync:test:1",
)
print(call["status"], call["recipients"][0]["structured_result"])
```

---

## 5. Webhooks vs polling

- **Webhooks (preferred in prod):** set `CALL_E_WEBHOOK_BASE_URL` to your public
  host. CALL-E POSTs terminal events to `/api/v1/webhooks/calle` (no signature —
  we dedupe on the `CALL-E-Event-Id` header in
  `app/api/v1/endpoints/webhooks.py`). This reconciles the offer without polling.
- **Polling (no public host needed):** if `CALL_E_WEBHOOK_BASE_URL` is unset, the
  `/voice/{job_id}` page polls `GET /v1/calls/{call_id}` via
  `resolve_offer` and reconciles the structured result. Great for local testing
  behind a firewall / `localhost`.

---

## 6. Offline / demo mode (no key)

With `CALL_E_API_KEY` unset, `create_call` raises `CallENotConfigured`; the UI
shows a "CALL-E not configured" banner and dispatch state is `unavailable` rather
than crashing. The entire rest of the flow (intake → match → status page →
booking) still works with the structured result **simulated**. To simulate a
completed CALL-E webhook locally:

```bash
curl -X POST https://<host>/api/v1/webhooks/calle \
  -H "Content-Type: application/json" \
  -d '{"call_id":"<id>","recipients":[{"structured_result":{
       "availability":true,"estimated_price":150000,
       "earliest_time":"tomorrow 9am","service_scope":"4x camera install",
       "travel_fee":5000,"confidence":"high","requires_human_approval":false}}]}'
```

---

## 7. Run the tests

```bash
pytest tests/test_phase2_voice_cctv.py tests/test_phase1_cctv.py -q
```
These exercise dispatch + structured-result handling with CALL-E/LLM mocked
(offline). Full suite: `pytest`.

---

## 8. Submit

When live-tested, submit the project to **Awesome Phone Call Agents**
(`CALLE-AI/awesome-phone-call-agents`) before **Sep 14 2026**, referencing this
repo and [`CALL_E_HACKATHON.md`](./CALL_E_HACKATHON.md).
