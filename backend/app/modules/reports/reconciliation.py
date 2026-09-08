"""Does a per-dimension breakdown actually add up to the clinic total?

Revora shows two numbers side by side that come from different places: a
clinic total for a period, and a breakdown of that same money by doctor.
Nothing forced them to agree, and on real SAN Dental data they do not --
roughly 1.87M KZT on paid revenue and 1.97M KZT on accrued revenue for a
two-day sync. This module makes that gap a first-class, reported quantity
instead of something a reader discovers by adding a column up by hand.

The deliberate design decision here is that "unattributed" and
"unexplained" are NOT the same thing and must never be merged:

- unattributed_total is money the breakdown itself reports as having no
  doctor. It is evidence: 1C really does have sales rows with an empty
  Сотрудник, and the extension groups them under an explicit key rather
  than dropping them.
- difference is what is left over after attributed + unattributed are
  subtracted from the clinic total. Nothing explains it yet. Folding it
  into a "Не распределено" line would make the invariant hold by
  construction and destroy the only signal that something is wrong.

So the invariant

    clinic_total = attributed_total + unattributed_total

is asserted, not enforced: when it does not hold, `difference` carries the
residual, `status` becomes "partial", and `diagnostics` names the most
likely mechanisms. Two of those mechanisms are already known and are
detected structurally rather than guessed at:

1. DIFFERENT_REPORT_TYPES. The clinic total and the breakdown can come
   from two different 1C reports. REPORT_TYPE_BY_METRIC maps
   revenue_payment to "cash_receipts" but doctor_revenue_payment to
   "doctor_revenue" -- so on the paid side the total is scraped from
   «Монитор руководителя. Выручка» while the breakdown is queried from
   «Анализ оплат по врачам». Those are different documents over
   different registers; there is no reason for them to agree, and no
   amount of reconciliation logic can make them agree. This is reported
   as a structural cause, because the fix is to change where the numbers
   come from, not to adjust them.

2. DIMENSION_EXCEEDS_CLINIC_TOTAL. A breakdown larger than the total it
   belongs to cannot be explained by missing rows; it means the two sides
   covered different periods or different filters. In the 1C extension
   the classic cause is a СтрЗаменить() period substitution that silently
   did not match, leaving the register query running over all of history
   while the report ran over the requested range.

Tolerance is per-row, not a flat percentage: each 1C row is rounded to a
tiyn, so N rows can legitimately drift by N tiyns and no further. A
percentage tolerance would quietly absorb real money on large periods.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Sequence

from app.modules.reports.repository import REPORT_TYPE_BY_METRIC

TIYN = Decimal("0.01")

# Dimension keys the 1C extension uses when a row genuinely has no doctor.
# КлючСсылки() renders an empty reference as "empty"; the others are
# defensive against older snapshots and hand-built fixtures.
UNATTRIBUTED_KEYS = frozenset({"", "empty", "none", "null", "unknown", "не указано"})

RECONCILED = "reconciled"
PARTIAL = "partial"
FAILED = "failed"


class _HasDimension(Protocol):
    dimension_key: str
    dimension_label: str
    value: Decimal


class _HasCoverage(Protocol):
    coverage_ratio: float
    is_partial: bool


def is_unattributed(dimension_key: str) -> bool:
    return dimension_key.strip().casefold() in UNATTRIBUTED_KEYS


@dataclass(frozen=True)
class DimensionReconciliation:
    """One breakdown checked against the clinic total it should sum to."""

    metric_code: str
    clinic_metric_code: str
    dimension_type: str

    clinic_total: Decimal | None
    attributed_total: Decimal
    unattributed_total: Decimal
    dimension_total: Decimal
    difference: Decimal | None
    difference_percent: Decimal | None

    rows_total: int
    rows_without_dimension: int

    status: str
    diagnostics: tuple[str, ...]
    tolerance: Decimal

    @property
    def invariant_holds(self) -> bool:
        """clinic_total = attributed_total + unattributed_total, up to the
        accumulated per-row rounding the tolerance allows."""
        if self.difference is None:
            return False
        return abs(self.difference) <= self.tolerance

    @property
    def is_trustworthy(self) -> bool:
        return self.status == RECONCILED


def reconcile_dimension(
    *,
    metric_code: str,
    clinic_metric_code: str,
    dimension_type: str,
    clinic_total: Decimal | None,
    rows: Sequence[_HasDimension],
    clinic_coverage: _HasCoverage | None = None,
    dimension_coverage: _HasCoverage | None = None,
) -> DimensionReconciliation:
    """Check one dimension breakdown against its clinic total.

    `clinic_total` of None means the official total is not available for
    this period at all (no control report, no complete month of daily
    snapshots). That is "failed", not "zero": reporting a difference
    against an absent total would invent a 100% discrepancy out of missing
    data.
    """
    attributed = Decimal("0")
    unattributed = Decimal("0")
    rows_without_dimension = 0

    for row in rows:
        value = Decimal(row.value)
        if is_unattributed(str(row.dimension_key)):
            unattributed += value
            rows_without_dimension += 1
        else:
            attributed += value

    dimension_total = attributed + unattributed
    rows_total = len(rows)
    tolerance = max(TIYN, TIYN * rows_total)

    diagnostics: list[str] = []

    clinic_report = REPORT_TYPE_BY_METRIC.get(clinic_metric_code)
    dimension_report = REPORT_TYPE_BY_METRIC.get(metric_code)
    if clinic_report and dimension_report and clinic_report != dimension_report:
        # Structural: no arithmetic can reconcile two different 1C reports.
        diagnostics.append(
            f"different_report_types:{clinic_metric_code}={clinic_report}"
            f"|{metric_code}={dimension_report}"
        )

    if clinic_total is None:
        diagnostics.append(f"clinic_total_missing:{clinic_metric_code}")
        return DimensionReconciliation(
            metric_code=metric_code,
            clinic_metric_code=clinic_metric_code,
            dimension_type=dimension_type,
            clinic_total=None,
            attributed_total=attributed,
            unattributed_total=unattributed,
            dimension_total=dimension_total,
            difference=None,
            difference_percent=None,
            rows_total=rows_total,
            rows_without_dimension=rows_without_dimension,
            status=FAILED,
            diagnostics=tuple(diagnostics),
            tolerance=tolerance,
        )

    if not rows:
        diagnostics.append(f"no_dimension_rows:{metric_code}")

    if rows_without_dimension:
        diagnostics.append(
            f"rows_without_{dimension_type}:{rows_without_dimension}"
            f"|sum={unattributed}"
        )

    difference = Decimal(clinic_total) - dimension_total
    difference_percent: Decimal | None = None
    if clinic_total != 0:
        difference_percent = (difference / Decimal(clinic_total) * 100).quantize(
            Decimal("0.0001")
        )

    if difference < -tolerance:
        # More money in the breakdown than in the total it belongs to.
        # Missing rows cannot cause this; a period or filter mismatch can.
        diagnostics.append(f"dimension_exceeds_clinic_total:{-difference}")

    for label, coverage in (
        ("clinic", clinic_coverage),
        ("dimension", dimension_coverage),
    ):
        if coverage is not None and getattr(coverage, "is_partial", False):
            diagnostics.append(
                f"partial_coverage:{label}={coverage.coverage_ratio:.4f}"
            )

    if (
        clinic_coverage is not None
        and dimension_coverage is not None
        and abs(clinic_coverage.coverage_ratio - dimension_coverage.coverage_ratio)
        > 1e-9
    ):
        # The two sides summed different sets of months, so the difference
        # is at least partly calendar, not accounting.
        diagnostics.append(
            f"coverage_mismatch:clinic={clinic_coverage.coverage_ratio:.4f}"
            f"|dimension={dimension_coverage.coverage_ratio:.4f}"
        )

    if not rows:
        status = FAILED
    elif abs(difference) <= tolerance:
        status = RECONCILED
    else:
        status = PARTIAL
        diagnostics.append(f"difference_exceeds_tolerance:{difference}|max={tolerance}")

    return DimensionReconciliation(
        metric_code=metric_code,
        clinic_metric_code=clinic_metric_code,
        dimension_type=dimension_type,
        clinic_total=Decimal(clinic_total),
        attributed_total=attributed,
        unattributed_total=unattributed,
        dimension_total=dimension_total,
        difference=difference,
        difference_percent=difference_percent,
        rows_total=rows_total,
        rows_without_dimension=rows_without_dimension,
        status=status,
        diagnostics=tuple(diagnostics),
        tolerance=tolerance,
    )
