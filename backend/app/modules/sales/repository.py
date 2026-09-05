"""Aggregate sales and appointment facts."""

# "Давно не посещавшие" threshold: a patient still marked active in 1C who
# has not visited in this many days counts as inactive/at-risk.
INACTIVE_PATIENT_DAYS = 60

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import RevenueFact
from app.modules.reports.repository import CoverageInfo, OfficialReportsRepository
from app.modules.sales.models import Appointment, Lead, Patient, TreatmentPlan
from app.shared.timezone import clinic_day_end_exclusive, clinic_day_start


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
    patients_total: int
    patients_primary: int
    patients_repeat: int
    paid_revenue: Decimal
    data_as_of: datetime | None
    coverage: dict[str, CoverageInfo] = field(default_factory=dict)
    # Task 2: transfers, treatment-plan funnel, and "давно не посещавшие"
    # inactive patients -- appointments_transferred/treatment_plan_* prefer
    # the official 1C figure and fall back to the local canonical count
    # (paid stays None, never a fabricated 0, when 1C hasn't sent it: there
    # is no local ledger for treatment-plan payments to fall back to).
    appointments_transferred: int = 0
    treatment_plan_created: int = 0
    treatment_plan_accepted: int = 0
    treatment_plan_paid: Decimal | None = None
    patients_inactive: int = 0


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
            func.sum(case((Appointment.has_reception.is_(True), 1), else_=0)),
            func.sum(case((Appointment.status == "cancelled", 1), else_=0)),
            func.sum(case((Appointment.status == "no_show", 1), else_=0)),
            func.count(
                func.distinct(
                    case((Appointment.has_reception.is_(True), Appointment.patient_id))
                )
            ),
            func.count(
                func.distinct(
                    case(
                        (
                            (Appointment.has_reception.is_(True))
                            & (Appointment.is_primary.is_(True)),
                            Appointment.patient_id,
                        )
                    )
                )
            ),
            func.max(Appointment.updated_at),
            # Task 2: rescheduled ("перенос") appointments -- see the BSL
            # extension's status normalisation. Local-only until 1C sends
            # appointments_transferred, at which point that value wins.
            func.sum(case((Appointment.status == "transferred", 1), else_=0)),
        ).where(
            Appointment.tenant_id == tenant_id,
            Appointment.status != "deleted",
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
        treatment_plan_created_statement = select(
            func.count(TreatmentPlan.id),
        ).where(
            TreatmentPlan.tenant_id == tenant_id,
            TreatmentPlan.created_at >= self._start(date_from),
            TreatmentPlan.created_at < self._end(date_to),
        )
        treatment_plan_accepted_statement = select(
            func.count(TreatmentPlan.id),
        ).where(
            TreatmentPlan.tenant_id == tenant_id,
            TreatmentPlan.accepted_at.is_not(None),
            TreatmentPlan.accepted_at >= self._start(date_from),
            TreatmentPlan.accepted_at < self._end(date_to),
        )
        if branch_ids is not None:
            # TreatmentPlan has no branch_id of its own -- scope through the
            # patient it belongs to, same as assigned_user_id scoping above.
            plan_patient_ids = select(Patient.id).where(
                Patient.tenant_id == tenant_id, Patient.branch_id.in_(branch_ids)
            )
            treatment_plan_created_statement = treatment_plan_created_statement.where(
                TreatmentPlan.patient_id.in_(plan_patient_ids)
            )
            treatment_plan_accepted_statement = treatment_plan_accepted_statement.where(
                TreatmentPlan.patient_id.in_(plan_patient_ids)
            )
        treatment_plan_created_row = (
            await self.session.execute(treatment_plan_created_statement)
        ).one()
        treatment_plan_accepted_row = (
            await self.session.execute(treatment_plan_accepted_statement)
        ).one()

        # "Давно не посещавшие" -- patients still marked active in 1C whose
        # last recorded visit is older than the threshold, as of date_to.
        # This is a point-in-time roster, not a date-range flow metric, so
        # it deliberately ignores date_from.
        inactivity_cutoff = self._start(date_to) - timedelta(days=INACTIVE_PATIENT_DAYS)
        inactive_patients_statement = select(func.count(Patient.id)).where(
            Patient.tenant_id == tenant_id,
            Patient.is_active.is_(True),
            Patient.last_visit_at.is_not(None),
            Patient.last_visit_at < inactivity_cutoff,
        )
        if branch_ids is not None:
            inactive_patients_statement = inactive_patients_statement.where(
                Patient.branch_id.in_(branch_ids)
            )
        inactive_patients_row = (
            await self.session.execute(inactive_patients_statement)
        ).one()

        official_values, official_as_of, official_coverage = await OfficialReportsRepository(
            self.session
        ).exact_values(
            tenant_id,
            date_from,
            date_to,
            {
                "appointments_total", "appointments_completed",
                "appointments_cancelled", "appointments_no_show",
                "patients_total", "patients_primary", "revenue_payment",
                "appointments_transferred", "treatment_plan_created",
                "treatment_plan_accepted", "treatment_plan_paid",
            },
            branch_ids,
        )
        timestamps = [
            value
            for value in (lead_row[4], appointment_row[6], revenue_row[1], official_as_of)
            if value
        ]
        patients_total = int(
            official_values.get("patients_total", appointment_row[4] or 0)
        )
        patients_primary = int(
            official_values.get("patients_primary", appointment_row[5] or 0)
        )
        return SalesTotals(
            leads_total=int(lead_row[0] or 0),
            leads_new=int(lead_row[1] or 0),
            leads_won=int(lead_row[2] or 0),
            leads_lost=int(lead_row[3] or 0),
            appointments_total=int(
                official_values.get("appointments_total", appointment_row[0] or 0)
            ),
            appointments_completed=int(
                official_values.get("appointments_completed", appointment_row[1] or 0)
            ),
            appointments_cancelled=int(
                official_values.get("appointments_cancelled", appointment_row[2] or 0)
            ),
            appointments_no_show=int(
                official_values.get("appointments_no_show", appointment_row[3] or 0)
            ),
            patients_total=patients_total,
            patients_primary=patients_primary,
            patients_repeat=max(0, patients_total - patients_primary),
            paid_revenue=official_values.get("revenue_payment", Decimal(revenue_row[0])),
            appointments_transferred=int(
                official_values.get("appointments_transferred", appointment_row[7] or 0)
            ),
            treatment_plan_created=int(
                official_values.get(
                    "treatment_plan_created", treatment_plan_created_row[0] or 0
                )
            ),
            treatment_plan_accepted=int(
                official_values.get(
                    "treatment_plan_accepted", treatment_plan_accepted_row[0] or 0
                )
            ),
            treatment_plan_paid=official_values.get("treatment_plan_paid"),
            patients_inactive=int(inactive_patients_row[0] or 0),
            data_as_of=max(timestamps) if timestamps else None,
            coverage=official_coverage,
        )

    @staticmethod
    def _start(value: date) -> datetime:
        return clinic_day_start(value)

    @staticmethod
    def _end(value: date) -> datetime:
        return clinic_day_end_exclusive(value)
