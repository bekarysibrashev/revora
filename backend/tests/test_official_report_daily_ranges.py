"""Coverage-aware date-range resolution for official 1C metrics (Task 3).

These tests exercise `OfficialReportsRepository.exact_values` /
`exact_dimension_metrics` together with the pure helpers `month_windows`
and `_build_coverage`. The repository has no live-Postgres test fixture in
this suite (see tests/README.md conventions), so `session.execute` is
stubbed with a queue of results shaped exactly like the rows the real SQL
statements would return, in the exact order the repository issues them.
Each test documents that call order inline so the stub queue stays legible
if the repository's query order ever changes.

Core acceptance rule under test throughout: a date range must never
collapse to a bare 0 just because it is not fully covered by data. Only
whole calendar months (or an exact control-total match) count as
"covered"; everything else is summed from what is actually covered and
reported via CoverageInfo, never interpolated or padded with zeros.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.reports.repository import (
    OfficialReportsRepository,
    _build_coverage,
    month_windows,
)


class RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def one(self):
        assert len(self.rows) == 1, f"expected exactly one row, got {self.rows!r}"
        return self.rows[0]


def _daily_rows(report_type: str, days: list[date]) -> list[tuple[str, date]]:
    """Rows `_month_coverage`'s query would return: one (report_type, day)
    pair per daily (period_from == period_to) import that actually exists."""
    return [(report_type, day) for day in days]


def _month_days(year: int, month: int, only_up_to: int | None = None) -> list[date]:
    import calendar

    last_day = only_up_to or calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(1, last_day + 1)]


# ---------------------------------------------------------------------------
# month_windows / _build_coverage -- pure functions, no session involved.
# ---------------------------------------------------------------------------

def test_month_windows_clips_partial_boundary_months() -> None:
    windows = month_windows(date(2026, 5, 15), date(2026, 7, 10))

    assert windows == [
        ("2026-05", date(2026, 5, 15), date(2026, 5, 31)),
        ("2026-06", date(2026, 6, 1), date(2026, 6, 30)),
        ("2026-07", date(2026, 7, 1), date(2026, 7, 10)),
    ]


def test_month_windows_covers_a_full_calendar_year() -> None:
    windows = month_windows(date(2026, 1, 1), date(2026, 12, 31))

    assert len(windows) == 12
    assert windows[0] == ("2026-01", date(2026, 1, 1), date(2026, 1, 31))
    assert windows[1] == ("2026-02", date(2026, 2, 1), date(2026, 2, 28))  # 2026 is not a leap year
    assert windows[-1] == ("2026-12", date(2026, 12, 1), date(2026, 12, 31))


def test_build_coverage_exact_match_is_fully_covered_regardless_of_windows() -> None:
    windows = month_windows(date(2026, 1, 1), date(2026, 12, 31))

    coverage = _build_coverage(date(2026, 1, 1), date(2026, 12, 31), windows, windows, is_exact=True)

    assert coverage.is_exact is True
    assert coverage.is_partial is False
    assert coverage.coverage_ratio == 1.0
    assert coverage.covered_from == date(2026, 1, 1)
    assert coverage.covered_to == date(2026, 12, 31)
    assert coverage.missing_months == []
    assert len(coverage.covered_months) == 12


def test_build_coverage_flags_partial_when_some_months_are_missing() -> None:
    windows = month_windows(date(2026, 5, 1), date(2026, 7, 31))
    covered = [windows[2]]  # only July

    coverage = _build_coverage(date(2026, 5, 1), date(2026, 7, 31), windows, covered)

    assert coverage.is_exact is False
    assert coverage.is_partial is True
    assert coverage.covered_months == ["2026-07"]
    assert coverage.missing_months == ["2026-05", "2026-06"]
    assert 0 < coverage.coverage_ratio < 1


def test_build_coverage_reports_unavailable_not_partial_when_nothing_is_covered() -> None:
    windows = month_windows(date(2026, 9, 1), date(2026, 9, 30))

    coverage = _build_coverage(date(2026, 9, 1), date(2026, 9, 30), windows, [])

    assert coverage.is_partial is False  # "partial" implies *some* real data; there is none here
    assert coverage.is_exact is False
    assert coverage.coverage_ratio == 0.0
    assert coverage.covered_months == []
    assert coverage.missing_months == ["2026-09"]
    assert coverage.covered_from is None
    assert coverage.covered_to is None


# ---------------------------------------------------------------------------
# exact_values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exact_control_total_still_has_priority_over_daily_metrics() -> None:
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([("revenue_accrual", Decimal("65494639.65"), now)]),
    ]

    values, as_of, coverage = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 7, 1), date(2026, 7, 31),
        {"revenue_accrual"}, None,
    )

    assert values == {"revenue_accrual": Decimal("65494639.65")}
    assert as_of == now
    assert coverage["revenue_accrual"].is_exact is True
    assert coverage["revenue_accrual"].coverage_ratio == 1.0
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_range_values_sum_daily_metrics_for_a_fully_covered_month_without_control_total() -> None:
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),  # 1. exact control-total check: none uploaded for this exact period
        RowsResult(_daily_rows("service_revenue", _month_days(2026, 7))),  # 2. all 31 July days present
        RowsResult([(Decimal("62000000.00"), now)]),  # 3. sum of the covered (July) window
    ]

    values, as_of, coverage = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 7, 1), date(2026, 7, 31),
        {"revenue_accrual"}, None,
    )

    assert values == {"revenue_accrual": Decimal("62000000.00")}
    assert as_of == now
    info = coverage["revenue_accrual"]
    assert info.is_exact is False
    assert info.is_partial is False  # fully covered by daily snapshots, nothing missing
    assert info.covered_months == ["2026-07"]
    assert info.coverage_ratio == 1.0


@pytest.mark.asyncio
async def test_range_values_only_sum_fully_covered_months_and_flag_the_rest_as_missing() -> None:
    """01.07-31.08: July has every day, August only has 20 of its 31 days.
    A partially-covered month must never be summed as if it were complete."""
    now = datetime.now(UTC)
    session = AsyncMock()
    present_days = _month_days(2026, 7) + _month_days(2026, 8, only_up_to=20)
    session.execute.side_effect = [
        RowsResult([]),
        RowsResult(_daily_rows("service_revenue", present_days)),
        RowsResult([(Decimal("62000000.00"), now)]),  # sum restricted to the July window only
    ]

    values, as_of, coverage = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 7, 1), date(2026, 8, 31),
        {"revenue_accrual"}, None,
    )

    assert values == {"revenue_accrual": Decimal("62000000.00")}
    info = coverage["revenue_accrual"]
    assert info.covered_months == ["2026-07"]
    assert info.missing_months == ["2026-08"]
    assert info.is_partial is True
    assert 0 < info.coverage_ratio < 1


@pytest.mark.asyncio
async def test_range_values_return_no_value_but_honest_coverage_beyond_the_loaded_months() -> None:
    """A range entirely past whatever data has been loaded must come back
    as genuinely absent (empty values dict), never as a fabricated 0."""
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),  # no exact control total
        RowsResult([]),  # no daily snapshots exist in this range at all
    ]

    values, as_of, coverage = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 9, 1), date(2026, 9, 30),
        {"revenue_accrual"}, None,
    )

    assert values == {}
    assert as_of is None
    info = coverage["revenue_accrual"]
    assert info.covered_months == []
    assert info.coverage_ratio == 0.0
    assert info.is_partial is False
    session.execute.assert_awaited()
    assert session.execute.await_count == 2  # never falls through to a per-metric sum call


@pytest.mark.asyncio
async def test_full_year_request_with_data_only_in_july_never_collapses_to_zero() -> None:
    """The exact scenario the user reported: selecting the whole of 2026
    when only July was ever sent must show July's real numbers, not 0."""
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),
        RowsResult(_daily_rows("service_revenue", _month_days(2026, 7))),
        RowsResult([(Decimal("62000000.00"), now)]),
    ]

    values, as_of, coverage = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 1, 1), date(2026, 12, 31),
        {"revenue_accrual"}, None,
    )

    assert values == {"revenue_accrual": Decimal("62000000.00")}  # not {} and not 0
    info = coverage["revenue_accrual"]
    assert info.covered_months == ["2026-07"]
    assert len(info.missing_months) == 11
    assert info.is_partial is True
    assert round(info.coverage_ratio, 2) == round(31 / 365, 2)


@pytest.mark.asyncio
async def test_range_patient_total_counts_distinct_anonymous_markers_across_covered_days() -> None:
    """A patient seen on two different covered days must count once, not
    twice -- the DISTINCT happens in the SQL itself; here we assert the
    repository plumbs that deduplicated count straight through."""
    now = datetime.now(UTC)
    raw_guid_rows = [("guid-A",), ("guid-A",), ("guid-B",)]  # guid-A seen both days
    distinct_count = len({row[0] for row in raw_guid_rows})
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),  # no exact control total for patients_total
        RowsResult(_daily_rows("patients", [date(2026, 7, 1), date(2026, 7, 2)])),
        RowsResult([(distinct_count, now)]),
    ]

    values, as_of, coverage = await OfficialReportsRepository(session).exact_values(
        uuid4(), date(2026, 7, 1), date(2026, 7, 2),
        {"patients_total"}, None,
    )

    assert values == {"patients_total": Decimal("2")}
    assert as_of == now
    assert coverage["patients_total"].is_partial is False


# ---------------------------------------------------------------------------
# exact_dimension_metrics (per-doctor / per-branch breakdowns)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exact_dimension_metrics_exact_control_total_has_priority() -> None:
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([("doctor-guid-1", "Dr. Ivanova", Decimal("2500000.00"), now)]),
    ]

    metrics, as_of, coverage = await OfficialReportsRepository(session).exact_dimension_metrics(
        uuid4(), date(2026, 7, 1), date(2026, 7, 31),
        "doctor_revenue_payment", "doctor", None,
    )

    assert len(metrics) == 1
    assert metrics[0].dimension_label == "Dr. Ivanova"
    assert metrics[0].value == Decimal("2500000.00")
    assert coverage.is_exact is True
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_exact_dimension_metrics_only_sums_the_fully_covered_month() -> None:
    """01.06-31.07: June has no doctor-revenue snapshots at all, July has
    every day. Only July's per-doctor breakdown should come back."""
    now = datetime.now(UTC)
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),  # no exact control total for 01.06-31.07
        RowsResult(_daily_rows("doctor_revenue", _month_days(2026, 7))),  # June absent, July complete
        RowsResult([("doctor-guid-1", "Dr. Ivanova", Decimal("2500000.00"), now)]),
    ]

    metrics, as_of, coverage = await OfficialReportsRepository(session).exact_dimension_metrics(
        uuid4(), date(2026, 6, 1), date(2026, 7, 31),
        "doctor_revenue_payment", "doctor", None,
    )

    assert len(metrics) == 1
    assert metrics[0].value == Decimal("2500000.00")
    assert coverage.covered_months == ["2026-07"]
    assert coverage.missing_months == ["2026-06"]
    assert coverage.is_partial is True


@pytest.mark.asyncio
async def test_exact_dimension_metrics_returns_empty_list_when_the_month_is_only_partly_covered() -> None:
    """A month with SOME but not all days present must not be silently
    treated as covered -- it must be excluded entirely, not interpolated."""
    session = AsyncMock()
    session.execute.side_effect = [
        RowsResult([]),
        RowsResult(_daily_rows("doctor_revenue", _month_days(2026, 7, only_up_to=25))),  # 25 of 31 days
    ]

    metrics, as_of, coverage = await OfficialReportsRepository(session).exact_dimension_metrics(
        uuid4(), date(2026, 7, 1), date(2026, 7, 31),
        "doctor_revenue_payment", "doctor", None,
    )

    assert metrics == []
    assert as_of is None
    assert coverage.covered_months == []
    assert coverage.missing_months == ["2026-07"]
    assert coverage.is_partial is False  # nothing usable was covered -- unavailable, not partial
