# Anchored Summary — ServiceSync

_Last updated: 2026-07-18_

## Project at a glance
ServiceSync is a FastAPI platform for home-service job matching with escrow payments, WhatsApp triage, contractor marketplaces, and admin tooling. Backend: FastAPI + SQLAlchemy (Alembic migrations) + JWT auth. Frontend: server-rendered Starlette/HTMX pages under `app/web`. Tests: pytest (`tests/`, `pytest.ini`).

## Recently completed (merged in)
- **Rate limiting middleware** (`app/main.py`): `RateLimitMiddleware`, per-IP in-memory limiter. Protects `/auth/login`, `/auth/signup`, `/api/v1/auth/login`, `/api/v1/auth/signup`, `/api/v1/chat/triage`. Exempts `/static`, `/health`, `/api/v1/webhooks`.
- **Upload content validation** (`app/services/upload_service.py`): `_validate_content` does magic-byte sniff for images + `%PDF` header check; rejects spoofed extensions.
- **Broader audit trail** (`app/services/audit_service.py`): new `log_audit` reusing the existing `AIOperationsAuditLog` table (no migration needed). Wired into `app/api/v1/endpoints/escrow.py` (release, cancel, dispute_resolve) and `app/api/v1/endpoints/auth.py` (login_success, login_failed).
- **Tests** (`tests/test_smoke.py`): `test_upload_rejects_spoofed_extension`, `test_upload_accepts_real_png`. All compile clean.

## Blocked
- **Deploy blocker — SECRET_KEY < 32 bytes (fail-fast validator).** `app/core/config.py:83-84` raises `RuntimeError("SECRET_KEY must be at least 32 bytes long.")`. Render env must be fixed (set a real ≥32-byte SECRET_KEY) before deploy succeeds. Status: **Blocked**.

## Active (remaining approved backlog)
- Email verification + password-reset (SMTP)
- Admin 2FA / provisioning
- JWT revocation / refresh tokens
- Full pytest suite (partially started)
- WhatsApp Cloud API integration

## Next Move
User must set `SECRET_KEY` in Render (≥32 bytes) to unblock deploy. Then continue the backlog — ask the user to prioritize the larger remaining features (each needs a config/product decision):
1. Email verification + password-reset (SMTP) — needs SMTP provider/credentials decision.
2. Admin 2FA / provisioning — needs 2FA method decision (TOTP vs SMS).
3. JWT revocation / refresh tokens — needs token store decision (DB vs Redis).
4. Full pytest suite — expand `tests/` coverage.
5. WhatsApp Cloud API integration — needs business account / webhook config.
