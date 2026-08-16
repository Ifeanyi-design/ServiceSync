# ServiceSync — Release-Cut Checklist

Use this when cutting a release of the recovered ServiceSync codebase (AI operating
+ marketplace infrastructure, plus the CALL-E hackathon packaging).

## 1. Pre-flight (code is solid)
- [ ] `python -m pytest` is green on a clean checkout (local sqlite, zero external services).
- [ ] `bandit -r app` and `pip-audit` reviewed (no hardcoded secrets, no known-critical CVEs).
- [ ] No secrets/keys committed (`.env` is git-ignored; `.env.example` only).

## 2. Database migration (REQUIRED before deploy)
The app added new columns and tables after the original schema shipped. `create_all`
won't add columns to an existing DB, so run the idempotent migration on the target:

```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
python scripts/migrate.py
```

It does `CREATE TABLE IF NOT EXISTS` for every model and `ALTER TABLE ... ADD COLUMN
IF NOT EXISTS` for any column missing from existing tables (safe to re-run).

New columns: `users.specialties`, `jobs.category`, `jobs.brief`, `jobs.matched_contractor_ids`.
New tables: `suppliers`, `products`, `job_materials`, `material_orders`.

## 3. Environment / secrets
- [ ] `SECRET_KEY` — strong random, 32+ bytes (fails fast otherwise).
- [ ] `DATABASE_URL` — production Postgres (async driver, e.g. `asyncpg`).
- [ ] `AI_PROVIDER` — `gemini` | `groq` | `ollama`. **Offline/demo mode works with
      zero keys** (all AI paths fall back); pick a provider only when you have a key.
- [ ] `GEMINI_API_KEY` / `GROQ_API_KEY` — only if using those providers.
- [ ] `CALL_E_API_KEY` — only for live ServiceSync Voice calls; `CALL_E_WEBHOOK_BASE_URL`
      must be a **public HTTPS URL** that reaches `/api/v1/calle/webhook`.
- [ ] `PAYSTACK_SECRET_KEY` / `PAYSTACK_PUBLIC_KEY` — required for real escrow
      funding/payouts (the hackathon/demo can run with mocked payments).

## 4. Security gates (already coded — verify they're on)
- [ ] Signup can never self-escalate to `admin` (coerced to `customer`).
- [ ] JWT `token_type` is validated; `2fa_temp` tokens are rejected for normal auth.
- [ ] Banned users are rejected at login and on protected routes.
- [ ] Paystack webhook is auth-checked; escrow funding is idempotent (no double receipt).
- [ ] CALL-E webhook is idempotent (`CALL-E-Event-Id` dedup) — no signature yet; add one before public exposure.

## 5. Feature readiness for a real transaction
| Capability | State | Note |
|-----------|-------|------|
| Customer → describe → match → quote → book → escrow pay → payout | Core flow exists | Reuses the pre-existing booking/escrow/wallet path; validate end-to-end with a live Paystack key |
| CCTV vertical (AI intake + quote + voice dispatch to matched installers) | ✅ | Live voice needs `CALL_E_API_KEY` + public webhook |
| Free-tools funnel (5 calculators) | ✅ | Ad-supported; CTAs funnel into the marketplace |
| Contractor materials board (BOM → order → deliver) | ✅ | Procurement endpoints commit correctly |
| Phase 6 — funnel → real lead conversion | 🔧 started | `GET /tools/request-pro` turns an estimate into a Job lead for signed-in customers |

## 6. Deploy
- [ ] Run migration (step 2).
- [ ] Set env (step 3), start workers, run `uvicorn app.main:app`.
- [ ] Smoke: sign up a customer + contractor, create a job via a free tool, get a quote, book + fund escrow, mark complete, release payout.
- [ ] (Optional) Alembic: replace `scripts/migrate.py` with a proper revision once a baseline migration is established.

## 7. Go-live for ServiceSync Voice (CALL-E)
The voice dispatch code is complete and offline-safe; it only calls CALL-E when a
key is configured. To enable live phone dispatch:
1. Get a `CALL_E_API_KEY` from heycall-e.com (base URL `https://api.heycall-e.com`).
2. Set env:
   - `CALL_E_API_KEY=...`
   - `CALL_E_WEBHOOK_BASE_URL=https://<your-public-host>/api/v1/calle/webhook` — must be
     a **public HTTPS URL** CALL-E can reach. The webhook handler is already at
     `POST /api/v1/calle/webhook` and is idempotent (`CALL-E-Event-Id` dedup).
   - `CALL_E_FROM_PHONE` (optional caller ID) and `CALL-E-Base-URL` (default prod).
3. Trigger dispatch from a CCTV job: the existing `POST /api/v1/voice/{job_id}/dispatch`
   phones the **matched** installers, collects structured offers, and renders them on
   `/voice/{job_id}` where the customer can book an offer.
4. Without a key the calls degrade gracefully (`CallENotConfigured`) — the rest of the
   app is unaffected. (A signature check on the webhook is recommended before public exposure.)

## 8. Push-to-deploy / auto-update
- This repo includes a GitHub Actions CI workflow (`.github/workflows/ci.yml`) that runs
  the offline test suite on every push/pull request, so broken code is caught before it ships.
- Connect your hosting platform (Render / Railway / Fly / Heroku / etc.) to this GitHub
  repo with git-based deploys — once connected, **every push to the default branch
  automatically rebuilds and redeploys** the app (the "code automatically updates").
- First deploy on a new database: run `python scripts/migrate.py` (step 2) once.
- `Procfile` and `requirements.txt` are present for buildpack-based platforms.
- Ensure the platform sets the production env (step 3) — especially `SECRET_KEY`,
  `DATABASE_URL`, and the Paystack/CALL-E keys when going live.

