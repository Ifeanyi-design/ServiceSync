from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import Optional

# Default is intentionally a known-bad placeholder; deployments MUST override it.
_DEFAULT_SECRET_KEY = "supersecretkey_please_change_me_in_production"


class Settings(BaseSettings):
    PROJECT_NAME: str = "ServiceSync"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = _DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7 # 7 days
    
    # Database - Neon Async PostgreSQL URL
    DATABASE_URL: str
    
    # AI Integration
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Monetization / subscription (Phase 7) — commission rules are configurable
    PLATFORM_FEE_PCT_FREE: float = 0.15      # 15% commission on the free tier
    PLATFORM_FEE_PCT_PREMIUM: float = 0.05   # 5% commission on the premium tier
    PREMIUM_TRIAL_DAYS: int = 14             # 14-day premium trial for new contractors
    PREMIUM_MONTHLY_PRICE: float = 29.0      # Displayed premium price (mock billing)
    PREMIUM_SEARCH_BOOST: float = 1000.0     # Trust-score boost applied to premium contractors
    BOOST_SEARCH_BOOST: float = 5000.0       # Paid "Boost" placement (top of results for 24h)
    BOOST_PRICE: float = 9.0                  # Cost of a 24h Boost (paid from earnings)

    # Payout clearing (days funds stay "pending" before becoming withdrawable)
    CLEARING_DAYS: int = 5                   # Free tier clearing window
    PREMIUM_CLEARING_DAYS: int = 2           # Premium tier clearing window (faster)

    # Payments (Stripe Connect). Leave unset to run in demo/mock mode.
    # When STRIPE_SECRET_KEY is present, real card capture + contractor payouts are used.
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_TEST_MODE: bool = True

    # Currency the platform actually charges in. This MUST be a currency enabled
    # on your Stripe account (default USD). All escrow records use this currency;
    # the per-user "display currency" in the UI is presentation-only and does not
    # change what Stripe charges. Keep this consistent everywhere to avoid
    # Stripe "amount_too_small" errors from cross-currency minimums.
    PAYMENT_CURRENCY: str = "USD"
    # Platform-enforced minimum charge (in PAYMENT_CURRENCY) so we never send a
    # sub-minimum amount to the gateway. Stripe's own minimum is ~$0.50.
    MIN_PAYMENT_AMOUNT: float = 1.0

    # Uploads — pick ONE optional backend. Leave all unset to store locally in
    # app/static/uploads (served via /static). Cloudinary and S3 URLs survive
    # server restarts, so they are recommended for hosted deployments.
    CLOUDINARY_URL: Optional[str] = None
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    AWS_S3_BUCKET: Optional[str] = None
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = None
    AWS_S3_CUSTOM_DOMAIN: Optional[str] = None

    # Redis — optional. When set, WebSocket broadcasts fan out across instances
    # via pub/sub. Leave unset to use in-process memory (single instance only).
    REDIS_URL: Optional[str] = None

    # Telegram bot webhook secret (optional). Set via BotFather /setWebhook's
    # secret-token header to authenticate inbound Telegram callbacks.
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None

    # Meta (WhatsApp / Messenger) verify token + app secret for webhook
    # verification and signature validation. Load from env/secret manager —
    # never hardcode.
    META_VERIFY_TOKEN: Optional[str] = None
    META_APP_SECRET: Optional[str] = None

    # WhatsApp Cloud API (Meta Graph). Optional — leave unset to disable WhatsApp.
    WHATSAPP_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None

    # Email (SMTP). Optional — when unset, verification/reset emails are skipped
    # (logged) so the app still runs in demo mode.
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASS: Optional[str] = None
    SMTP_USE_TLS: bool = True
    EMAIL_FROM: str = "noreply@servicesync.app"
    FRONTEND_URL: str = ""  # public base URL used in emailed links, e.g. https://app.onrender.com

    # JWT refresh tokens (DB-backed revocation). Access tokens stay short-lived.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Feature gating — keep OFF by default so existing deployments keep working.
    EMAIL_VERIFICATION_REQUIRED: bool = False
    ADMIN_2FA_REQUIRED: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)

    @model_validator(mode="after")
    def _check_secret_key(self) -> "Settings":
        if self.SECRET_KEY == _DEFAULT_SECRET_KEY:
            # Fail fast: a known placeholder lets anyone forge JWTs.
            raise RuntimeError(
                "SECRET_KEY is still the insecure default. Set a strong random "
                "value (e.g. `python -c \"import secrets;print(secrets.token_urlsafe(32))\"`)."
            )
        if len(self.SECRET_KEY.encode()) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 bytes long.")
        return self


settings = Settings()
