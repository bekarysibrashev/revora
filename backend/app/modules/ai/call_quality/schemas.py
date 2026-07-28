"""API contracts for versioned call quality rules."""
from datetime import date, datetime
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
    queued: int = 0
    processing: int = 0
    needs_review: int = 0
    failed: int = 0


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
    result: str | None = None
    summary: str | None = None
    needs_review: bool = False
    error_code: str | None = None


class CallListResponse(BaseModel):
    items: list[CallListItem]
    total: int


class EvidenceResponse(BaseModel):
    criterion: str
    timestamp_from: float
    timestamp_to: float
    description: str


class CallAnalysisResponse(BaseModel):
    id: UUID
    call_id: UUID
    status: str
    result: str | None
    score: int | None
    summary: str | None
    criteria_scores: list[dict]
    strengths: list[str]
    loss_reasons: list[str]
    recommendations: list[str]
    flags: dict[str, bool]
    evidence: list[EvidenceResponse]
    languages: list[str]
    mixed_language: bool | None
    confidence: float | None
    needs_review: bool
    attempt_count: int
    error_code: str | None
    model_version: str | None
    completed_at: datetime | None


class ManualTestResponse(BaseModel):
    call_id: UUID
    analysis_id: UUID
    status: str


class OperatorPerformanceItem(BaseModel):
    employee: str
    calls_analyzed: int
    average_score: float
    successful_calls: int
    success_rate: float
    needs_review: int


class OperatorPerformanceResponse(BaseModel):
    date_from: date | None
    date_to: date | None
    items: list[OperatorPerformanceItem]
