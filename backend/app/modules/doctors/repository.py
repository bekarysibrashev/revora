from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import re
import unicodedata
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.doctors.models import Doctor, DoctorRating
from app.modules.finance.models import RevenueFact
from app.modules.reports.reconciliation import (
    DimensionReconciliation,
    reconcile_dimension,
)
from app.modules.reports.repository import CoverageInfo, OfficialReportsRepository
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
    ) -> tuple[list[DoctorTotals], CoverageInfo]:
        appointments = (
            select(
                Appointment.doctor_id.label("doctor_id"),
                func.count(Appointment.id).label("appointments_total"),
                func.sum(case((Appointment.has_reception.is_(True), 1), else_=0)).label(
                    "appointments_completed"
                ),
                func.max(Appointment.updated_at).label("appointments_as_of"),
            )
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.doctor_id.is_not(None),
                Appointment.status != "deleted",
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
                    case((RevenueFact.recognition_type == "doctor_payment", RevenueFact.amount), else_=0)
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
        totals = [
            DoctorTotals(
                doctor_id=row[0],
                full_name=row[1],
                specialty=row[2],
                appointments_total=int(row[3]),
                appointments_completed=int(row[4]),
                revenue_accrual=Decimal(row[5]),
                revenue_payment=Decimal(row[6]),
                average_rating=Decimal(row[7]) if row[7] is not None else None,
                data_as_of=max(
                    [value for value in (row[8],) if value is not None],
                    default=None,
                ),
            )
            for row in rows
        ]
        official_repository = OfficialReportsRepository(self.session)
        payment_metrics, payment_as_of, payment_coverage = await official_repository.exact_dimension_metrics(
            tenant_id,
            date_from,
            date_to,
            "doctor_revenue_payment",
            "doctor",
            branch_ids,
        )
        accrual_metrics, accrual_as_of, accrual_coverage = await official_repository.exact_dimension_metrics(
            tenant_id,
            date_from,
            date_to,
            "doctor_revenue_accrual",
            "doctor",
            branch_ids,
        )
        by_name: dict[str, list[int]] = {}
        for index, item in enumerate(totals):
            by_name.setdefault(self._normalize_name(item.full_name), []).append(index)

        def merge_official_metric(
            metric: object, *, field_name: str, metric_as_of: datetime | None
        ) -> None:
            dimension_label = str(getattr(metric, "dimension_label"))
            matches = by_name.get(self._normalize_name(dimension_label), [])
            metric_value = Decimal(getattr(metric, "value"))
            if len(matches) == 1:
                index = matches[0]
                current = totals[index]
                timestamps = [
                    value for value in (current.data_as_of, metric_as_of) if value
                ]
                totals[index] = replace(
                    current,
                    **{
                        field_name: metric_value,
                        "data_as_of": max(timestamps) if timestamps else None,
                    },
                )
                return

            # A finance report can contain a doctor who is no longer present
            # in the current employee roster. Preserve that real row rather
            # than dropping money merely because the directory changed.
            item = DoctorTotals(
                doctor_id=uuid5(
                    NAMESPACE_URL,
                    f"revora:1c-doctor:{tenant_id}:{getattr(metric, 'dimension_key')}",
                ),
                full_name=dimension_label,
                specialty=None,
                appointments_total=0,
                appointments_completed=0,
                revenue_accrual=metric_value if field_name == "revenue_accrual" else Decimal("0"),
                revenue_payment=metric_value if field_name == "revenue_payment" else Decimal("0"),
                average_rating=None,
                data_as_of=metric_as_of,
            )
            totals.append(item)
            by_name.setdefault(self._normalize_name(item.full_name), []).append(len(totals) - 1)

        for metric in payment_metrics:
            merge_official_metric(
                metric, field_name="revenue_payment", metric_as_of=payment_as_of
            )
        for metric in accrual_metrics:
            merge_official_metric(
                metric, field_name="revenue_accrual", metric_as_of=accrual_as_of
            )
        coverage = payment_coverage
        if not payment_metrics and accrual_metrics:
            coverage = accrual_coverage
        return sorted(
            totals,
            key=lambda item: (-item.revenue_payment, item.full_name.casefold()),
        ), coverage

    # Pairs of (clinic metric, doctor breakdown) that are meant to describe
    # the same money. The paid pair is knowingly cross-report -- see
    # REPORT_TYPE_BY_METRIC: revenue_payment comes from cash_receipts while
    # doctor_revenue_payment comes from doctor_revenue. reconcile_dimension
    # detects and names that rather than silently comparing them.
    RECONCILED_PAIRS = (
        ("revenue_accrual", "doctor_revenue_accrual"),
        ("revenue_payment", "doctor_revenue_payment"),
    )

    async def revenue_reconciliation(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_ids: list[UUID] | None,
    ) -> list[DimensionReconciliation]:
        """Check both doctor revenue breakdowns against their clinic totals.

        Read-only and never adjusts a figure: the caller is told what the
        official total is, what the breakdown sums to, how much of it has no
        doctor, and what is left unexplained.
        """
        official = OfficialReportsRepository(self.session)
        clinic_values, _clinic_as_of, clinic_coverage = await official.exact_values(
            tenant_id,
            date_from,
            date_to,
            {code for code, _ in self.RECONCILED_PAIRS},
            branch_ids,
        )

        results: list[DimensionReconciliation] = []
        for clinic_code, dimension_code in self.RECONCILED_PAIRS:
            rows, _as_of, dimension_coverage = await official.exact_dimension_metrics(
                tenant_id, date_from, date_to, dimension_code, "doctor", branch_ids
            )
            results.append(
                reconcile_dimension(
                    metric_code=dimension_code,
                    clinic_metric_code=clinic_code,
                    dimension_type="doctor",
                    clinic_total=clinic_values.get(clinic_code),
                    rows=rows,
                    clinic_coverage=clinic_coverage.get(clinic_code),
                    dimension_coverage=dimension_coverage,
                )
            )
        return results

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _end(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)

    @staticmethod
    def _normalize_name(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).casefold()
        return re.sub(r"[^a-zа-я0-9]+", "", normalized)
