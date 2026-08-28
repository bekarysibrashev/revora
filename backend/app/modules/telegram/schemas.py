"""Validated API contracts for Telegram administration and task assignment."""

from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.auth.models import UserRole
from app.modules.telegram.models import TelegramReportCadence, TelegramTaskPriority, TelegramTaskStatus


class InvitationCreateRequest(BaseModel):
    role: UserRole
    branch_id: UUID | None = None
    expires_in_hours: int = Field(default=24, ge=1, le=168)
    max_uses: int = Field(default=1, ge=1, le=20)


class InvitationResponse(BaseModel):
    id: UUID
    code: str
    code_hint: str
    role: UserRole
    branch_id: UUID | None
    expires_at: datetime
    max_uses: int


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID | None
    role: UserRole
    telegram_user_id: int
    username: str | None
    full_name: str
    is_active: bool
    registered_at: datetime
    last_seen_at: datetime


class EmployeeListResponse(BaseModel):
    items: list[EmployeeResponse]
    total: int


class EmployeeUpdateRequest(BaseModel):
    is_active: bool | None = None
    role: UserRole | None = None
    branch_id: UUID | None = None

    @model_validator(mode="after")
    def require_changes(self) -> "EmployeeUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class TaskCreateRequest(BaseModel):
    employee_id: UUID
    title: str = Field(min_length=2, max_length=250)
    description: str = Field(min_length=1, max_length=4000)
    priority: TelegramTaskPriority = TelegramTaskPriority.NORMAL
    due_at: datetime | None = None

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    title: str
    description: str
    priority: TelegramTaskPriority
    status: TelegramTaskStatus
    due_at: datetime | None
    delivered_at: datetime | None
    accepted_at: datetime | None
    completed_at: datetime | None
    completion_note: str | None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int


class ReportSubscriptionRequest(BaseModel):
    cadence: TelegramReportCadence
    local_time: time
    weekday: int | None = Field(default=None, ge=0, le=6)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_weekday(self) -> "ReportSubscriptionRequest":
        if self.cadence == TelegramReportCadence.WEEKLY and self.weekday is None:
            raise ValueError("weekday is required for a weekly report")
        if self.cadence == TelegramReportCadence.DAILY:
            self.weekday = None
        return self
