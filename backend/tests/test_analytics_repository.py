"""AnalyticsRepository.dataset_snapshots reads real 1C-sourced datasets.

The old OData/PowerShell connector wrote one row per transaction into
revenue_facts/expense_facts/cash_flow_facts/appointments/doctors. The current
1C report-snapshot pipeline never writes those tables -- it writes
official_report_imports/official_report_metrics instead (see
app.modules.reports). This test proves the "revenue"/"cashflow"/"expenses"/
"appointments"/"doctors" datasets are read from the tables the real pipeline
actually fills, not from the now-permanently-empty legacy fact tables, so
the "Контроль данных" readiness widget reflects reality.

Session mocking follows tests/test_official_report_daily_ranges.py's
convention (no live-Postgres fixture in this suite): session.execute is
stubbed with a queue of canned results shaped like what the real query would
return, in the exact order AnalyticsRepository.dataset_snapshots issues them:
patients, doctors, appointments, leads, revenue, expenses, cashflow,
balances, marketing_spend, attribution.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.analytics.repository import AnalyticsRepository


class OneResult:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


@pytest.mark.asyncio
async def test_dataset_snapshots_reads_official_report_tables_not_legacy_facts() -> None:
    now = datetime(2026, 7, 25, tzinfo=UTC)
    tenant_id = uuid4()
    session = AsyncMock()
    session.execute.side_effect = [
        OneResult((766, now)),   # patients
        OneResult((3, now)),     # doctors -- distinct dimension_label from doctor_revenue metrics
        OneResult((45, now)),    # appointments -- from official_report_metrics, report_type=appointments
        OneResult((0, None)),    # leads -- genuinely no source wired yet
        OneResult((12, now)),    # revenue -- report_type=service_revenue
        OneResult((0, None)),    # expenses -- report_type=purchases, none synced this period
        OneResult((6, now)),     # cashflow -- report_type=cash_receipts
        OneResult((0, None)),    # balances -- external, not connected
        OneResult((0, None)),    # marketing_spend
        OneResult((0, None)),    # attribution
    ]

    result = await AnalyticsRepository(session).dataset_snapshots(
        tenant_id, date(2026, 7, 1), date(2026, 7, 31), None
    )

    by_key = {item.key: item for item in result}
    assert by_key["patients"].count == 766
    assert by_key["doctors"].count == 3
    assert by_key["appointments"].count == 45
    assert by_key["revenue"].count == 12
    assert by_key["cashflow"].count == 6
    assert by_key["expenses"].count == 0
    assert by_key["leads"].count == 0
    assert session.execute.await_count == 10


@pytest.mark.asyncio
async def test_dataset_snapshots_queries_use_official_report_tables_not_legacy_facts() -> None:
    """The compiled SQL for revenue/cashflow/expenses/appointments/doctors
    must reference official_report_imports/official_report_metrics, and must
    NOT reference the dead legacy fact tables -- this is what actually makes
    the readiness widget honest again."""
    session = AsyncMock()
    compiled: list[str] = []

    async def capture(statement):
        compiled.append(str(statement.compile(compile_kwargs={"literal_binds": True})))
        return OneResult((0, None))

    session.execute.side_effect = capture

    await AnalyticsRepository(session).dataset_snapshots(
        uuid4(), date(2026, 7, 1), date(2026, 7, 31), None
    )

    # order: patients, doctors, appointments, leads, revenue, expenses,
    # cashflow, balances, marketing_spend, attribution
    doctors_sql, appointments_sql, revenue_sql, expenses_sql, cashflow_sql = (
        compiled[1], compiled[2], compiled[4], compiled[5], compiled[6]
    )
    legacy_tables = ("revenue_facts", "expense_facts", "cash_flow_facts", "FROM appointments", "FROM doctors")
    for sql in (doctors_sql, appointments_sql, revenue_sql, expenses_sql, cashflow_sql):
        assert "official_report_metrics" in sql
        assert "official_report_imports" in sql
        for legacy in legacy_tables:
            assert legacy not in sql
