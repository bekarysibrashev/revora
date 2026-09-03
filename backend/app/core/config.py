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
    login_max_attempts: int = Field(default=5, ge=3, le=10)
    login_lock_minutes: int = Field(default=15, ge=1, le=1440)

    # Bootstrap an empty production database after infrastructure replacement.
    # Render runs initialDeployHook only when the web service itself is first
    # created, so replacing only PostgreSQL would otherwise leave no tenant or
    # owner account behind.
    initial_owner_email: str = ""
    initial_owner_password: SecretStr = SecretStr("")
    initial_tenant_name: str = "SAN Dental"
    initial_tenant_slug: str = "sandental"
    initial_branch_name: str = "Сейфуллина"
    initial_branch_code: str = "seifullina"
    initial_extra_branch_name: str = "Батыс Мура"
    initial_extra_branch_code: str = "batys-mura"

    # Kcell sends this value in every webhook request. It is set only in Render.
    kcell_crm_token: SecretStr = SecretStr("")
    kcell_tenant_slug: str = "demo"

    # Meta Marketing API is read-only. Secrets live only in the backend runtime.
    meta_access_token: SecretStr = SecretStr("")
    meta_ad_account_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    meta_graph_api_version: str = "v25.0"
    meta_tenant_slug: str = "demo"
    meta_attribution_windows: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["7d_click", "1d_view"]
    )
    meta_action_report_time: Literal["impression", "conversion", "mixed"] = "impression"
    meta_auto_sync_enabled: bool = False
    meta_auto_sync_interval_minutes: int = Field(default=180, ge=15, le=1440)
    meta_auto_sync_lookback_days: int = Field(default=30, ge=1, le=90)

    # LLM analyst. The API key never reaches the browser or tenant data tables.
    analyst_ai_provider: Literal["openai", "groq"] = "groq"
    analyst_ai_model: str = "openai/gpt-oss-120b"
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
    call_min_duration_seconds: int = Field(default=10, ge=1, le=60)
    call_max_audio_bytes: int = Field(default=25_000_000, ge=1_000_000, le=100_000_000)
    call_analysis_timeout_seconds: int = Field(default=120, ge=15, le=300)
    call_analysis_max_attempts: int = Field(default=3, ge=1, le=10)
    embedded_call_worker: bool = False
    embedded_call_worker_interval_seconds: int = Field(default=20, ge=5, le=300)
    embedded_call_processing_timeout_minutes: int = Field(default=15, ge=5, le=120)

    # WhatsApp AI assistant. Production sending stays disabled until explicitly enabled.
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_data_key: SecretStr = SecretStr("")
    meta_app_id: str = "965678616515017"
    whatsapp_embedded_signup_config_id: str = "2277685509673688"
    whatsapp_tenant_slug: str = "demo"
    whatsapp_graph_api_version: str = "v25.0"
    whatsapp_ai_provider: Literal["rules", "groq", "openai"] = "rules"
    whatsapp_ai_model: str = "openai/gpt-oss-20b"
    whatsapp_ai_auto_send: bool = False
    whatsapp_monthly_budget_kzt: int = Field(default=10_000, ge=0, le=1_000_000)
    whatsapp_max_context_messages: int = Field(default=12, ge=2, le=30)
    whatsapp_usd_kzt_rate: Decimal = Field(default=550, gt=0, le=5000)
    # Unofficial linked-device gateway used by the zero-subscription QR pilot.
    # The shared secret authenticates only server-to-server traffic.
    whatsapp_qr_gateway_url: str = ""
    whatsapp_qr_gateway_secret: SecretStr = SecretStr("")
    whatsapp_admin_pause_minutes: int = Field(default=60, ge=5, le=1440)

    # Telegram staff bot. The token is configured only in the bot process.
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_poll_timeout_seconds: int = Field(default=25, ge=5, le=50)

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

    @field_validator("meta_ad_account_ids", "meta_attribution_windows", mode="before")
    @classmethod
    def split_meta_lists(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("meta_attribution_windows")
    @classmethod
    def validate_meta_attribution_windows(cls, value: list[str]) -> list[str]:
        allowed = {"1d_click", "7d_click", "28d_click", "1d_view", "7d_view", "28d_view"}
        if not value or any(item not in allowed for item in value):
            raise ValueError("META_ATTRIBUTION_WINDOWS contains an unsupported window")
        return list(dict.fromkeys(value))

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
