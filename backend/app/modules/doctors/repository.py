from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.doctors.models import Doctor, DoctorRating
from app.modules.finance.models import RevenueFact
from app.modules.sales.models import Appointment


@dataclass(frozen=True)
class DoctorTotals:
    doctor_id: UUID
    full_name: str
    specialty: str | None
    appointments_total: int
    appointments_completed: int
    revenue_accrual: Decimal
    revenue_payment: Decimal
    average_rating: Decimal | None
    data_as_of: datetime | None


class DoctorsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_ids: list[UUID] | None,
    ) -> list[DoctorTotals]:
        appointments = (
            select(
                Appointment.doctor_id.label("doctor_id"),
                func.count(Appointment.id).label("appointments_total"),
                func.sum(case((Appointment.status == "completed", 1), else_=0)).label(
                    "appointments_completed"
                ),
                func.max(Appointment.updated_at).label("appointments_as_of"),
            )
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.doctor_id.is_not(None),
                Appointment.starts_at >= self._start(date_from),
                Appointment.starts_at < self._end(date_to),
            )
            .group_by(Appointment.doctor_id)
        )
        if branch_ids is not None:
            appointments = appointments.where(Appointment.branch_id.in_(branch_ids))
        appointments = appointments.subquery()

        revenue = (
            select(
                RevenueFact.doctor_id.label("doctor_id"),
                func.sum(
                    case((RevenueFact.recognition_type == "accrual", RevenueFact.amount), else_=0)
                ).label("revenue_accrual"),
                func.sum(
                    case((RevenueFact.recognition_type == "payment", RevenueFact.amount), else_=0)
                ).label("revenue_payment"),
                func.max(RevenueFact.updated_at).label("revenue_as_of"),
            )
            .where(
                RevenueFact.tenant_id == tenant_id,
                RevenueFact.doctor_id.is_not(None),
                RevenueFact.occurred_at >= self._start(date_from),
                RevenueFact.occurred_at < self._end(date_to),
            )
            .group_by(RevenueFact.doctor_id)
        )
        if branch_ids is not None:
            revenue = revenue.where(RevenueFact.branch_id.in_(branch_ids))
        revenue = revenue.subquery()

        ratings = (
            select(
                DoctorRating.doctor_id.label("doctor_id"),
                func.avg(DoctorRating.rating).label("average_rating"),
                func.max(DoctorRating.updated_at).label("rating_as_of"),
            )
            .where(DoctorRating.tenant_id == tenant_id)
            .group_by(DoctorRating.doctor_id)
            .subquery()
        )
        statement = (
            select(
                Doctor.id,
                Doctor.full_name,
                Doctor.specialty,
                func.coalesce(appointments.c.appointments_total, 0),
                func.coalesce(appointments.c.appointments_completed, 0),
                func.coalesce(revenue.c.revenue_accrual, 0),
                func.coalesce(revenue.c.revenue_payment, 0),
                ratings.c.average_rating,
                func.greatest(
                    appointments.c.appointments_as_of,
                    revenue.c.revenue_as_of,
                    ratings.c.rating_as_of,
                ),
            )
            .outerjoin(appointments, appointments.c.doctor_id == Doctor.id)
            .outerjoin(revenue, revenue.c.doctor_id == Doctor.id)
            .outerjoin(ratings, ratings.c.doctor_id == Doctor.id)
            .where(Doctor.tenant_id == tenant_id)
            .order_by(func.coalesce(revenue.c.revenue_accrual, 0).desc(), Doctor.full_name)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            DoctorTotals(
                doctor_id=row[0],
                full_name=row[1],
                specialty=row[2],
                appointments_total=int(row[3]),
                appointments_completed=int(row[4]),
                revenue_accrual=Decimal(row[5]),
                revenue_payment=Decimal(row[6]),
                average_rating=Decimal(row[7]) if row[7] is not None else None,
                data_as_of=row[8],
            )
            for row in rows
        ]

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _end(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)
