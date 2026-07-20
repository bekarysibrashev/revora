import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_are_suitable_for_local_development() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.timezone == "Asia/Almaty"
    assert settings.api_v1_prefix == "/api/v1"


def test_render_postgres_url_uses_asyncpg_driver() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:password@database.example/revora",
    )

    assert settings.database_url == (
        "postgresql+asyncpg://user:password@database.example/revora"
    )


def test_comma_separated_cors_origins_are_supported() -> None:
    settings = Settings(_env_file=None, cors_origins="https://one.test, https://two.test")

    assert settings.cors_origins == ["https://one.test", "https://two.test"]


def test_cors_origins_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://one.test,https://two.test")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["https://one.test", "https://two.test"]


def test_production_rejects_local_secrets() -> None:
    with pytest.raises(ValidationError, match="Production requires unique"):
        Settings(_env_file=None, app_env="production")
