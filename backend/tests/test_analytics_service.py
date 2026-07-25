from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.analytics.repository import DatasetSnapshot, IssueSnapshot
from app.modules.analytics.service import AnalyticsService
from app.modules.auth.models import User, UserRole


def make_user(role: UserRole = UserRole.OWNER) -> User:
    user = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="analytics@example.test",
        full_name="Analytics User",
        password_hash="unused",
        role=role,
        is_active=True,
    )
    user.branch_links = []
    return user


class FakeAnalyticsRepository:
    def __init__(self) -> None:
        now = datetime(2026, 7, 25, tzinfo=UTC)
        self.snapshots = [
            DatasetSnapshot("patients", "Пациенты", 10, now, "tenant"),
            DatasetSnapshot("doctors", "Врачи", 3, now, "tenant"),
            DatasetSnapshot("appointments", "Записи", 20, now),
            DatasetSnapshot("leads", "Лиды", 0, None),
            DatasetSnapshot("revenue", "Выручка", 15, now),
            DatasetSnapshot("expenses", "Расходы", 8, now),
            DatasetSnapshot("cashflow", "ДДС", 7, now),
            DatasetSnapshot("balances", "Остатки", 1, now),
            DatasetSnapshot("marketing_spend", "Маркетинг", 0, None),
            DatasetSnapshot("attribution", "Атрибуция", 0, None),
        ]
        self.issues = [
            IssueSnapshot(
                "revenue_without_doctor",
                "Выручка без врача",
                "description",
                "critical",
                2,
                "revenue",
            ),
            IssueSnapshot(
                "patients_without_name",
                "Пациенты без имени",
                "description",
                "warning",
                0,
                "patients",
            ),
        ]

    async def dataset_snapshots(self, tenant_id, date_from, date_to, branch_id):
        return self.snapshots

    async def quality_issues(self, tenant_id, date_from, date_to, branch_id):
        return self.issues

    async def connections(self, tenant_id):
        return []


@pytest.mark.asyncio
async def test_quality_exposes_only_active_issues_and_score() -> None:
    response = await AnalyticsService(FakeAnalyticsRepository()).quality(
        make_user(), date(2026, 7, 1), date(2026, 7, 31), None
    )

    assert response.summary.score == 92
    assert response.summary.status == "good"
    assert response.summary.critical_issues == 1
    assert len(response.issues) == 1
    assert response.issues[0].affected_records == 2


@pytest.mark.asyncio
async def test_metric_catalog_marks_missing_inputs() -> None:
    response = await AnalyticsService(FakeAnalyticsRepository()).metric_catalog(
        make_user(), date(2026, 7, 1), date(2026, 7, 31), None
    )

    lead_conversion = next(
        item for item in response.items if item.key == "lead_conversion_rate"
    )
    roas = next(item for item in response.items if item.key == "marketing_roas")
    net_profit = next(item for item in response.items if item.key == "net_profit")
    assert not lead_conversion.available
    assert roas.missing_datasets == ["marketing_spend", "attribution"]
    assert net_profit.available


@pytest.mark.asyncio
async def test_quality_rejects_administrator() -> None:
    with pytest.raises(AppError) as error:
        await AnalyticsService(FakeAnalyticsRepository()).quality(
            make_user(UserRole.ADMINISTRATOR),
            date(2026, 7, 1),
            date(2026, 7, 31),
            None,
        )

    assert error.value.code == "FORBIDDEN"
