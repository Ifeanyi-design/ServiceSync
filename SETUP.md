# ServiceSync — Setup, Environment & Testing Guide

This guide explains every environment variable, where to get the keys, why each
is needed, and how to run + test the app (demo mode needs **none** of them).

---

## 0. Demo mode (default — zero config)

Clone, create a venv, install, and run:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head          # create tables (needs DATABASE_URL, see below)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

With only `DATABASE_URL` set, **everything works in mock mode**:
- Payments are simulated (no real charges). Stripe card form is the demo UI.
- Uploads go to `app/static/uploads` (local).
- AI dispute analysis uses the built-in 50% fallback (no Gemini key needed).
- WebSocket chat works in-process (no Redis needed).

So you can demo the full flow — book, fund escrow, message, dispute, resolve —
without signing up for any external service.

---

## 1. Environment variables (`.env` at project root)

All are **optional**. `app/core/config.py` reads them from `.env` (or real env).

| Variable | Required? | Where to get it | Why / what it enables |
|---|---|---|---|
| `DATABASE_URL` | **Yes** | Neon: *Dashboard → your project → Connect → Python/asyncpg* → copy the `postgresql+asyncpg://...` URL | Async Postgres. The only hard requirement. |
| `SECRET_KEY` | Recommended | Any random string (`python -c "import secrets;print(secrets.token_urlsafe(32))"`) | JWT signing. Change the insecure default before any real deploy. |
| `GEMINI_API_KEY` | Optional | Google AI Studio → API keys | Real AI dispute analysis, price estimates, triage, contractor auto-replies. Without it, the app uses sensible offline fallbacks. |
| `STRIPE_SECRET_KEY` | Optional (for live payments) | Stripe Dashboard → Developers → API keys → **Secret** key (test `sk_test_…`) | Enables **real** card capture. When set (with the publishable key), the pay screen switches from the demo form to real Stripe Elements. Leave unset = demo/mock. |
| `STRIPE_PUBLISHABLE_KEY` | Optional | Stripe Dashboard → Developers → API keys → **Publishable** key (`pk_test_…`) | Client-side Stripe.js. Must be set together with `STRIPE_SECRET_KEY` to go live. |
| `STRIPE_WEBHOOK_SECRET` | Optional (live only) | `stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe` prints `whsec_…` | Verifies webhook signatures so Stripe events (payment succeeded/refunded) update escrow status. |
| `STRIPE_TEST_MODE` | Optional | `true` (default) | Keep `true` while using test keys. |
| `CLOUDINARY_URL` (or `CLOUDINARY_CLOUD_NAME`+`API_KEY`+`API_SECRET`) | Optional | Cloudinary console → Dashboard | Persists chat/avatar uploads to Cloudinary CDN (survives server restarts). If unset, uploads stay local. |
| `AWS_S3_BUCKET` (+ `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`) | Optional | AWS S3 | Alternative persistent storage for uploads. Used only if set and Cloudinary is not. |
| `REDIS_URL` | Optional (multi-instance only) | Render → Redis instance, or any `redis://` URL | Cross-instance WebSocket broadcast via pub/sub. If unset, chat works in-process (fine for a single instance / demo). |
| `PREMIUM_*` / `CLEARING_DAYS` | Optional | n/a (configured in code) | Commission %, trial length, payout clearing window. Safe defaults provided. |

**Minimal `.env` for local dev:**
```ini
DATABASE_URL=postgresql+asyncpg://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb
SECRET_KEY=change-me-to-a-random-string
# GEMINI_API_KEY=...        (optional)
# STRIPE_SECRET_KEY=...     (optional — only for live payments)
# STRIPE_PUBLISHABLE_KEY=... (optional)
# REDIS_URL=...             (optional)
```

---

## 2. Going live with Stripe (real money)

1. Create a Stripe account. Get **test** keys first (Dashboard → Developers → API keys).
2. Put `STRIPE_SECRET_KEY` + `STRIPE_PUBLISHABLE_KEY` in `.env`. On next load the pay
   screen automatically mounts Stripe Elements (the demo card form is hidden).
3. Run the Stripe CLI to forward webhooks locally:
   ```powershell
   stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe
   ```
   Copy the printed `whsec_…` into `STRIPE_WEBHOOK_SECRET`. This keeps `Escrow.status`
   in sync (succeeded → `held`, refunded → `refunded`).
4. In production, register the webhook endpoint in the Stripe Dashboard pointing at
   `https://<your-domain>/api/v1/webhooks/stripe` (same signing secret).
5. **Contractor payouts (Stripe Connect):** a contractor clicks *Connect* on their
   dashboard → account is created and `stripe_account_id` stored → they complete
   onboarding via the returned link. Releases then pay out to their Connect account.

> Remember: test keys only move test money. Use `4242 4242 4242 4242` even in live-UI
> mode when `STRIPE_TEST_MODE=true`.

---

## 3. External services summary

| Service | Needed for | Free tier? | Signup |
|---|---|---|---|
| Neon Postgres | Database (required) | Yes | neon.tech |
| Stripe | Real payments + contractor payouts | Test mode free | stripe.com |
| Google Gemini | AI features | Free tier | aistudio.google.com |
| Cloudinary / AWS S3 | Durable uploads | Yes | cloudinary.com / aws.amazon.com |
| Redis | Multi-instance chat | Yes (Render) | render.com |
| pytest | Tests (dev only) | n/a | `pip install -r requirements.txt` |

---

## 4. Testing

### 4.1 Automated smoke tests
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt      # includes pytest, pytest-asyncio
pytest                              # 9 smoke tests: import, /health, routes,
                                    # upload helper, Redis fallback, escrow rules
```
These need **no live DB/keys** — they use mocks. They verify: app builds, `/health`
responds, key routes are registered, the upload helper falls back to local storage
and rejects bad types, the broadcast hub works without Redis, and the core escrow
state-machine rules (no double-funding, disputed escrows can't be force-released,
penalty split allowed from disputed).

### 4.2 Manual end-to-end (demo mode)
1. `uvicorn app.main:app --reload`
2. Sign up as a **Customer** and as a **Contractor** (two browsers / incognito).
3. Customer: search → pick a contractor → message → start a job (creates booking + escrow `unfunded`).
4. Customer: open the job → **Fund Escrow** (demo card `4242…`) → escrow `held`, receipt shown.
5. Contractor: start job → mark complete. Customer: confirm → escrow `released`, contractor wallet credited (pending).
6. Dispute: customer opens a dispute on a held escrow → AI recommendation is generated and shown on `/admin` → admin resolves with a refund % → escrow `refunded`/`penalty_split` and `Job.status` updated.
7. Admin: `/admin` shows stats; verify/approve contractors; force-refund a held escrow.
8. Mobile: open the customer dashboard and pay screen at ~375px width — text should wrap, no horizontal overflow, icons render (no emoji).

### 4.3 Health probe for hosting
`GET /health` returns `{"status":"ok", ...}` — point Render's health check there.

---

## 5. Deploy checklist (Render)
- Build: `pip install -r requirements.txt`
- Migrate: `alembic upgrade head` (Neon cold-starts can be slow; allow a long timeout)
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Set the env vars above in the Render dashboard.
- Add `REDIS_URL` only if you scale to >1 instance.
- Static uploads on Render's free tier are **ephemeral** — set Cloudinary or S3 so
  chat/avatar files survive restarts.
