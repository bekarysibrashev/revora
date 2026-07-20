"""API contracts for clinic administration."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.auth.models import UserRole


class BranchCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    address: str | None = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("address", mode="before")
    @classmethod
    def normalize_address(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class BranchUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("address", mode="before")
    @classmethod
    def normalize_address(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def require_changes(self) -> "BranchUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    address: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BranchListResponse(BaseModel):
    items: list[BranchResponse]
    total: int


class AdminUserCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole
    branch_ids: list[UUID] = Field(default_factory=list)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminUserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    branch_ids: list[UUID] | None = None
    is_active: bool | None = None

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_changes(self) -> "AdminUserUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class AdminUserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    branch_ids: list[UUID]
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int
