from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.losses.service import LossService


def make_user(role: UserRole = UserRole.OWNER) -> User:
    user = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="loss@example.test",
        full_name="Loss User",
        password_hash="unused",
        role=role,
        is_active=True,
    )
    user.branch_links = []
    return user


def opportunity(status: str = "open"):
    now = datetime(2026, 7, 26, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        branch_id=None,
        assigned_user_id=None,
        loss_type="no_show",
        severity="critical",
        status=status,
        title="Неявка",
        description="Описание",
        recommended_action="Позвонить",
        entity_type="appointment",
        entity_id=uuid4(),
        estimated_amount=Decimal("100000"),
        recovered_amount=Decimal("0"),
        currency="KZT",
        confidence=Decimal("0.9"),
        evidence={"basis": "average"},
        detected_at=now,
        last_detected_at=now,
        resolved_at=None,
    )


class FakeLossRepository:
    def __init__(self):
        self.item = opportunity()

    async def detect(self, tenant_id, date_from, date_to, branch_id):
        return [SimpleNamespace()]

    async def upsert(self, tenant_id, candidates, date_from, date_to):
        return len(candidates)

    async def list(self, tenant_id, date_from, date_to, branch_id):
        return [self.item]

    async def get(self, tenant_id, opportunity_id):
        return self.item if opportunity_id == self.item.id else None


@pytest.mark.asyncio
async def test_loss_refresh_returns_financial_summary() -> None:
    response = await LossService(FakeLossRepository()).refresh(
        make_user(), date(2026, 7, 1), date(2026, 7, 31), None
    )

    assert response.detected == 1
    assert response.summary.estimated_total == Decimal("100000")
    assert response.summary.critical_count == 1


@pytest.mark.asyncio
async def test_recovered_loss_requires_amount() -> None:
    repository = FakeLossRepository()
    service = LossService(repository)
    from app.modules.losses.schemas import LossUpdateRequest

    with pytest.raises(AppError) as error:
        await service.update(
            make_user(),
            repository.item.id,
            LossUpdateRequest(status="recovered"),
        )

    assert error.value.code == "RECOVERED_AMOUNT_REQUIRED"
