"""Card status model shared by every "official 1C figure vs local detail"
dashboard card (finance, sales/patients, operational, marketing).

A card never invents a number: build_card() only ever returns one of five
honest states -- verified / mismatch / partial / unavailable / pending --
plus the official_value/detail_value/difference/source_report/coverage
fields the spec requires, and a human `reason` whenever the value is not a
plain verified figure. Metrics Revora computes itself (EBITDA, margin, CAC,
ROAS, ...) pass their own tuple of `depends_on` metric_codes instead of a
source_report, since they are never given a 1C metric_code of their own.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from app.modules.reports.repository import CoverageInfo

CardStatusName = Literal["verified", "mismatch", "partial", "unavailable", "pending"]

# Relative tolerance before two independently sourced values for the same
# metric count as a genuine mismatch rather than rounding/timing noise.
DEFAULT_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class CardStatus:
    metric_code: str
    label: str
    official_value: Decimal | None
    detail_value: Decimal | None
    difference: Decimal | None
    status: CardStatusName
    source_report: str
    coverage_from: date | None
    coverage_to: date | None
    branch: str | None = None
    reason: str | None = None
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    unit: str = "KZT"


def is_full_coverage(coverage: CoverageInfo | None) -> bool:
    """True only when the ENTIRE requested range is backed by real 1C data:
    an exact control-total match, or every calendar month in range present
    with none missing. Used to gate figures (profit, margin, ...) that must
    never be presented as certain when only part of the period is confirmed.
    """
    if coverage is None:
        return False
    if coverage.is_exact:
        return True
    return bool(coverage.covered_months) and not coverage.missing_months


def build_card(
    *,
    metric_code: str,
    label: str,
    source_report: str,
    official_value: Decimal | None = None,
    detail_value: Decimal | None = None,
    coverage: CoverageInfo | None = None,
    branch: str | None = None,
    tolerance: Decimal = DEFAULT_TOLERANCE,
    unavailable_reason: str | None = None,
    depends_on: tuple[str, ...] = (),
    unit: str = "KZT",
) -> CardStatus:
    """Builds one CardStatus. Pure function, no I/O -- every dashboard
    section calls this once it has fetched official_value (from
    OfficialReportsRepository.exact_values/exact_dimension_metrics),
    detail_value (from Revora's own canonical tables, if any exist for this
    metric), and the matching CoverageInfo.
    """
    difference = (
        official_value - detail_value
        if official_value is not None and detail_value is not None
        else None
    )
    coverage_from = coverage.covered_from if coverage else None
    coverage_to = coverage.covered_to if coverage else None

    def _card(status: CardStatusName, reason: str | None) -> CardStatus:
        return CardStatus(
            metric_code=metric_code, label=label,
            official_value=official_value, detail_value=detail_value, difference=difference,
            status=status, source_report=source_report,
            coverage_from=coverage_from, coverage_to=coverage_to, branch=branch,
            reason=reason, depends_on=depends_on, unit=unit,
        )

    if official_value is None and detail_value is None:
        return _card(
            "unavailable",
            unavailable_reason
            or "Нет данных ни от 1С, ни из локальных записей за этот период",
        )

    if official_value is None:
        # A local detail figure exists but 1C has not confirmed it for the
        # period yet -- distinct from unavailable: this metric IS sourced
        # from 1C in principle, it just has not arrived for this range.
        return _card("pending", "Официальный отчёт 1С за этот период ещё не загружен")

    if not is_full_coverage(coverage):
        return _card(
            "partial",
            "Официальные данные 1С покрывают только часть выбранного периода",
        )

    if detail_value is not None:
        base = abs(official_value) if official_value else Decimal("1")
        relative_diff = abs(difference) / base if base else abs(difference)
        if relative_diff > tolerance:
            return _card(
                "mismatch",
                f"Официальный итог 1С расходится с локальной детализацией "
                f"более чем на {tolerance:.0%}",
            )

    return _card("verified", None)
