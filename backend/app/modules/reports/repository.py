"""Persistence and exact-period lookup for official 1C control totals."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.reports.models import OfficialReportImport, OfficialReportMetric
from app.modules.tenancy.models import Branch


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
        imported_by_user_id: UUID, summary: dict, metrics: list[dict],
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
        conditions = [
            OfficialReportMetric.tenant_id == tenant_id,
            OfficialReportImport.tenant_id == tenant_id,
            OfficialReportImport.period_from == date_from,
            OfficialReportImport.period_to == date_to,
            OfficialReportImport.is_active.is_(True),
            OfficialReportMetric.metric_code.in_(metric_codes),
        ]
        if branch_ids is None:
            conditions.extend([
                OfficialReportMetric.dimension_type == "clinic",
                OfficialReportMetric.branch_id.is_(None),
            ])
        else:
            conditions.extend([
                OfficialReportMetric.dimension_type == "branch",
                OfficialReportMetric.branch_id.in_(branch_ids),
            ])
        rows = (await self.session.execute(
            select(
                OfficialReportMetric.metric_code,
                func.sum(OfficialReportMetric.value),
                func.max(OfficialReportImport.created_at),
            )
            .join(OfficialReportImport, OfficialReportImport.id == OfficialReportMetric.report_id)
            .where(*conditions)
            .group_by(OfficialReportMetric.metric_code)
        )).all()
        values = {str(row[0]): Decimal(row[1]) for row in rows}
        timestamps = [row[2] for row in rows if row[2] is not None]
        return values, max(timestamps) if timestamps else None

    async def exact_dimension_metrics(
        self, tenant_id: UUID, date_from: date, date_to: date,
        metric_code: str, dimension_type: str, branch_ids: list[UUID] | None,
    ) -> tuple[list[OfficialReportMetric], datetime | None]:
        statement = (
            select(OfficialReportMetric, OfficialReportImport.created_at)
            .join(OfficialReportImport, OfficialReportImport.id == OfficialReportMetric.report_id)
            .where(
                OfficialReportMetric.tenant_id == tenant_id,
                OfficialReportMetric.metric_code == metric_code,
                OfficialReportMetric.dimension_type == dimension_type,
                OfficialReportImport.period_from == date_from,
                OfficialReportImport.period_to == date_to,
                OfficialReportImport.is_active.is_(True),
            )
        )
        if branch_ids is not None:
            statement = statement.where(OfficialReportMetric.branch_id.in_(branch_ids))
        rows = (await self.session.execute(statement)).all()
        timestamps = [row[1] for row in rows if row[1]]
        return [row[0] for row in rows], max(timestamps) if timestamps else None
