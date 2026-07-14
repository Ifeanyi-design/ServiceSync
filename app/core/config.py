from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "ServiceSync"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = "supersecretkey_please_change_me_in_production"
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
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)

settings = Settings()
