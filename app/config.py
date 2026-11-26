import os
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # BUSINESS_BOT_TOKEN is the token of @finplan_business_bot. BOT_TOKEN is accepted too,
    # so the service also works when the variable is named as in the personal finplan.
    bot_token: str = Field(default="", validation_alias=AliasChoices("BUSINESS_BOT_TOKEN", "BOT_TOKEN"))
    public_app_url: str = ""
    database_url: str = "sqlite+aiosqlite:///./finplan_business.db"
    debug: bool = False
    dev_telegram_user_id: int | None = None
    webapp_auth_max_age_seconds: int = 86_400
    # Comma-separated Telegram user ids whose businesses always get Team (the owner, testers).
    admin_telegram_ids: str = ""
    # Shown by /paysupport, e.g. "@my_username". Telegram requires bots that sell to offer payment support.
    support_contact: str = ""
    default_timezone: str = "Europe/Kyiv"

    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    # Optional cheaper model for simple jobs (recording operations, categories). Empty = AI_MODEL.
    ai_model_fast: str = ""

    # Fernet key (urlsafe base64, 32 bytes) for bank tokens. Any other string is hashed into a key.
    encryption_key: str = ""

    # Voice messages: any OpenAI-compatible /audio/transcriptions endpoint (OpenAI, Groq, a self-hosted Whisper).
    transcription_api_url: str = ""
    transcription_api_key: str = ""
    transcription_model: str = "whisper-1"

    # Link to the personal finplan Mini App / bot for the "Личное / Бизнес" switch, e.g. https://t.me/finplan_bot/app
    personal_app_url: str = ""
    # How often the monobank statement is pulled, minutes (the bank allows one statement call per minute).
    bank_sync_minutes: int = 30

    @field_validator("bot_token", "anthropic_api_key", "encryption_key", mode="before")
    @classmethod
    def _strip(cls, value: str | None) -> str:
        return (value or "").strip().strip('"').strip("'")

    @field_validator("public_app_url", mode="before")
    @classmethod
    def _normalize_public_url(cls, value: str | None) -> str:
        """Accept `my-app.up.railway.app`, `http://…`, quotes or a trailing slash.

        Falls back to RAILWAY_PUBLIC_DOMAIN, which Railway sets automatically
        once the service has a public domain.
        """
        url = (value or "").strip().strip('"').strip("'").rstrip("/")
        if not url:
            url = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip().rstrip("/")
        if not url:
            return ""
        if url.startswith("http://") and not url.startswith(("http://localhost", "http://127.0.0.1")):
            url = "https://" + url.removeprefix("http://")
        elif not url.startswith(("https://", "http://")):
            url = "https://" + url
        return url

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.admin_telegram_ids.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}

    @property
    def fast_model(self) -> str:
        return self.ai_model_fast or self.ai_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
