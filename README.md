# ServiceSync

AI-powered operating + marketplace infrastructure for service businesses. The
customer-facing marketplace already exists; the active focus is the **contractor
operating layer** — AI enquiry → quote → booking → payment — starting with the
**CCTV / security** vertical.

## ServiceSync Voice (CALL-E hackathon)

The CALL-E integration — an AI phone dispatcher that calls matched contractors,
captures structured availability/price/ETA offers, and lets customers book in
one tap — is the centerpiece of our **CALL-E: Your Code Is Calling** submission.

> **Submission write-up:** [`docs/CALL_E_HACKATHON.md`](docs/CALL_E_HACKATHON.md)

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # set CALL_E_API_KEY + CALL_E_WEBHOOK_BASE_URL to enable live calls
uvicorn app.main:app --reload
```

With no API keys the app runs in **offline / demo mode** (AI intake and voice
dispatch degrade gracefully; the full CCTV → match → book → escrow flow is still
demonstrable).

## Layout

- `app/services/llm.py` — provider-agnostic LLM backend (Gemini / Groq / Ollama
  via `AI_PROVIDER`; no vendor lock-in).
- `app/services/calle_client.py`, `app/services/voice_dispatch.py` — CALL-E
  client + voice orchestration.
- `app/api/v1/endpoints/{voice,cctv,webhooks}.py` — voice dispatch, CCTV intake,
  CALL-E webhook.
- `app/templates/{cctv_intake,voice_dispatch,voice_offer_card}.html` — UI.
- `docs/ROADMAP.md` — product direction + work log (phased plan).

## Tests

```bash
pytest      # 28 tests; offline, no external services
```
