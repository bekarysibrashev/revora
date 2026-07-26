from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.auth.models import User, UserRole
from app.modules.ml.repository import CohortStats, ReadinessStats
from app.modules.ml.service import MLService, wilson_interval


def make_user() -> User:
    user = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="ml@example.test",
        full_name="ML User",
        password_hash="unused",
        role=UserRole.OWNER,
        is_active=True,
    )
    user.branch_links = []
    return user


class FakeMLRepository:
    async def readiness(self, tenant_id, date_from, date_to, branch_id):
        return ReadinessStats(
            row_count=500,
            positive_count=60,
            date_min=datetime(2026, 1, 1, tzinfo=UTC),
            date_max=datetime(2026, 7, 20, tzinfo=UTC),
            source_max_updated_at=datetime(2026, 7, 20, tzinfo=UTC),
            doctor_count=500,
            direction_count=400,
            lead_source_count=250,
            lead_time_count=500,
        )

    async def cohorts(self, tenant_id, date_from, date_to, branch_id):
        return [CohortStats("weekday", "1", 100, 20)]


@pytest.mark.asyncio
async def test_no_show_readiness_exposes_feature_quality_and_uncertainty() -> None:
    response = await MLService(FakeMLRepository()).no_show_readiness(
        make_user(), date(2026, 1, 1), date(2026, 7, 31), None
    )

    assert response.status == "exploratory"
    assert response.positive_rate == Decimal("0.12")
    assert response.cohorts[0].lift_vs_baseline > 1
    lead_source = next(
        item for item in response.feature_coverage if item.name == "lead_source"
    )
    assert not lead_source.usable


def test_wilson_interval_is_bounded_and_contains_observed_rate() -> None:
    low, high = wilson_interval(20, 100)
    assert 0 <= low < 0.2 < high <= 1
