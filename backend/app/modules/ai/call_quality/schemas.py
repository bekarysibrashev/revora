"""API contracts for versioned call quality rules."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class CriterionRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    weight: int = Field(ge=1, le=100)
    description: str = Field(min_length=2, max_length=500)


class RuleSetRequest(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    success_definition: str = Field(min_length=5, max_length=3000)
    partial_success_definition: str = Field(min_length=5, max_length=3000)
    loss_definition: str = Field(min_length=5, max_length=3000)
    criteria: list[CriterionRequest] = Field(min_length=1, max_length=20)
    loss_reasons: list[str] = Field(min_length=1, max_length=50)


class RuleSetResponse(RuleSetRequest):
    id: UUID
    version: int
    is_active: bool
    created_at: datetime


class CallQualityStatusResponse(BaseModel):
    rule_set: RuleSetResponse | None
    calls_received: int
    analyses_ready: int
    integration_status: str


class CallListItem(BaseModel):
    id: UUID
    started_at: datetime
    direction: str
    employee: str | None
    phone_masked: str | None
    duration_seconds: int | None
    outcome: str | None
    recording_url: str | None
    analysis_status: str | None
    score: int | None


class CallListResponse(BaseModel):
    items: list[CallListItem]
    total: int
