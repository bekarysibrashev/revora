from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.reports.repository import OfficialReportsRepository


class RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]


@pytest.mark.asyncio
async def test_range_values_sum_daily_metrics_when_every_day_is_present() -> None:
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),
        RowsResult([("service_revenue", 30)]),
        RowsResult([("revenue_accrual", Decimal("62000000.00"), now)]),
    ]

    values, as_of = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 7, 2), date(2026, 7, 31),
        {"revenue_accrual"}, None,
    )

    assert values == {"revenue_accrual": Decimal("62000000.00")}
    assert as_of == now


@pytest.mark.asyncio
async def test_range_values_do_not_present_partial_daily_coverage_as_complete() -> None:
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),
        RowsResult([("service_revenue", 29)]),
        RowsResult([("revenue_accrual", Decimal("61000000.00"), now)]),
    ]

    values, as_of = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 7, 2), date(2026, 7, 31),
        {"revenue_accrual"}, None,
    )

    assert values == {}
    assert as_of is None


@pytest.mark.asyncio
async def test_range_patient_total_counts_distinct_anonymous_markers() -> None:
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),
        RowsResult([("patients", 30)]),
        RowsResult([(760, now)]),
    ]

    values, as_of = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 7, 2), date(2026, 7, 31),
        {"patients_total"}, None,
    )

    assert values == {"patients_total": Decimal("760")}
    assert as_of == now


@pytest.mark.asyncio
async def test_exact_control_total_still_has_priority_over_daily_metrics() -> None:
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.return_value = RowsResult([
        ("revenue_accrual", Decimal("65494639.65"), now),
    ])

    values, as_of = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 7, 1), date(2026, 7, 31),
        {"revenue_accrual"}, None,
    )

    assert values == {"revenue_accrual": Decimal("65494639.65")}
    assert as_of == now
    session.execute.assert_awaited_once()
