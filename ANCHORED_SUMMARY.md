# Anchored Summary — ServiceSync

_Last updated: 2026-07-18_

## Project at a glance
ServiceSync is an AI contractor marketplace: FastAPI + SQLModel + Neon (Postgres), server-rendered HTMX frontend under `app/web`, deployed on Render. Payments via Stripe escrow (always USD), triage via Gemini, WhatsApp Cloud API inbound. Philosophy: demo-first, graceful degradation when integrations (SMTP/WhatsApp) are unconfigured.

## Deploy status: LIVE ✅
- User set a valid `SECRET_KEY`; app running on Render.
- Gemini triage works; login works.
- **Payment failure (Stripe `amount_too_small`) FIXED.** Root cause: live PaymentIntent was created in the detected locale currency (NGN ₦50 ≈ $0.04) while escrow records are always USD → cross-currency minimum error.
  - Fix: charge currency is now `settings.PAYMENT_CURRENCY` (default USD), consistent everywhere.
  - Platform minimum `MIN_PAYMENT_AMOUNT` (default 1.0) enforced before any gateway call in both `create_job_payment_intent` and `fund_escrow`.
  - Pay UI no longer hardcodes `$` (uses charge-currency symbol); currency selector is display-only with a "you're charged in X" note.
  - Currencies expanded: USD, NGN, GBP, EUR, KES, GHS, ZAR, INR, CAD, AUD, AED, TZS, UGX, SGD (`COUNTRY_CURRENCY_MAP`, `CURRENCY_SYMBOLS`, template options + JS rates/symbols).

## All four approved backlog features — IMPLEMENTED ✅
(Code complete, compiles, 14 smoke tests pass)
1. **JWT refresh + revocation** — `security.py` adds `jti`+`type` to tokens and `create_refresh_token`; `token_service.py` (DB-backed `RevokedToken` revocation, decode, new_code); `get_current_user_optional` checks revocation by `jti`; `auth.py` has `/login` (access+refresh cookie, admin 2FA branch), `/2fa/verify`, `/verify-email`, `/forgot-password`, `/reset-password`, `/refresh` (rotates), `/logout` (revokes).
2. **Email service** — `app/services/email_service.py` (SMTP via stdlib, graceful when unconfigured) + `account_service.py` (verify/reset/2FA shared logic) + wired into API signup and web signup/login.
3. **Admin 2FA** — email-code second step on both web (`/auth/2fa`) and API, gated by `ADMIN_2FA_REQUIRED` or per-user `twofa_enabled`.
4. **WhatsApp Cloud API** — `app/services/whatsapp_service.py` (send + signature verify) + `/api/v1/webhooks/whatsapp` (GET verify, POST signed inbound routed into existing conversation).

## Previously done (still true)
Rate limiting middleware, upload content/MIME validation, broader audit trail (`log_audit` in escrow+auth), Field/time import fixes, `SecurityHeadersMiddleware`, META sig verify, escrow auth checks, privileged-field strip, secure cookies, open-redirect fix, `/escrow/{id}/release` route, chat `[SYSTEM]` pill + repeat-job action.

## New env vars (added to SETUP.md)
`SMTP_HOST/PORT/USER/PASS/USE_TLS`, `EMAIL_FROM`, `FRONTEND_URL`, `EMAIL_VERIFICATION_REQUIRED`, `ADMIN_2FA_REQUIRED`, `REFRESH_TOKEN_EXPIRE_DAYS`, `WHATSAPP_TOKEN/PHONE_NUMBER_ID/APP_SECRET/VERIFY_TOKEN`, `META_VERIFY_TOKEN/META_APP_SECRET`, `PAYMENT_CURRENCY`, `MIN_PAYMENT_AMOUNT`.

## Migration
New alembic migration `p1q2r3s4t5u6_auth_hardening.py` adds `User` columns (`email_verified`, `email_verify_token/expiry`, `reset_token/expiry`, `twofa_enabled/code/expiry`, `wa_id` + index) and `RevokedToken` table. Applied via `alembic upgrade head` on deploy (Render does this).

## Next Move / status
Deploy should now succeed and payments should work (USD). User can optionally set `SMTP_*`, `WHATSAPP_*`, `ADMIN_2FA_REQUIRED` to enable those features. No remaining blockers. All requested items are done.

(End of file)
