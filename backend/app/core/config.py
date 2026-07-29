"""Типизированная конфигурация Revora из переменных окружения."""

from functools import lru_cache
import json
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Единственный источник runtime-настроек приложения."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Revora API"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_v1_prefix: str = "/api/v1"
    timezone: str = "Asia/Almaty"

    database_url: str = "postgresql+asyncpg://revora:revora@localhost:5432/revora"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "revora"
    minio_secret_key: SecretStr = SecretStr("revora-local-secret")
    minio_secure: bool = False
    minio_bucket: str = "revora"

    jwt_secret_key: SecretStr = SecretStr("local-only-change-me")
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=365)

    # Kcell sends this value in every webhook request. It is set only in Render.
    kcell_crm_token: SecretStr = SecretStr("")
    kcell_tenant_slug: str = "demo"

    # Meta Marketing API is read-only. Secrets live only in the backend runtime.
    meta_access_token: SecretStr = SecretStr("")
    meta_ad_account_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    meta_graph_api_version: str = "v25.0"
    meta_tenant_slug: str = "demo"

    # LLM analyst. The API key never reaches the browser or tenant data tables.
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5.6-terra"
    openai_base_url: str = "https://api.openai.com/v1"
    ai_request_timeout_seconds: int = Field(default=45, ge=5, le=120)
    ai_max_tool_rounds: int = Field(default=4, ge=1, le=8)
    ai_messages_per_minute: int = Field(default=10, ge=1, le=60)

    # Automatic call intelligence. Audio and transcripts are transient.
    # Groq is used separately from the role-scoped OpenAI business analyst.
    call_ai_provider: Literal["openai", "groq"] = "groq"
    groq_api_key: SecretStr = SecretStr("")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    call_transcription_model: str = "whisper-large-v3-turbo"
    call_analysis_model: str = "openai/gpt-oss-20b"
    call_min_duration_seconds: int = Field(default=7, ge=1, le=60)
    call_max_audio_bytes: int = Field(default=25_000_000, ge=1_000_000, le=100_000_000)
    call_analysis_timeout_seconds: int = Field(default=120, ge=15, le=300)
    call_analysis_max_attempts: int = Field(default=3, ge=1, le=10)

    # WhatsApp AI assistant. Production sending stays disabled until explicitly enabled.
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_data_key: SecretStr = SecretStr("")
    meta_app_id: str = ""
    whatsapp_embedded_signup_config_id: str = ""
    whatsapp_tenant_slug: str = "demo"
    whatsapp_graph_api_version: str = "v25.0"
    whatsapp_ai_provider: Literal["rules", "groq", "openai"] = "rules"
    whatsapp_ai_model: str = "openai/gpt-oss-20b"
    whatsapp_ai_auto_send: bool = False
    whatsapp_monthly_budget_kzt: int = Field(default=10_000, ge=0, le=1_000_000)
    whatsapp_max_context_messages: int = Field(default=12, ge=2, le=30)
    whatsapp_usd_kzt_rate: Decimal = Field(default=550, gt=0, le=5000)

    # Отдельный секрет для /platform/* (создание новых клиник) — не JWT, не
    # per-tenant роль. Видит только оператор платформы. Та же логика защиты
    # от дефолтного значения в проде, что и у остальных секретов ниже.
    platform_admin_token: SecretStr = SecretStr("local-only-change-me-platform")

    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:8080",
    ]

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith("/"):
            raise ValueError("API_V1_PREFIX must start with '/'")
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def use_async_postgres_driver(cls, value: object) -> object:
        """Render supplies a plain PostgreSQL URL; the app uses asyncpg."""
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("meta_ad_account_ids", mode="before")
    @classmethod
    def split_meta_ad_account_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [
                account.strip()
                for account in value.split(",")
                if account.strip()
            ]
        return value

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.app_env != "production":
            return self

        insecure_values = {
            self.jwt_secret_key.get_secret_value(),
            self.minio_secret_key.get_secret_value(),
            self.platform_admin_token.get_secret_value(),
        }
        defaults = {"local-only-change-me", "revora-local-secret", "local-only-change-me-platform"}
        if insecure_values & defaults:
            raise ValueError("Production requires unique JWT and MinIO secrets")
        if self.debug:
            raise ValueError("DEBUG must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Возвращает один неизменяемый экземпляр настроек на процесс."""

    return Settings()
