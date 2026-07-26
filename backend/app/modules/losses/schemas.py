from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


LossStatus = Literal["open", "in_progress", "recovered", "dismissed"]


class LossOpportunityResponse(BaseModel):
    id: UUID
    branch_id: UUID | None
    assigned_user_id: UUID | None
    loss_type: str
    severity: str
    status: str
    title: str
    description: str
    recommended_action: str
    entity_type: str | None
    entity_id: UUID | None
    estimated_amount: Decimal
    recovered_amount: Decimal
    currency: str
    confidence: Decimal
    evidence: dict[str, object]
    detected_at: datetime
    last_detected_at: datetime


class LossMapSummary(BaseModel):
    estimated_total: Decimal
    recovered_total: Decimal
    open_count: int
    in_progress_count: int
    recovered_count: int
    critical_count: int


class LossMapResponse(BaseModel):
    summary: LossMapSummary
    items: list[LossOpportunityResponse]
    total: int
    date_from: date
    date_to: date
    branch_id: UUID | None
    generated_at: datetime


class LossRefreshResponse(LossMapResponse):
    detected: int


class LossUpdateRequest(BaseModel):
    status: LossStatus
    recovered_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    assigned_user_id: UUID | None = None
