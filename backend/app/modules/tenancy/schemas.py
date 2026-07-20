"""API contracts for platform (cross-tenant) clinic provisioning."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenantCreateRequest(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=200)
    tenant_slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    branch_name: str = Field(min_length=2, max_length=200)
    branch_code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    owner_email: str = Field(min_length=3, max_length=320)
    owner_full_name: str = Field(min_length=2, max_length=200)
    owner_password: str = Field(min_length=8, max_length=128)

    @field_validator("tenant_name", "branch_name", "owner_full_name", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("tenant_slug", "branch_code", mode="before")
    @classmethod
    def normalize_slug(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("owner_email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TenantListResponse(BaseModel):
    items: list[TenantResponse]
    total: int


class TenantCreateResponse(BaseModel):
    """Отдельно от TenantResponse: возвращаем ещё email владельца и код
    филиала — то, что оператор платформы вводил в форму и должен увидеть
    в подтверждении (пароль в ответе не возвращаем — только что создан,
    но это секрет)."""

    tenant: TenantResponse
    branch_code: str
    owner_email: str
