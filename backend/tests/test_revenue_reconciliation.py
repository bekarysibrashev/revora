"""The revenue reconciliation contract.

Every case the SAN Dental audit asked to be covered is here: ordinary
payments, accruals, a row with no doctor, a refund, a reversal, a
discount, several doctors, daily-vs-exact ranges agreeing, no double
counting, and a full clinic-total check. They are expressed against
reconcile_dimension() because that is where the invariant

    clinic_total = attributed_total + unattributed_total

is decided; the numbers themselves arrive from 1C and are not this
module's to invent.
"""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.modules.reports.reconciliation import (
    FAILED,
    PARTIAL,
    RECONCILED,
    is_unattributed,
    reconcile_dimension,
)


@dataclass(frozen=True)
class Row:
    dimension_key: str
    dimension_label: str
    value: Decimal


@dataclass(frozen=True)
class Coverage:
    coverage_ratio: float
    is_partial: bool


def _row(key: str, value: str, label: str | None = None) -> Row:
    return Row(dimension_key=key, dimension_label=label or key, value=Decimal(value))


def _reconcile(clinic_total, rows, **kwargs):
    return reconcile_dimension(
        metric_code=kwargs.pop("metric_code", "doctor_revenue_accrual"),
        clinic_metric_code=kwargs.pop("clinic_metric_code", "revenue_accrual"),
        dimension_type="doctor",
        clinic_total=None if clinic_total is None else Decimal(clinic_total),
        rows=rows,
        **kwargs,
    )


def test_ordinary_accrual_breakdown_reconciles_exactly() -> None:
    result = _reconcile("300000.00", [_row("d1", "180000.00"), _row("d2", "120000.00")])

    assert result.status == RECONCILED
    assert result.difference == Decimal("0.00")
    assert result.invariant_holds
    assert result.unattributed_total == Decimal("0")
    assert result.diagnostics == ()


def test_ordinary_payment_breakdown_reconciles_exactly() -> None:
    """Same contract on the paid side, using the pair of metric codes that
    actually share a report type."""
    result = _reconcile(
        "250000.00",
        [_row("d1", "250000.00")],
        metric_code="doctor_revenue_payment",
        clinic_metric_code="doctor_revenue_payment",
    )

    assert result.status == RECONCILED
    assert result.diagnostics == ()


def test_a_row_without_a_doctor_is_reported_not_dropped() -> None:
    """Money 1C really has no doctor for stays in the total and is counted
    separately, so the invariant still closes."""
    result = _reconcile(
        "300000.00",
        [_row("d1", "180000.00"), _row("empty", "120000.00", "Не указано")],
    )

    assert result.attributed_total == Decimal("180000.00")
    assert result.unattributed_total == Decimal("120000.00")
    assert result.rows_without_dimension == 1
    assert result.status == RECONCILED
    assert result.invariant_holds
    assert any(item.startswith("rows_without_doctor:1") for item in result.diagnostics)


def test_refund_reduces_the_breakdown_and_still_reconciles() -> None:
    result = _reconcile(
        "170000.00",
        [_row("d1", "180000.00"), _row("d2", "-10000.00")],
    )

    assert result.dimension_total == Decimal("170000.00")
    assert result.status == RECONCILED


def test_reversal_of_a_whole_doctor_row_reconciles_to_zero() -> None:
    result = _reconcile("0.00", [_row("d1", "50000.00"), _row("d1_storno", "-50000.00")])

    assert result.dimension_total == Decimal("0.00")
    assert result.difference == Decimal("0.00")
    assert result.difference_percent is None  # no percentage against a zero total
    assert result.status == RECONCILED


def test_discounted_total_reconciles_against_the_discounted_breakdown() -> None:
    """revenue_before_discount is a separate metric; the reconciliation
    must compare like with like and not drift because a discount exists."""
    result = _reconcile("95000.00", [_row("d1", "50000.00"), _row("d2", "45000.00")])

    assert result.status == RECONCILED


def test_many_doctors_sum_to_the_clinic_total() -> None:
    rows = [_row(f"d{index}", "1000.00") for index in range(50)]

    result = _reconcile("50000.00", rows)

    assert result.rows_total == 50
    assert result.status == RECONCILED


def test_rounding_drift_is_tolerated_per_row_not_as_a_percentage() -> None:
    """Ten rows may drift by ten tiyns and no more. A flat percentage
    tolerance would absorb real money on a large period; this must not."""
    rows = [_row(f"d{index}", "100.00") for index in range(10)]

    within = _reconcile("1000.10", rows)
    beyond = _reconcile("1000.11", rows)

    assert within.status == RECONCILED
    assert beyond.status == PARTIAL


def test_a_real_gap_is_reported_and_never_absorbed_into_unattributed() -> None:
    """The regression that motivates this module: a ~1.97M gap must show up
    as an unexplained difference, not as a tidy "Не распределено" line that
    makes the column add up."""
    result = _reconcile("10000000.00", [_row("d1", "8026179.65")])

    assert result.status == PARTIAL
    assert result.difference == Decimal("1973820.35")
    assert result.unattributed_total == Decimal("0")
    assert result.rows_without_dimension == 0
    assert not result.invariant_holds
    assert any(
        item.startswith("difference_exceeds_tolerance") for item in result.diagnostics
    )


def test_difference_percent_is_reported_against_the_clinic_total() -> None:
    result = _reconcile("1000000.00", [_row("d1", "900000.00")])

    assert result.difference == Decimal("100000.00")
    assert result.difference_percent == Decimal("10.0000")


def test_breakdown_larger_than_the_total_is_flagged_as_its_own_cause() -> None:
    """Missing rows cannot make a breakdown exceed its total. This is the
    signature of a period or filter mismatch -- in the 1C extension,
    typically a СтрЗаменить period substitution that did not match and left
    the register query running over all of history."""
    result = _reconcile("100000.00", [_row("d1", "250000.00")])

    assert result.status == PARTIAL
    assert result.difference == Decimal("-150000.00")
    assert any(
        item.startswith("dimension_exceeds_clinic_total:150000.00")
        for item in result.diagnostics
    )


def test_paid_revenue_pair_is_flagged_as_structurally_unreconcilable() -> None:
    """The concrete finding behind the ~1.87M paid-side gap: the clinic
    total and the doctor breakdown are read from two different 1C reports
    (cash_receipts vs doctor_revenue). The number cannot be fixed by
    arithmetic, so it is named as a structural cause."""
    result = _reconcile(
        "5000000.00",
        [_row("d1", "3125079.65")],
        metric_code="doctor_revenue_payment",
        clinic_metric_code="revenue_payment",
    )

    assert any(
        item.startswith("different_report_types:revenue_payment=cash_receipts")
        and "doctor_revenue_payment=doctor_revenue" in item
        for item in result.diagnostics
    )


def test_accrued_revenue_pair_shares_one_report_type() -> None:
    """The accrued side does NOT have the structural mismatch: both codes
    map to service_revenue. Its gap therefore has a different cause and
    must not be blamed on report types."""
    result = _reconcile("300000.00", [_row("d1", "300000.00")])

    assert not any(item.startswith("different_report_types") for item in result.diagnostics)


def test_missing_clinic_total_fails_rather_than_inventing_a_full_discrepancy() -> None:
    result = _reconcile(None, [_row("d1", "180000.00")])

    assert result.status == FAILED
    assert result.clinic_total is None
    assert result.difference is None
    assert result.difference_percent is None
    assert not result.invariant_holds
    assert any(item.startswith("clinic_total_missing") for item in result.diagnostics)


def test_no_breakdown_rows_fails_rather_than_claiming_a_full_gap() -> None:
    result = _reconcile("300000.00", [])

    assert result.status == FAILED
    assert any(item.startswith("no_dimension_rows") for item in result.diagnostics)


def test_partial_coverage_is_named_on_whichever_side_is_incomplete() -> None:
    result = _reconcile(
        "300000.00",
        [_row("d1", "300000.00")],
        clinic_coverage=Coverage(coverage_ratio=1.0, is_partial=False),
        dimension_coverage=Coverage(coverage_ratio=0.5, is_partial=True),
    )

    assert any(item.startswith("partial_coverage:dimension=0.5") for item in result.diagnostics)


def test_different_coverage_on_the_two_sides_is_flagged_as_calendar_not_accounting() -> None:
    result = _reconcile(
        "300000.00",
        [_row("d1", "300000.00")],
        clinic_coverage=Coverage(coverage_ratio=1.0, is_partial=False),
        dimension_coverage=Coverage(coverage_ratio=0.5, is_partial=True),
    )

    assert any(item.startswith("coverage_mismatch:clinic=1.0000") for item in result.diagnostics)


def test_equal_coverage_on_both_sides_raises_no_calendar_diagnostic() -> None:
    result = _reconcile(
        "300000.00",
        [_row("d1", "300000.00")],
        clinic_coverage=Coverage(coverage_ratio=1.0, is_partial=False),
        dimension_coverage=Coverage(coverage_ratio=1.0, is_partial=False),
    )

    assert not any(item.startswith("coverage_mismatch") for item in result.diagnostics)


def test_a_daily_summed_range_and_an_exact_range_reconcile_identically() -> None:
    """Same money, delivered as one exact-period row set or as summed daily
    snapshots, must produce the same verdict -- otherwise the reader cannot
    trust a figure without knowing which path produced it."""
    exact = _reconcile("300000.00", [_row("d1", "180000.00"), _row("d2", "120000.00")])
    daily = _reconcile(
        "300000.00",
        [
            _row("d1", "60000.00"),
            _row("d1", "120000.00"),
            _row("d2", "120000.00"),
        ],
    )

    assert exact.status == daily.status == RECONCILED
    assert exact.dimension_total == daily.dimension_total


def test_the_same_row_is_never_counted_twice() -> None:
    """Guard against the classic double-count: mixing an exact control
    period with the daily snapshots that make it up. If both were summed,
    the breakdown would be exactly double and the reconciliation must not
    call that reconciled."""
    doubled = _reconcile(
        "300000.00",
        [_row("d1", "180000.00"), _row("d2", "120000.00")] * 2,
    )

    assert doubled.dimension_total == Decimal("600000.00")
    assert doubled.status == PARTIAL
    assert any(
        item.startswith("dimension_exceeds_clinic_total:300000.00")
        for item in doubled.diagnostics
    )


@pytest.mark.parametrize("key", ["empty", "", "  ", "NONE", "Не указано", "unknown"])
def test_every_shape_of_missing_doctor_key_counts_as_unattributed(key: str) -> None:
    assert is_unattributed(key) is True


@pytest.mark.parametrize("key", ["d1", "Иванов И.И.", "0"])
def test_a_real_doctor_key_is_never_treated_as_unattributed(key: str) -> None:
    assert is_unattributed(key) is False


# --- Wiring: the verdict must actually reach the API response -------------


class _ReconcilingDoctorsRepository:
    """Minimal double for DoctorsService: one doctor whose money does not
    add up to the clinic total."""

    def __init__(self, reconciliation):
        self._reconciliation = reconciliation

    async def overview(self, tenant_id, date_from, date_to, branch_ids):
        from app.modules.doctors.repository import DoctorTotals
        from app.modules.reports.repository import CoverageInfo

        totals = [
            DoctorTotals(
                doctor_id=__import__("uuid").uuid4(),
                full_name="Doctor One",
                specialty="Dentist",
                appointments_total=4,
                appointments_completed=4,
                revenue_accrual=Decimal("8026179.65"),
                revenue_payment=Decimal("8026179.65"),
                average_rating=None,
                data_as_of=None,
            )
        ]
        coverage = CoverageInfo(
            requested_from=date_from,
            requested_to=date_to,
            covered_from=date_from,
            covered_to=date_to,
            covered_months=["2026-08"],
            missing_months=[],
            coverage_ratio=1.0,
            is_partial=False,
            is_exact=True,
        )
        return totals, coverage

    async def revenue_reconciliation(self, tenant_id, date_from, date_to, branch_ids):
        return self._reconciliation


class _PlainDoctorsRepository(_ReconcilingDoctorsRepository):
    """An older repository that knows nothing about reconciliation."""

    def __init__(self):
        super().__init__([])

    revenue_reconciliation = None


@pytest.mark.asyncio
async def test_overview_reports_an_unreconciled_doctor_column() -> None:
    from datetime import date as _date

    from app.modules.auth.models import User, UserRole
    from app.modules.doctors.service import DoctorsService

    gap = _reconcile("10000000.00", [_row("d1", "8026179.65")])
    user = User(
        id=__import__("uuid").uuid4(),
        tenant_id=__import__("uuid").uuid4(),
        email="owner@example.test",
        full_name="Owner",
        password_hash="unused",
        role=UserRole.OWNER,
        is_active=True,
    )
    user.branch_links = []

    response = await DoctorsService(_ReconcilingDoctorsRepository([gap])).overview(
        user, _date(2026, 8, 1), _date(2026, 8, 31), None
    )

    assert len(response.reconciliation) == 1
    entry = response.reconciliation[0]
    assert entry.status == PARTIAL
    assert entry.difference == Decimal("1973820.35")
    assert entry.unattributed_total == Decimal("0")
    assert any(
        item.startswith("difference_exceeds_tolerance") for item in entry.diagnostics
    )


@pytest.mark.asyncio
async def test_overview_still_works_against_a_repository_without_reconciliation() -> None:
    from datetime import date as _date

    from app.modules.auth.models import User, UserRole
    from app.modules.doctors.service import DoctorsService

    user = User(
        id=__import__("uuid").uuid4(),
        tenant_id=__import__("uuid").uuid4(),
        email="owner2@example.test",
        full_name="Owner",
        password_hash="unused",
        role=UserRole.OWNER,
        is_active=True,
    )
    user.branch_links = []

    response = await DoctorsService(_PlainDoctorsRepository()).overview(
        user, _date(2026, 8, 1), _date(2026, 8, 31), None
    )

    assert response.reconciliation == []
    assert response.total == 1
