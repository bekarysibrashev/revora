"""Authentication API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.models import UserRole


class LoginRequest(BaseModel):
    tenant_slug: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("tenant_slug", "email")
    @classmethod
    def normalize_identifiers(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class LogoutRequest(RefreshRequest):
    pass


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    email: str
    full_name: str
    role: UserRole
    branch_ids: list[UUID] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


class MessageResponse(BaseModel):
    message: str
