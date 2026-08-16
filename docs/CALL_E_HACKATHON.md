# ServiceSync Voice — built with CALL-E

> Hackathon submission write-up for **CALL-E: Your Code Is Calling**
> (Devpost). This document is the submission artifact: it explains what we built
> with CALL-E, how the integration is architected, and how to run/demo it.

---

## 1. The problem

Home-service marketplaces (plumbing, electrical, **CCTV / security installs**,
solar…) live or die on **speed of response**. Today the loop looks like this:

1. A customer describes a job.
2. The platform messages a handful of contractors.
3. Contractors reply on their own time — often hours later, half of them never
   answer, and the quotes that come back are inconsistent free text.

The customer abandons the platform; the contractor misses the lead. **The
bottleneck is human latency on the phone.**

## 2. What we built (with CALL-E)

**ServiceSync Voice** uses CALL-E to **place real phone calls to matched
contractors on the customer's behalf**, have a natural conversation about
availability, price, and ETA, and turn each call into a **structured offer** the
customer can compare and book in one tap.

CALL-E is the telephony + voice agent. ServiceSync supplies the *intelligence
around* the call: who to call, what to ask, how to structure the result, how to
rank offers, and how to convert a verified offer into a booked, escrow-backed
job.

### The agentic flow

```
Customer describes a CCTV job (plain language)
  → ServiceSync AI intake → structured brief (cameras, coverage, features, budget)
  → vertical-aware matching → matched CCTV installers
  → ServiceSync Voice (CALL-E) phones each installer:
        "Are you available? Earliest start? Total price + travel fee? What's included?"
  → CALL-E returns a structured result (availability, price, ETA, scope, confidence)
  → ServiceSync ranks offers + flags ambiguous ones for human approval
  → Customer taps "Book this offer" → job booked → escrow deposit → payout
```

Every CALL-E outcome resolves to one canonical schema (`ServiceCallResult`), so
a messy human conversation ("around two, twenty-fiveish") becomes usable,
bookable data.

## 3. How CALL-E is used

- **Outbound calls:** `POST https://api.heycall-e.com/v1/calls` with a `task`
  (the call goal, built from the job + structured brief), a recipient phone, an
  optional `result_schema` (so CALL-E returns structured JSON, not just a
  transcript), an `Idempotency-Key`, and a `webhook_url`.
- **Result retrieval:** `GET /v1/calls/{call_id}` (transcript + `structured_result`).
- **Webhooks:** `POST /calle/webhook` terminal events; CALL-E sends no signature,
  so we dedupe on the `CALL-E-Event-Id` header and reconcile against in-flight
  calls.
- **Auth:** `Bearer $CALL_E_API_KEY`.

We never hardcode a region — CALL-E gets a best-effort country hint only
(`NG`, `US`, …), keeping the product global.

## 4. Architecture / module map (the CALL-E surface)

All CALL-E-specific code is isolated and swappable; the rest of ServiceSync does
not depend on a telephony vendor:

| Concern | File |
|---------|------|
| CALL-E HTTP client (create/get call, auth, `CallENotConfigured` when no key) | `app/services/calle_client.py` |
| Voice orchestration: build task, dispatch, parse result, rank, reconcile webhook | `app/services/voice_dispatch.py` |
| HTTP endpoints: `POST /api/v1/voice/dispatch`, `GET /api/v1/voice/dispatch/{job_id}` | `app/api/v1/endpoints/voice.py` |
| CALL-E terminal webhook: `POST /api/v1/webhooks/calle` (deduped) | `app/api/v1/endpoints/webhooks.py` |
| Live status page + "Book this offer" | `app/web/pages.py` (`/voice/{job_id}`), `app/templates/voice_dispatch.html`, `app/templates/voice_offer_card.html` |
| CCTV vertical wiring: intake → matched installers → CALL-E targets exactly those | `app/api/v1/endpoints/cctv.py`, `app/templates/cctv_intake.html` |

The voice layer depends only on `httpx` (for CALL-E) and the app's own
provider-agnostic LLM abstraction (`app/services/llm.py`) for transcript
extraction fallback. **An LLM is not required for the call itself** — CALL-E
returns the structured result directly.

## 5. Demo scenario (CCTV vertical, end-to-end)

1. Customer opens **/cctv/intake**, types *"4 cameras around my shop, night
   vision, view on my phone, 2 weeks recording"*.
2. ServiceSync AI returns a **structured brief** and a list of **matched CCTV
   installers**.
3. Customer clicks **"Call matched installers by phone"** → ServiceSync Voice
   (CALL-E) places a call to each installer asking availability/price/ETA.
4. The **/voice/{job_id}** page streams each call's structured offer
   (price, earliest start, travel fee, scope, confidence).
5. Customer taps **"Book this offer"** on the best one → job booked → escrow
   deposit → completed → payout.

## 6. Run it

```bash
pip install -r requirements.txt      # httpx is the only CALL-E dependency
cp .env.example .env
# Optional — enable real calls:
#   CALL_E_API_KEY=...
#   CALL_E_WEBHOOK_BASE_URL=https://<your-public-host>   # for live webhooks
uvicorn app.main:app --reload
```

### Demo / offline mode (no CALL-E key)

With `CALL_E_API_KEY` unset, `create_call` raises `CallENotConfigured`; the UI
shows a clear "CALL-E not configured" banner and the dispatch state is
`unavailable` rather than crashing. **The entire flow is still demonstrable** —
intake, matching, the status page, and the booking path all work; only the live
phone calls are stubbed. This is the safest way to review the integration
without a key.

To simulate a completed CALL-E call locally, POST a terminal webhook (the shape
CALL-E sends) to the webhook endpoint; `apply_webhook_event` reconciles it
against the in-flight offer by `call_id`:

```bash
curl -X POST https://<host>/api/v1/webhooks/calle \
  -H "Content-Type: application/json" \
  -d '{"call_id":"<id>","recipients":[{"structured_result":{
        "availability":true,"estimated_price":150000,
        "earliest_time":"tomorrow 9am","service_scope":"4x camera install",
        "travel_fee":5000,"confidence":"high","requires_human_approval":false}}]}'
```

## 7. Testing

`tests/test_phase2_voice_cctv.py` and `tests/test_phase1_cctv.py` exercise the
CCTV + Voice integration with mocked CALL-E/LLM providers (offline, no keys):
dispatch targets the matched contractors, structured results feed back into
booking, and the brief→call context is correct. Full suite: `pytest` (28 tests).

## 8. What's next

- Real CALL-E test call to lock the `result_schema` / `structured_result` shape.
- Persist dispatch state to a DB table (currently in-memory `DISPATCH_STATE`) for
  multi-worker deployments.
- Extend the same voice loop to solar / electrical / HVAC verticals.

## 9. Why this fits "Your Code Is Calling"

CALL-E turns code into action over the phone. ServiceSync Voice is a concrete,
production-shaped example: an AI marketplace that **calls real businesses**,
negotiates availability and price, and closes a transaction — all initiated from
a few lines of backend code and a structured schema. The telephony is fully
abstracted behind a tiny client, so the same agentic pattern ports to any
vertical or region.
