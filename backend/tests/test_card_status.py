"""Pure, DB-free tests for the card status model shared by every dashboard
card (app.modules.reports.card_status). This is the primitive Task 2's
official_value/detail_value/difference/status/source_report/coverage
contract is built on.
"""
from datetime import date
from decimal import Decimal

from app.modules.reports.card_status import build_card, is_full_coverage
from app.modules.reports.repository import CoverageInfo


def _coverage(**overrides) -> CoverageInfo:
    base = dict(
        requested_from=date(2026, 7, 1),
        requested_to=date(2026, 7, 31),
        covered_from=date(2026, 7, 1),
        covered_to=date(2026, 7, 31),
        covered_months=["2026-07"],
        missing_months=[],
        coverage_ratio=1.0,
        is_partial=False,
        is_exact=False,
    )
    base.update(overrides)
    return CoverageInfo(**base)


def test_no_official_and_no_detail_is_unavailable_with_a_reason() -> None:
    card = build_card(
        metric_code="operating_expenses", label="Операционные расходы",
        source_report="purchases",
    )

    assert card.status == "unavailable"
    assert card.official_value is None
    assert card.detail_value is None
    assert card.reason


def test_custom_unavailable_reason_is_used_verbatim() -> None:
    card = build_card(
        metric_code="doctor_load", label="Загрузка врачей", source_report="appointments",
        unavailable_reason="1С не передаёт данные о расписании и вместимости врача",
    )

    assert card.status == "unavailable"
    assert card.reason == "1С не передаёт данные о расписании и вместимости врача"


def test_detail_only_is_pending_not_unavailable() -> None:
    card = build_card(
        metric_code="revenue_accrual", label="Выручка", source_report="service_revenue",
        detail_value=Decimal("100000"),
    )

    assert card.status == "pending"
    assert card.official_value is None
    assert card.detail_value == Decimal("100000")


def test_official_only_with_full_coverage_is_verified() -> None:
    card = build_card(
        metric_code="revenue_accrual", label="Выручка", source_report="service_revenue",
        official_value=Decimal("1000000"), coverage=_coverage(),
    )

    assert card.status == "verified"
    assert card.difference is None


def test_official_with_partial_coverage_is_partial() -> None:
    card = build_card(
        metric_code="revenue_accrual", label="Выручка", source_report="service_revenue",
        official_value=Decimal("500000"),
        coverage=_coverage(covered_months=["2026-07"], missing_months=["2026-08"], coverage_ratio=0.5, is_partial=True),
    )

    assert card.status == "partial"


def test_official_and_detail_within_tolerance_is_verified() -> None:
    card = build_card(
        metric_code="revenue_accrual", label="Выручка", source_report="service_revenue",
        official_value=Decimal("1000000"), detail_value=Decimal("999900"),
        coverage=_coverage(),
    )

    assert card.status == "verified"
    assert card.difference == Decimal("100")


def test_official_and_detail_beyond_tolerance_is_mismatch() -> None:
    card = build_card(
        metric_code="revenue_accrual", label="Выручка", source_report="service_revenue",
        official_value=Decimal("1000000"), detail_value=Decimal("900000"),
        coverage=_coverage(),
    )

    assert card.status == "mismatch"
    assert card.difference == Decimal("100000")


def test_exact_control_total_coverage_counts_as_full_even_without_months() -> None:
    exact = _coverage(covered_months=["2026-07"], is_exact=True, coverage_ratio=1.0)
    assert is_full_coverage(exact) is True


def test_zero_coverage_is_not_full() -> None:
    assert is_full_coverage(None) is False
    empty = _coverage(covered_months=[], missing_months=[], coverage_ratio=0.0)
    assert is_full_coverage(empty) is False


def test_computed_metric_carries_depends_on_instead_of_a_raw_source() -> None:
    card = build_card(
        metric_code="ebitda", label="EBITDA", source_report="Расчёт",
        official_value=Decimal("400000"), coverage=_coverage(),
        depends_on=("revenue_accrual", "variable_expenses", "fixed_expenses", "payroll_accrual"),
    )

    assert card.depends_on == (
        "revenue_accrual", "variable_expenses", "fixed_expenses", "payroll_accrual",
    )
    assert card.status == "verified"


def test_difference_is_none_when_only_one_side_present() -> None:
    card = build_card(
        metric_code="refunds", label="Возвраты", source_report="cash_receipts",
        official_value=Decimal("5000"), coverage=_coverage(),
    )

    assert card.detail_value is None
    assert card.difference is None
    assert card.status == "verified"
