"""Persistence and period lookup for official and daily 1C metrics."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.reports.models import OfficialReportImport, OfficialReportMetric
from app.modules.tenancy.models import Branch


@dataclass(frozen=True)
class ReportMetricValue:
    dimension_key: str
    dimension_label: str
    value: Decimal
    branch_id: UUID | None = None


REPORT_TYPE_BY_METRIC = {
    "revenue_payment": "cash_receipts",
    "cash_inflow": "cash_receipts",
    "services_count": "service_revenue",
    "revenue_accrual": "service_revenue",
    "revenue_before_discount": "service_revenue",
    "doctor_revenue_payment": "doctor_revenue",
    "purchases_accrual_all_entities": "purchases",
    "purchases_paid_all_entities": "purchases",
    "purchases_accrual": "purchases",
    "purchases_paid": "purchases",
    "patients_total": "patients",
    "patients_primary": "patients",
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
    ) -> tuple[dict[str, Decimal], datetime | None]:
        scope_conditions = []
        if branch_ids is None:
            scope_conditions.extend([
                OfficialReportMetric.dimension_type == "clinic",
                OfficialReportMetric.branch_id.is_(None),
            ])
        else:
            scope_conditions.extend([
                OfficialReportMetric.dimension_type == "branch",
                OfficialReportMetric.branch_id.in_(branch_ids),
            ])

        base_conditions = [
            OfficialReportMetric.tenant_id == tenant_id,
            OfficialReportImport.tenant_id == tenant_id,
            OfficialReportImport.is_active.is_(True),
            *scope_conditions,
        ]

        async def grouped_values(*period_conditions) -> tuple[dict[str, Decimal], datetime | None]:
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

        exact, exact_as_of = await grouped_values(
            OfficialReportImport.period_from == date_from,
            OfficialReportImport.period_to == date_to,
        )
        if exact:
            return exact, exact_as_of

        covered_report_types = await self._daily_coverage(tenant_id, date_from, date_to)

        additive_codes = metric_codes - {"patients_total", "patients_primary"}
        daily_values: dict[str, Decimal] = {}
        timestamps: list[datetime] = []
        if additive_codes:
            rows = (await self.session.execute(
                select(
                    OfficialReportMetric.metric_code,
                    func.sum(OfficialReportMetric.value),
                    func.max(OfficialReportImport.created_at),
                )
                .join(OfficialReportImport, OfficialReportImport.id == OfficialReportMetric.report_id)
                .where(
                    *base_conditions,
                    OfficialReportMetric.metric_code.in_(additive_codes),
                    OfficialReportImport.period_from == OfficialReportImport.period_to,
                    OfficialReportImport.period_from >= date_from,
                    OfficialReportImport.period_to <= date_to,
                )
                .group_by(OfficialReportMetric.metric_code)
            )).all()
            for row in rows:
                code = str(row[0])
                if REPORT_TYPE_BY_METRIC.get(code) not in covered_report_types:
                    continue
                daily_values[code] = Decimal(row[1])
                if row[2] is not None:
                    timestamps.append(row[2])

        for result_code, marker_code in {
            "patients_total": "patient_seen",
            "patients_primary": "patient_primary_seen",
        }.items():
            if result_code not in metric_codes:
                continue
            if REPORT_TYPE_BY_METRIC[result_code] not in covered_report_types:
                continue
            marker_conditions = [
                OfficialReportMetric.tenant_id == tenant_id,
                OfficialReportImport.tenant_id == tenant_id,
                OfficialReportImport.is_active.is_(True),
                OfficialReportImport.period_from == OfficialReportImport.period_to,
                OfficialReportImport.period_from >= date_from,
                OfficialReportImport.period_to <= date_to,
                OfficialReportMetric.metric_code == marker_code,
                OfficialReportMetric.dimension_type == "patient",
            ]
            if branch_ids is not None:
                marker_conditions.append(OfficialReportMetric.branch_id.in_(branch_ids))
            marker_row = (await self.session.execute(
                select(
                    func.count(func.distinct(OfficialReportMetric.dimension_key)),
                    func.max(OfficialReportImport.created_at),
                )
                .join(OfficialReportImport, OfficialReportImport.id == OfficialReportMetric.report_id)
                .where(*marker_conditions)
            )).one()
            if marker_row[0]:
                daily_values[result_code] = Decimal(marker_row[0])
            if marker_row[1] is not None:
                timestamps.append(marker_row[1])
        return daily_values, max(timestamps) if timestamps else None

    async def exact_dimension_metrics(
        self, tenant_id: UUID, date_from: date, date_to: date,
        metric_code: str, dimension_type: str, branch_ids: list[UUID] | None,
    ) -> tuple[list[ReportMetricValue], datetime | None]:
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

        exact, exact_as_of = await grouped_metrics(
            OfficialReportImport.period_from == date_from,
            OfficialReportImport.period_to == date_to,
        )
        if exact:
            return exact, exact_as_of
        if REPORT_TYPE_BY_METRIC.get(metric_code) not in await self._daily_coverage(
            tenant_id, date_from, date_to
        ):
            return [], None
        return await grouped_metrics(
            OfficialReportImport.period_from == OfficialReportImport.period_to,
            OfficialReportImport.period_from >= date_from,
            OfficialReportImport.period_to <= date_to,
        )

    async def _daily_coverage(
        self, tenant_id: UUID, date_from: date, date_to: date
    ) -> set[str]:
        expected_days = (date_to - date_from).days + 1
        rows = (await self.session.execute(
            select(
                OfficialReportImport.report_type,
                func.count(func.distinct(OfficialReportImport.period_from)),
            )
            .where(
                OfficialReportImport.tenant_id == tenant_id,
                OfficialReportImport.is_active.is_(True),
                OfficialReportImport.period_from == OfficialReportImport.period_to,
                OfficialReportImport.period_from >= date_from,
                OfficialReportImport.period_to <= date_to,
            )
            .group_by(OfficialReportImport.report_type)
        )).all()
        return {str(row[0]) for row in rows if int(row[1]) == expected_days}
