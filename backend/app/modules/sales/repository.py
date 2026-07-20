"""Aggregate sales and appointment facts."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import RevenueFact
from app.modules.sales.models import Appointment, Lead


@dataclass(frozen=True)
class SalesTotals:
    leads_total: int
    leads_new: int
    leads_won: int
    leads_lost: int
    appointments_total: int
    appointments_completed: int
    appointments_cancelled: int
    appointments_no_show: int
    paid_revenue: Decimal
    data_as_of: datetime | None


class SalesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_ids: list[UUID] | None,
        assigned_user_id: UUID | None,
    ) -> SalesTotals:
        lead_statement = select(
            func.count(Lead.id),
            func.sum(case((Lead.status == "new", 1), else_=0)),
            func.sum(case((Lead.status.in_(["won", "converted"]), 1), else_=0)),
            func.sum(case((Lead.status == "lost", 1), else_=0)),
            func.max(Lead.updated_at),
        ).where(
            Lead.tenant_id == tenant_id,
            Lead.created_at >= self._start(date_from),
            Lead.created_at < self._end(date_to),
        )
        if branch_ids is not None:
            lead_statement = lead_statement.where(Lead.branch_id.in_(branch_ids))
        if assigned_user_id:
            lead_statement = lead_statement.where(Lead.assigned_user_id == assigned_user_id)
        lead_row = (await self.session.execute(lead_statement)).one()

        scoped_patient_ids = select(Lead.patient_id).where(
            Lead.tenant_id == tenant_id, Lead.patient_id.is_not(None)
        )
        if branch_ids is not None:
            scoped_patient_ids = scoped_patient_ids.where(Lead.branch_id.in_(branch_ids))
        if assigned_user_id:
            scoped_patient_ids = scoped_patient_ids.where(Lead.assigned_user_id == assigned_user_id)

        appointment_statement = select(
            func.count(Appointment.id),
            func.sum(case((Appointment.status == "completed", 1), else_=0)),
            func.sum(case((Appointment.status == "cancelled", 1), else_=0)),
            func.sum(case((Appointment.status == "no_show", 1), else_=0)),
            func.max(Appointment.updated_at),
        ).where(
            Appointment.tenant_id == tenant_id,
            Appointment.starts_at >= self._start(date_from),
            Appointment.starts_at < self._end(date_to),
        )
        if branch_ids is not None:
            appointment_statement = appointment_statement.where(
                Appointment.branch_id.in_(branch_ids)
            )
        if assigned_user_id:
            appointment_statement = appointment_statement.where(
                Appointment.patient_id.in_(scoped_patient_ids)
            )
        appointment_row = (await self.session.execute(appointment_statement)).one()

        revenue_statement = select(
            func.coalesce(func.sum(RevenueFact.amount), 0), func.max(RevenueFact.updated_at)
        ).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.recognition_type == "payment",
            RevenueFact.occurred_at >= self._start(date_from),
            RevenueFact.occurred_at < self._end(date_to),
        )
        if branch_ids is not None:
            revenue_statement = revenue_statement.where(RevenueFact.branch_id.in_(branch_ids))
        if assigned_user_id:
            revenue_statement = revenue_statement.where(
                RevenueFact.patient_id.in_(scoped_patient_ids)
            )
        revenue_row = (await self.session.execute(revenue_statement)).one()
        timestamps = [
            value for value in (lead_row[4], appointment_row[4], revenue_row[1]) if value
        ]
        return SalesTotals(
            leads_total=int(lead_row[0] or 0),
            leads_new=int(lead_row[1] or 0),
            leads_won=int(lead_row[2] or 0),
            leads_lost=int(lead_row[3] or 0),
            appointments_total=int(appointment_row[0] or 0),
            appointments_completed=int(appointment_row[1] or 0),
            appointments_cancelled=int(appointment_row[2] or 0),
            appointments_no_show=int(appointment_row[3] or 0),
            paid_revenue=Decimal(revenue_row[0]),
            data_as_of=max(timestamps) if timestamps else None,
        )

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _end(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)
