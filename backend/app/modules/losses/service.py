from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.losses.repository import LossRepository
from app.modules.losses.schemas import (
    LossMapResponse,
    LossMapSummary,
    LossOpportunityResponse,
    LossRefreshResponse,
    LossUpdateRequest,
)

ZERO = Decimal("0")


class LossService:
    def __init__(self, repository: LossRepository) -> None:
        self.repository = repository

    async def refresh(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> LossRefreshResponse:
        self._validate(user, date_from, date_to, branch_id)
        candidates = await self.repository.detect(
            user.tenant_id, date_from, date_to, branch_id
        )
        detected = await self.repository.upsert(
            user.tenant_id, candidates, date_from, date_to
        )
        response = await self.map(user, date_from, date_to, branch_id)
        return LossRefreshResponse(**response.model_dump(), detected=detected)

    async def map(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> LossMapResponse:
        self._validate(user, date_from, date_to, branch_id)
        records = await self.repository.list(
            user.tenant_id, date_from, date_to, branch_id
        )
        items = [self._response(item) for item in records]
        return LossMapResponse(
            summary=LossMapSummary(
                estimated_total=sum(
                    (
                        item.estimated_amount
                        for item in items
                        if item.status not in {"recovered", "dismissed"}
                    ),
                    ZERO,
                ),
                recovered_total=sum((item.recovered_amount for item in items), ZERO),
                open_count=sum(item.status == "open" for item in items),
                in_progress_count=sum(item.status == "in_progress" for item in items),
                recovered_count=sum(item.status == "recovered" for item in items),
                critical_count=sum(
                    item.severity == "critical" and item.status == "open" for item in items
                ),
            ),
            items=items,
            total=len(items),
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
            generated_at=datetime.now(UTC),
        )

    async def update(
        self, user: User, opportunity_id: UUID, payload: LossUpdateRequest
    ) -> LossOpportunityResponse:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER, UserRole.ADMINISTRATOR}:
            raise AppError("FORBIDDEN", "Loss workflow is not available for this role", 403)
        item = await self.repository.get(user.tenant_id, opportunity_id)
        if item is None:
            raise AppError("LOSS_NOT_FOUND", "Loss opportunity not found", 404)
        allowed = {link.branch_id for link in user.branch_links}
        if user.role == UserRole.ADMINISTRATOR and item.branch_id not in allowed:
            raise AppError("BRANCH_FORBIDDEN", "Opportunity is outside your branch scope", 403)
        if payload.recovered_amount is not None:
            item.recovered_amount = payload.recovered_amount
        if payload.status == "recovered" and item.recovered_amount <= ZERO:
            raise AppError(
                "RECOVERED_AMOUNT_REQUIRED",
                "Recovered amount must be greater than zero",
                422,
            )
        item.status = payload.status
        item.assigned_user_id = payload.assigned_user_id
        item.resolved_at = (
            datetime.now(UTC) if payload.status in {"recovered", "dismissed"} else None
        )
        return self._response(item)

    @staticmethod
    def _response(item) -> LossOpportunityResponse:
        return LossOpportunityResponse(
            id=item.id,
            branch_id=item.branch_id,
            assigned_user_id=item.assigned_user_id,
            loss_type=item.loss_type,
            severity=item.severity,
            status=item.status,
            title=item.title,
            description=item.description,
            recommended_action=item.recommended_action,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            estimated_amount=item.estimated_amount,
            recovered_amount=item.recovered_amount,
            currency=item.currency,
            confidence=item.confidence,
            evidence=item.evidence,
            detected_at=item.detected_at,
            last_detected_at=item.last_detected_at,
        )

    @staticmethod
    def _validate(
        user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> None:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER, UserRole.ADMINISTRATOR}:
            raise AppError("FORBIDDEN", "Loss map is not available for this role", 403)
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        if (date_to - date_from).days > 366:
            raise AppError("DATE_RANGE_TOO_LARGE", "Loss map range cannot exceed one year", 422)
        allowed = {link.branch_id for link in user.branch_links}
        if branch_id and allowed and branch_id not in allowed:
            raise AppError("BRANCH_FORBIDDEN", "Branch is outside your access scope", 403)
        if user.role == UserRole.ADMINISTRATOR and branch_id is None:
            raise AppError(
                "BRANCH_REQUIRED", "Administrator must select an assigned branch", 422
            )
