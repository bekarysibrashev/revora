from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import case, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ml.models import (
    MLDatasetSnapshot,
    MLExperiment,
    MLModelVersion,
    MLPrediction,
)
from app.modules.sales.models import Appointment, Patient


@dataclass(frozen=True)
class ReadinessStats:
    row_count: int
    positive_count: int
    date_min: datetime | None
    date_max: datetime | None
    source_max_updated_at: datetime | None
    doctor_count: int
    direction_count: int
    lead_source_count: int
    lead_time_count: int


@dataclass(frozen=True)
class CohortStats:
    dimension: str
    value: str
    appointments: int
    no_shows: int


class MLRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def readiness(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> ReadinessStats:
        base = [
            Appointment.tenant_id == tenant_id,
            Appointment.status.in_(["completed", "no_show"]),
            Appointment.starts_at >= self._start(date_from),
            Appointment.starts_at < self._end(date_to),
        ]
        if branch_id:
            base.append(Appointment.branch_id == branch_id)
        statement = (
            select(
                func.count(Appointment.id),
                func.sum(case((Appointment.status == "no_show", 1), else_=0)),
                func.min(Appointment.starts_at),
                func.max(Appointment.starts_at),
                func.max(Appointment.updated_at),
                func.sum(case((Appointment.doctor_id.is_not(None), 1), else_=0)),
                func.sum(case((Appointment.direction_id.is_not(None), 1), else_=0)),
                func.sum(case((Patient.lead_source.is_not(None), 1), else_=0)),
                func.sum(
                    case(
                        (
                            Appointment.created_at.is_not(None)
                            & (Appointment.starts_at >= Appointment.created_at),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .select_from(Appointment)
            .join(Patient, Patient.id == Appointment.patient_id)
            .where(*base)
        )
        row = (await self.session.execute(statement)).one()
        return ReadinessStats(
            row_count=int(row[0] or 0),
            positive_count=int(row[1] or 0),
            date_min=row[2],
            date_max=row[3],
            source_max_updated_at=row[4],
            doctor_count=int(row[5] or 0),
            direction_count=int(row[6] or 0),
            lead_source_count=int(row[7] or 0),
            lead_time_count=int(row[8] or 0),
        )

    async def cohorts(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> list[CohortStats]:
        base = [
            Appointment.tenant_id == tenant_id,
            Appointment.status.in_(["completed", "no_show"]),
            Appointment.starts_at >= self._start(date_from),
            Appointment.starts_at < self._end(date_to),
        ]
        if branch_id:
            base.append(Appointment.branch_id == branch_id)

        weekday = extract("dow", Appointment.starts_at)
        weekday_query = (
            select(
                weekday.label("value"),
                func.count(Appointment.id),
                func.sum(case((Appointment.status == "no_show", 1), else_=0)),
            )
            .where(*base)
            .group_by(weekday)
            .order_by(weekday)
        )
        hour_bucket = case(
            (extract("hour", Appointment.starts_at) < 12, "morning"),
            (extract("hour", Appointment.starts_at) < 17, "afternoon"),
            else_="evening",
        )
        hour_query = (
            select(
                hour_bucket.label("value"),
                func.count(Appointment.id),
                func.sum(case((Appointment.status == "no_show", 1), else_=0)),
            )
            .where(*base)
            .group_by(hour_bucket)
            .order_by(hour_bucket)
        )
        items = [
            CohortStats("weekday", str(int(row[0])), int(row[1]), int(row[2] or 0))
            for row in (await self.session.execute(weekday_query)).all()
        ]
        items.extend(
            CohortStats("time_of_day", str(row[0]), int(row[1]), int(row[2] or 0))
            for row in (await self.session.execute(hour_query)).all()
        )
        return items

    async def create_snapshot(
        self,
        tenant_id: UUID,
        branch_id: UUID | None,
        date_from: date,
        date_to: date,
        stats: ReadinessStats,
        feature_schema: dict,
        quality_report: dict,
    ) -> MLDatasetSnapshot:
        source_stamp = (
            stats.source_max_updated_at.isoformat()
            if stats.source_max_updated_at
            else "none"
        )
        raw_key = (
            f"{tenant_id}:{branch_id}:{date_from}:{date_to}:"
            f"{stats.row_count}:{stats.positive_count}:{source_stamp}"
        )
        snapshot_key = sha256(raw_key.encode("utf-8")).hexdigest()
        existing = await self.session.scalar(
            select(MLDatasetSnapshot).where(
                MLDatasetSnapshot.tenant_id == tenant_id,
                MLDatasetSnapshot.snapshot_key == snapshot_key,
            )
        )
        if existing:
            return existing
        snapshot = MLDatasetSnapshot(
            tenant_id=tenant_id,
            branch_id=branch_id,
            purpose="appointment_no_show",
            snapshot_key=snapshot_key,
            date_from=date_from,
            date_to=date_to,
            row_count=stats.row_count,
            positive_count=stats.positive_count,
            feature_schema=feature_schema,
            quality_report=quality_report,
            source_max_updated_at=stats.source_max_updated_at,
        )
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot

    async def list_snapshots(self, tenant_id: UUID) -> list[MLDatasetSnapshot]:
        return list(
            (
                await self.session.scalars(
                    select(MLDatasetSnapshot)
                    .where(MLDatasetSnapshot.tenant_id == tenant_id)
                    .order_by(MLDatasetSnapshot.created_at.desc())
                    .limit(50)
                )
            ).all()
        )

    async def registry_counts(self, tenant_id: UUID) -> tuple[int, int, int, int, bool]:
        async def count(model):
            return int(
                (
                    await self.session.scalar(
                        select(func.count(model.id)).where(model.tenant_id == tenant_id)
                    )
                )
                or 0
            )

        datasets = await count(MLDatasetSnapshot)
        experiments = await count(MLExperiment)
        versions = await count(MLModelVersion)
        predictions = await count(MLPrediction)
        active = bool(
            await self.session.scalar(
                select(MLModelVersion.id)
                .where(
                    MLModelVersion.tenant_id == tenant_id,
                    MLModelVersion.status == "active",
                )
                .limit(1)
            )
        )
        return datasets, experiments, versions, predictions, active

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=UTC)

    @staticmethod
    def _end(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=UTC)
