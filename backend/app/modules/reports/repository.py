"""Persistence and period lookup for official and daily 1C metrics."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.reports.models import OfficialReportImport, OfficialReportMetric
from app.modules.sales.models import Patient
from app.modules.tenancy.models import Branch


@dataclass(frozen=True)
class ReportMetricValue:
    dimension_key: str
    dimension_label: str
    value: Decimal
    branch_id: UUID | None = None


@dataclass(frozen=True)
class CoverageInfo:
    """Honest description of how much of a requested date range is backed by
    real 1C data for one metric, so a partial answer is never presented as a
    complete one and never silently collapses to zero.

    A calendar month counts as "covered" only when every one of its days
    within the requested range has its own daily snapshot for the report
    type that metric belongs to (or the whole requested range matches an
    uploaded control-total period exactly, in which case is_exact=True and
    the range is covered by definition). Coverage is never computed by
    averaging or interpolating -- only real, present rows count.
    """

    requested_from: date
    requested_to: date
    covered_from: date | None
    covered_to: date | None
    covered_months: list[str] = field(default_factory=list)
    missing_months: list[str] = field(default_factory=list)
    coverage_ratio: float = 0.0
    is_partial: bool = False
    is_exact: bool = False


REPORT_TYPE_BY_METRIC = {
    "revenue_payment": "cash_receipts",
    "cash_inflow": "cash_receipts",
    # Task 2: cash-receipts breakdown the "Фактически поступившие деньги"
    # report already carries alongside plain inflow -- returns to patients
    # and insurance-company settlements.
    "refunds": "cash_receipts",
    "insurance_payments": "cash_receipts",
    "services_count": "service_revenue",
    "revenue_accrual": "service_revenue",
    "revenue_before_discount": "service_revenue",
    "doctor_revenue_payment": "doctor_revenue",
    "purchases_accrual_all_entities": "purchases",
    "purchases_paid_all_entities": "purchases",
    "purchases_accrual": "purchases",
    "purchases_paid": "purchases",
    "operating_expenses": "purchases",
    "patients_total": "patients",
    "patients_primary": "patients",
    "patients_new": "patients",
    "patient_visits": "patients",
    "patient_report_revenue": "patients",
    "patient_report_paid": "patients",
    "patient_seen": "patients",
    "patient_primary_seen": "patients",
    "appointments_total": "appointments",
    "appointments_primary": "appointments",
    "appointments_completed": "appointments",
    "appointments_cancelled": "appointments",
    "appointments_no_show": "appointments",
    "appointment_report_revenue": "appointments",
    "appointment_report_paid": "appointments",
    # Task 2: appointment-level operational metrics from the same
    # "Статистика предварительной записи" report already used for
    # appointments_total/completed/cancelled/no_show.
    "appointments_transferred": "appointments",
    "doctor_load": "appointments",
    "room_load": "appointments",
    # Task 2: treatment-plan funnel (consultation -> plan -> payment).
    # Grouped under "patients" (patient journey), not a new report_type --
    # best-effort source, see tools/revora_1c_extension/РвОбменСервер.bsl.
    "treatment_plan_created": "patients",
    "treatment_plan_accepted": "patients",
    "treatment_plan_paid": "patients",
    # payroll_accrual / payroll_paid / payroll_due are deliberately absent:
    # the 1C extension only ever sends payroll as a whole-month control
    # total (see tools/revora_1c_extension README), so there is no daily
    # granularity to fall back to for a partial range -- and there must
    # never be, since payroll cannot be prorated across days.
}

# Metrics whose daily rows are already a running, self-summing quantity
# (money, counts of events). Excluded here are the two patient metrics,
# which need DISTINCT-by-GUID counting across covered days instead of a
# plain SUM (a patient seen on two different covered days must count once).
_DISTINCT_PATIENT_METRICS = {
    "patients_total": "patient_seen",
    "patients_primary": "patient_primary_seen",
}


def month_windows(date_from: date, date_to: date) -> list[tuple[str, date, date]]:
    """Split [date_from, date_to] into per-calendar-month windows, each
    clipped to the requested range. E.g. 2026-05-15..2026-07-10 yields
    [("2026-05", 05-15, 05-31), ("2026-06", 06-01, 06-30), ("2026-07", 07-01, 07-10)].
    """
    windows: list[tuple[str, date, date]] = []
    cursor = date_from.replace(day=1)
    while cursor <= date_to:
        if cursor.month == 12:
            next_month = cursor.replace(year=cursor.year + 1, month=1, day=1)
        else:
            next_month = cursor.replace(month=cursor.month + 1, day=1)
        month_end = next_month - timedelta(days=1)
        window_start = max(cursor, date_from)
        window_end = min(month_end, date_to)
        windows.append((f"{cursor.year:04d}-{cursor.month:02d}", window_start, window_end))
        cursor = next_month
    return windows


def _build_coverage(
    date_from: date,
    date_to: date,
    windows: list[tuple[str, date, date]],
    covered_windows: list[tuple[str, date, date]],
    is_exact: bool = False,
) -> CoverageInfo:
    covered_keys = {key for key, _, _ in covered_windows}
    missing_keys = [key for key, _, _ in windows if key not in covered_keys]
    total_days = (date_to - date_from).days + 1
    covered_days = sum((end - start).days + 1 for _, start, end in covered_windows)
    covered_from = min((start for _, start, _ in covered_windows), default=None)
    covered_to = max((end for _, _, end in covered_windows), default=None)
    ratio = round(covered_days / total_days, 4) if total_days else 0.0
    return CoverageInfo(
        requested_from=date_from,
        requested_to=date_to,
        covered_from=date_from if is_exact else covered_from,
        covered_to=date_to if is_exact else covered_to,
        covered_months=sorted(covered_keys) if not is_exact else [key for key, _, _ in windows],
        missing_months=[] if is_exact else sorted(missing_keys),
        coverage_ratio=1.0 if is_exact else ratio,
        is_partial=(not is_exact) and bool(covered_keys) and bool(missing_keys),
        is_exact=is_exact,
    )


def _parse_snapshot_date(value: object) -> datetime | None:
    """Parses a 1C snapshot date field ("YYYY-MM-DD", ISO datetime, or
    already a date/datetime) into a tz-aware datetime at UTC midnight.
    Returns None for anything missing or unparsable -- a bad date must
    never crash ingestion, it just means that one field stays unknown."""
    from datetime import timezone as _timezone

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=_timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=_timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    for parser in (
        lambda v: datetime.strptime(v, "%Y-%m-%d"),
        lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
    ):
        try:
            parsed = parser(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=_timezone.utc)
        except ValueError:
            continue
    return None


def _positive_int(value: object) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return result if result > 0 else 0


def _build_patient_identity_row(tenant_id: UUID, metric: dict) -> dict | None:
    """Pure transform from one patient_phone_identity metric row into the
    values dict upsert_patient_identities writes to the patients table.
    Kept free of any DB/session dependency so the parsing and validation
    rules (bad phone_hash, missing external_id, deleted-patient flag, date
    parsing) are directly unit-testable without a live database. Returns
    None when the row cannot be identified by a stable external_id at all --
    everything else degrades gracefully instead of dropping the patient.
    """
    if metric.get("metric_code") != "patient_phone_identity":
        return None
    external_id = str(metric.get("dimension_key") or "").strip()
    if not external_id or external_id == "empty":
        return None
    details = metric.get("details") or {}
    phone_hash = str(details.get("phone_hash") or "").strip() or None
    if phone_hash is not None and len(phone_hash) != 64:
        # Not a well-formed SHA-256 hex digest -- never trust it for
        # matching; keep the patient row, drop only the bad hash.
        phone_hash = None
    full_name = str(details.get("full_name") or metric.get("dimension_label") or "").strip() or None
    return {
        "tenant_id": tenant_id,
        "external_id": external_id,
        "full_name": full_name,
        "phone_hash": phone_hash,
        "branch_id": metric.get("branch_id"),
        "first_visit_at": _parse_snapshot_date(details.get("first_visit_at")),
        "last_visit_at": _parse_snapshot_date(details.get("last_visit_at")),
        "visit_count": _positive_int(details.get("visit_count")),
        "is_active": bool(details.get("active", True)),
    }


class OfficialReportsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def branches_by_code(self, tenant_id: UUID) -> dict[str, Branch]:
        rows = await self.session.scalars(
            select(Branch).where(Branch.tenant_id == tenant_id, Branch.is_active.is_(True))
        )
        return {row.code: row for row in rows}

    async def duplicate(
        self, tenant_id: UUID, report_type: str, period_from: date,
        period_to: date, source_hash: str,
    ) -> OfficialReportImport | None:
        return await self.session.scalar(
            select(OfficialReportImport)
            .options(selectinload(OfficialReportImport.metrics))
            .where(
                OfficialReportImport.tenant_id == tenant_id,
                OfficialReportImport.report_type == report_type,
                OfficialReportImport.period_from == period_from,
                OfficialReportImport.period_to == period_to,
                OfficialReportImport.source_hash == source_hash,
            )
        )

    async def replace_active(
        self, *, tenant_id: UUID, report_type: str, period_from: date,
        period_to: date, source_filename: str, source_hash: str,
        imported_by_user_id: UUID | None, summary: dict, metrics: list[dict],
    ) -> OfficialReportImport:
        await self.session.execute(
            update(OfficialReportImport)
            .where(
                OfficialReportImport.tenant_id == tenant_id,
                OfficialReportImport.report_type == report_type,
                OfficialReportImport.period_from == period_from,
                OfficialReportImport.period_to == period_to,
                OfficialReportImport.is_active.is_(True),
            )
            .values(is_active=False)
        )
        report = OfficialReportImport(
            tenant_id=tenant_id, report_type=report_type,
            period_from=period_from, period_to=period_to,
            source_filename=source_filename, source_hash=source_hash,
            imported_by_user_id=imported_by_user_id, summary=summary,
            is_active=True,
        )
        report.metrics = [OfficialReportMetric(tenant_id=tenant_id, **metric) for metric in metrics]
        self.session.add(report)
        await self.session.flush()
        return report

    async def upsert_patient_identities(self, tenant_id: UUID, metrics: list[dict]) -> int:
        """Materialize patient_phone_identity metric rows into the patients
        table so ContactRegistry can match inbound calls/WhatsApp against
        real 1C patients by phone_hash. The raw metric rows already landed
        in official_report_metrics via replace_active (that's the audited,
        idempotent ledger); this is a derived, upsert-only projection keyed
        on the same stable external_id 1C sends every time -- resending an
        unchanged snapshot just rewrites the same values, never duplicates.

        Never receives or stores a plaintext phone number: only phone_hash
        (already SHA-256'd by the 1C extension) ever reaches this table.
        A row missing phone_hash, dimension_key or a parseable date is
        skipped rather than aborting the whole batch -- one bad record must
        not block every other patient in the same snapshot. Two different
        patients legitimately sharing one phone_hash (a shared household or
        family number) are both kept as distinct rows -- the uniqueness
        constraint is (tenant_id, external_id), never phone_hash.
        """
        upserted = 0
        for metric in metrics:
            values = _build_patient_identity_row(tenant_id, metric)
            if values is None:
                continue
            statement = pg_insert(Patient).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=["tenant_id", "external_id"],
                set_={
                    "full_name": statement.excluded.full_name,
                    "phone_hash": statement.excluded.phone_hash,
                    "branch_id": statement.excluded.branch_id,
                    "first_visit_at": statement.excluded.first_visit_at,
                    "last_visit_at": statement.excluded.last_visit_at,
                    "visit_count": statement.excluded.visit_count,
                    "is_active": statement.excluded.is_active,
                },
            )
            await self.session.execute(statement)
            upserted += 1
        return upserted

    async def activate_existing(self, report: OfficialReportImport) -> OfficialReportImport:
        await self.session.execute(
            update(OfficialReportImport)
            .where(
                OfficialReportImport.tenant_id == report.tenant_id,
                OfficialReportImport.report_type == report.report_type,
                OfficialReportImport.period_from == report.period_from,
                OfficialReportImport.period_to == report.period_to,
                OfficialReportImport.id != report.id,
            )
            .values(is_active=False)
        )
        report.is_active = True
        await self.session.flush()
        return report

    async def list_active(self, tenant_id: UUID) -> list[OfficialReportImport]:
        return list((await self.session.scalars(
            select(OfficialReportImport)
            .options(selectinload(OfficialReportImport.metrics))
            .where(OfficialReportImport.tenant_id == tenant_id, OfficialReportImport.is_active.is_(True))
            .order_by(OfficialReportImport.period_from.desc(), OfficialReportImport.report_type)
        )).all())

    async def exact_values(
        self, tenant_id: UUID, date_from: date, date_to: date,
        metric_codes: set[str], branch_ids: list[UUID] | None,
    ) -> tuple[dict[str, Decimal], datetime | None, dict[str, CoverageInfo]]:
        """Resolve official 1C values for `metric_codes` over [date_from, date_to].

        Priority order, per metric:
        1. An uploaded control-total report whose period matches the
           requested range exactly -> authoritative, is_exact coverage.
        2. Otherwise, sum whatever complete calendar months of daily
           snapshots exist inside the range (never a partial month, never
           an interpolated/averaged figure) and report exactly which
           months were used and which were not via CoverageInfo.

        A metric with zero covered months is simply absent from the
        returned values dict (coverage_ratio=0, covered_months=[]) --
        callers already fall back to Revora's own computed total for an
        absent metric, and now also have the coverage detail to tell a
        genuine "nothing to show" apart from a partial figure.
        """
        scope_conditions = self._scope_conditions(branch_ids)
        base_conditions = [
            OfficialReportMetric.tenant_id == tenant_id,
            OfficialReportImport.tenant_id == tenant_id,
            OfficialReportImport.is_active.is_(True),
            *scope_conditions,
        ]

        exact, exact_as_of = await self._grouped_values(
            base_conditions, metric_codes,
            OfficialReportImport.period_from == date_from,
            OfficialReportImport.period_to == date_to,
        )
        windows = month_windows(date_from, date_to)
        if exact:
            coverage = {
                code: _build_coverage(date_from, date_to, windows, windows, is_exact=True)
                for code in exact
            }
            return exact, exact_as_of, coverage

        report_types_needed = {
            REPORT_TYPE_BY_METRIC.get(code) for code in metric_codes
        } - {None}
        coverage_by_report_type = await self._month_coverage(
            tenant_id, report_types_needed, windows
        )

        values: dict[str, Decimal] = {}
        timestamps: list[datetime] = []
        coverage: dict[str, CoverageInfo] = {}
        additive_codes = metric_codes - set(_DISTINCT_PATIENT_METRICS)

        for code in additive_codes:
            report_type = REPORT_TYPE_BY_METRIC.get(code)
            covered_windows = coverage_by_report_type.get(report_type, [])
            coverage[code] = _build_coverage(date_from, date_to, windows, covered_windows)
            if not covered_windows:
                continue
            value, ts = await self._sum_daily_metric(
                base_conditions, code, covered_windows
            )
            if value is not None:
                values[code] = value
                if ts is not None:
                    timestamps.append(ts)

        for result_code, marker_code in _DISTINCT_PATIENT_METRICS.items():
            if result_code not in metric_codes:
                continue
            report_type = REPORT_TYPE_BY_METRIC[result_code]
            covered_windows = coverage_by_report_type.get(report_type, [])
            coverage[result_code] = _build_coverage(date_from, date_to, windows, covered_windows)
            if not covered_windows:
                continue
            count, ts = await self._distinct_marker_count(
                tenant_id, marker_code, covered_windows, branch_ids
            )
            if count:
                values[result_code] = Decimal(count)
            if ts is not None:
                timestamps.append(ts)

        return values, (max(timestamps) if timestamps else None), coverage

    async def exact_dimension_metrics(
        self, tenant_id: UUID, date_from: date, date_to: date,
        metric_code: str, dimension_type: str, branch_ids: list[UUID] | None,
    ) -> tuple[list[ReportMetricValue], datetime | None, CoverageInfo]:
        base_conditions = [
            OfficialReportMetric.tenant_id == tenant_id,
            OfficialReportMetric.metric_code == metric_code,
            OfficialReportMetric.dimension_type == dimension_type,
            OfficialReportImport.tenant_id == tenant_id,
            OfficialReportImport.is_active.is_(True),
        ]
        if branch_ids is not None:
            base_conditions.append(OfficialReportMetric.branch_id.in_(branch_ids))

        async def grouped_metrics(*period_conditions) -> tuple[list[ReportMetricValue], datetime | None]:
            rows = (await self.session.execute(
                select(
                    OfficialReportMetric.dimension_key,
                    OfficialReportMetric.dimension_label,
                    func.sum(OfficialReportMetric.value),
                    func.max(OfficialReportImport.created_at),
                )
                .join(OfficialReportImport, OfficialReportImport.id == OfficialReportMetric.report_id)
                .where(*base_conditions, *period_conditions)
                .group_by(
                    OfficialReportMetric.dimension_key,
                    OfficialReportMetric.dimension_label,
                )
            )).all()
            metrics = [
                ReportMetricValue(
                    dimension_key=str(row[0]),
                    dimension_label=str(row[1]),
                    value=Decimal(row[2]),
                )
                for row in rows
            ]
            timestamps = [row[3] for row in rows if row[3] is not None]
            return metrics, max(timestamps) if timestamps else None

        windows = month_windows(date_from, date_to)
        exact, exact_as_of = await grouped_metrics(
            OfficialReportImport.period_from == date_from,
            OfficialReportImport.period_to == date_to,
        )
        if exact:
            return exact, exact_as_of, _build_coverage(date_from, date_to, windows, windows, is_exact=True)

        report_type = REPORT_TYPE_BY_METRIC.get(metric_code)
        coverage_by_report_type = await self._month_coverage(tenant_id, {report_type} - {None}, windows)
        covered_windows = coverage_by_report_type.get(report_type, [])
        coverage = _build_coverage(date_from, date_to, windows, covered_windows)
        if not covered_windows:
            return [], None, coverage

        window_condition = or_(*[
            and_(
                OfficialReportImport.period_from >= start,
                OfficialReportImport.period_to <= end,
            )
            for _, start, end in covered_windows
        ])
        metrics, as_of = await grouped_metrics(
            OfficialReportImport.period_from == OfficialReportImport.period_to,
            window_condition,
        )
        return metrics, as_of, coverage

    async def _grouped_values(
        self, base_conditions: list, metric_codes: set[str], *period_conditions,
    ) -> tuple[dict[str, Decimal], datetime | None]:
        rows = (await self.session.execute(
            select(
                OfficialReportMetric.metric_code,
                func.sum(OfficialReportMetric.value),
                func.max(OfficialReportImport.created_at),
            )
            .join(OfficialReportImport, OfficialReportImport.id == OfficialReportMetric.report_id)
            .where(
                *base_conditions,
                OfficialReportMetric.metric_code.in_(metric_codes),
                *period_conditions,
            )
            .group_by(OfficialReportMetric.metric_code)
        )).all()
        values = {str(row[0]): Decimal(row[1]) for row in rows}
        timestamps = [row[2] for row in rows if row[2] is not None]
        return values, max(timestamps) if timestamps else None

    async def _sum_daily_metric(
        self, base_conditions: list, code: str,
        covered_windows: list[tuple[str, date, date]],
    ) -> tuple[Decimal | None, datetime | None]:
        window_condition = or_(*[
            and_(
                OfficialReportImport.period_from >= start,
                OfficialReportImport.period_to <= end,
            )
            for _, start, end in covered_windows
        ])
        row = (await self.session.execute(
            select(
                func.sum(OfficialReportMetric.value),
                func.max(OfficialReportImport.created_at),
            )
            .join(OfficialReportImport, OfficialReportImport.id == OfficialReportMetric.report_id)
            .where(
                *base_conditions,
                OfficialReportMetric.metric_code == code,
                OfficialReportImport.period_from == OfficialReportImport.period_to,
                window_condition,
            )
        )).one()
        value = Decimal(row[0]) if row[0] is not None else None
        return value, row[1]

    async def _distinct_marker_count(
        self, tenant_id: UUID, marker_code: str,
        covered_windows: list[tuple[str, date, date]], branch_ids: list[UUID] | None,
    ) -> tuple[int, datetime | None]:
        window_condition = or_(*[
            and_(
                OfficialReportImport.period_from >= start,
                OfficialReportImport.period_to <= end,
            )
            for _, start, end in covered_windows
        ])
        marker_conditions = [
            OfficialReportMetric.tenant_id == tenant_id,
            OfficialReportImport.tenant_id == tenant_id,
            OfficialReportImport.is_active.is_(True),
            OfficialReportImport.period_from == OfficialReportImport.period_to,
            window_condition,
            OfficialReportMetric.metric_code == marker_code,
            OfficialReportMetric.dimension_type == "patient",
        ]
        if branch_ids is not None:
            marker_conditions.append(OfficialReportMetric.branch_id.in_(branch_ids))
        row = (await self.session.execute(
            select(
                func.count(func.distinct(OfficialReportMetric.dimension_key)),
                func.max(OfficialReportImport.created_at),
            )
            .join(OfficialReportImport, OfficialReportImport.id == OfficialReportMetric.report_id)
            .where(*marker_conditions)
        )).one()
        return int(row[0] or 0), row[1]

    async def _month_coverage(
        self, tenant_id: UUID, report_types: set[str],
        windows: list[tuple[str, date, date]],
    ) -> dict[str, list[tuple[str, date, date]]]:
        """For each report_type, which month-windows have every one of
        their days present as a daily (period_from == period_to) import."""
        result: dict[str, list[tuple[str, date, date]]] = {}
        if not report_types or not windows:
            return result
        range_start = windows[0][1]
        range_end = windows[-1][2]
        rows = (await self.session.execute(
            select(OfficialReportImport.report_type, OfficialReportImport.period_from)
            .where(
                OfficialReportImport.tenant_id == tenant_id,
                OfficialReportImport.is_active.is_(True),
                OfficialReportImport.report_type.in_(report_types),
                OfficialReportImport.period_from == OfficialReportImport.period_to,
                OfficialReportImport.period_from >= range_start,
                OfficialReportImport.period_to <= range_end,
            )
        )).all()
        present_days: dict[str, set[date]] = {}
        for report_type, day in rows:
            present_days.setdefault(str(report_type), set()).add(day)
        for report_type in report_types:
            days = present_days.get(report_type, set())
            covered: list[tuple[str, date, date]] = []
            for month_key, start, end in windows:
                expected = (end - start).days + 1
                have = sum(1 for day in days if start <= day <= end)
                if have == expected:
                    covered.append((month_key, start, end))
            result[report_type] = covered
        return result

    @staticmethod
    def _scope_conditions(branch_ids: list[UUID] | None) -> list:
        if branch_ids is None:
            return [
                OfficialReportMetric.dimension_type == "clinic",
                OfficialReportMetric.branch_id.is_(None),
            ]
        return [
            OfficialReportMetric.dimension_type == "branch",
            OfficialReportMetric.branch_id.in_(branch_ids),
        ]
