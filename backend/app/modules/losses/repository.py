from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.finance.models import RevenueFact
from app.modules.losses.models import LossOpportunity
from app.modules.reports.repository import OfficialReportsRepository
from app.modules.sales.models import Appointment, Call, Lead, Patient
from app.modules.sales.repository import reconcile_lost_leads
from app.modules.whatsapp.models import WhatsAppConversation, WhatsAppMessage

ZERO = Decimal("0")


def _bounded_rate(
    numerator: Decimal | int,
    denominator: Decimal | int,
    *,
    default: Decimal,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    """Return a stable observed funnel rate without trusting tiny samples."""
    denominator_value = Decimal(denominator)
    if denominator_value < Decimal("20"):
        return default
    observed = Decimal(numerator) / denominator_value
    return min(maximum, max(minimum, observed))


def expected_contact_value(
    *,
    average_visit: Decimal,
    leads_total: int,
    leads_won: int,
    appointments_total: int,
    appointments_completed: int,
    revenue_accrual: Decimal,
    revenue_payment: Decimal,
) -> tuple[Decimal, dict[str, float]]:
    """Probability-weight one inbound contact instead of calling its full LTV lost."""
    booking_rate = _bounded_rate(
        leads_won,
        leads_total,
        default=Decimal("0.35"),
        minimum=Decimal("0.10"),
        maximum=Decimal("0.80"),
    )
    show_rate = _bounded_rate(
        appointments_completed,
        appointments_total,
        default=Decimal("0.75"),
        minimum=Decimal("0.30"),
        maximum=Decimal("0.98"),
    )
    collection_rate = (
        min(Decimal("1"), max(Decimal("0.30"), revenue_payment / revenue_accrual))
        if revenue_accrual > ZERO
        else Decimal("0.85")
    )
    amount = average_visit * booking_rate * show_rate * collection_rate
    return amount.quantize(Decimal("0.01")), {
        "booking_rate": float(booking_rate),
        "show_rate": float(show_rate),
        "collection_rate": float(collection_rate),
    }


@dataclass(frozen=True)
class LossCandidate:
    fingerprint: str
    branch_id: UUID | None
    loss_type: str
    severity: str
    title: str
    description: str
    recommended_action: str
    entity_type: str | None
    entity_id: UUID | None
    estimated_amount: Decimal
    confidence: Decimal
    evidence: dict[str, object]
    assigned_user_id: UUID | None = None


@dataclass(frozen=True)
class LossTotals:
    estimated_total: Decimal
    recovered_total: Decimal
    open_count: int
    in_progress_count: int
    recovered_count: int
    critical_count: int
    total_count: int
    stage_counts: dict[str, int]
    stage_amounts: dict[str, Decimal]


class LossRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def detect(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> list[LossCandidate]:
        # See sales/repository.py::reconcile_lost_leads -- this is the other
        # real reader of Lead.status == "lost" (lost_leads_query below), and
        # without this call it would always see zero rows: nothing else on
        # this code path ever persists that status.
        await reconcile_lost_leads(self.session, tenant_id)
        start = self._start(date_from)
        end = self._end(date_to)

        completed_query = select(func.count(Appointment.id)).where(
            Appointment.tenant_id == tenant_id,
            Appointment.status == "completed",
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
        )
        accrual_query = select(func.coalesce(func.sum(RevenueFact.amount), 0)).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.recognition_type == "accrual",
            RevenueFact.occurred_at >= start,
            RevenueFact.occurred_at < end,
        )
        if branch_id:
            completed_query = completed_query.where(Appointment.branch_id == branch_id)
            accrual_query = accrual_query.where(RevenueFact.branch_id == branch_id)
        completed = int((await self.session.scalar(completed_query)) or 0)
        accrual = Decimal((await self.session.scalar(accrual_query)) or 0)
        official_values, _, _ = await OfficialReportsRepository(self.session).exact_values(
            tenant_id,
            date_from,
            date_to,
            {
                "appointments_total",
                "appointments_completed",
                "revenue_accrual",
                "revenue_payment",
            },
            [branch_id] if branch_id else None,
        )
        # The production 1C extension sends audited report totals even when
        # canonical per-patient revenue rows are unavailable. Use that same
        # source as the dashboards so the loss map never values hundreds of
        # real cancellations at zero merely because the detailed fallback is
        # incomplete.
        completed = int(official_values.get("appointments_completed", completed))
        accrual = official_values.get("revenue_accrual", accrual)
        average_visit = accrual / completed if completed else ZERO

        appointment_total_query = select(func.count(Appointment.id)).where(
            Appointment.tenant_id == tenant_id,
            Appointment.status != "deleted",
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
        )
        lead_funnel_query = select(
            func.count(Lead.id),
            func.sum(case((Lead.status.in_(["won", "converted"]), 1), else_=0)),
        ).where(
            Lead.tenant_id == tenant_id,
            Lead.created_at >= start,
            Lead.created_at < end,
        )
        payment_query = select(func.coalesce(func.sum(RevenueFact.amount), 0)).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.recognition_type == "payment",
            RevenueFact.occurred_at >= start,
            RevenueFact.occurred_at < end,
        )
        if branch_id:
            appointment_total_query = appointment_total_query.where(
                Appointment.branch_id == branch_id
            )
            lead_funnel_query = lead_funnel_query.where(Lead.branch_id == branch_id)
            payment_query = payment_query.where(RevenueFact.branch_id == branch_id)
        if "appointments_total" in official_values:
            appointment_total = int(official_values["appointments_total"])
        else:
            appointment_total = int(
                (await self.session.scalar(appointment_total_query)) or 0
            )
        lead_total, won_count = (await self.session.execute(lead_funnel_query)).one()
        lead_total = int(lead_total or 0)
        won_count = int(won_count or 0)
        if "revenue_payment" in official_values:
            payments = official_values["revenue_payment"]
        else:
            payments = Decimal((await self.session.scalar(payment_query)) or 0)
        contact_value, contact_rates = expected_contact_value(
            average_visit=average_visit,
            leads_total=lead_total,
            leads_won=won_count,
            appointments_total=appointment_total,
            appointments_completed=completed,
            revenue_accrual=accrual,
            revenue_payment=payments,
        )

        # Revenue and appointment dimensions are distinct SQL columns; build
        # the maps explicitly so the grouping always references the
        # table being queried.
        async def dimension_averages(appointment_dimension, revenue_dimension):
            counts = select(appointment_dimension, func.count(Appointment.id)).where(
                Appointment.tenant_id == tenant_id,
                Appointment.status == "completed",
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
                appointment_dimension.is_not(None),
            )
            payments = select(revenue_dimension, func.coalesce(func.sum(RevenueFact.amount), 0)).where(
                RevenueFact.tenant_id == tenant_id,
                RevenueFact.recognition_type == "payment",
                RevenueFact.occurred_at >= start,
                RevenueFact.occurred_at < end,
                revenue_dimension.is_not(None),
            )
            if branch_id:
                counts = counts.where(Appointment.branch_id == branch_id)
                payments = payments.where(RevenueFact.branch_id == branch_id)
            count_map = dict((await self.session.execute(counts.group_by(appointment_dimension))).all())
            payment_map = dict((await self.session.execute(payments.group_by(revenue_dimension))).all())
            return {
                key: Decimal(payment_map.get(key) or 0) / count
                for key, count in count_map.items()
                if count and Decimal(payment_map.get(key) or 0) > ZERO
            }

        patient_averages = await dimension_averages(
            Appointment.patient_id, RevenueFact.patient_id
        )
        doctor_averages = await dimension_averages(Appointment.doctor_id, RevenueFact.doctor_id)
        direction_averages = await dimension_averages(
            Appointment.direction_id, RevenueFact.direction_id
        )

        later_appointment = aliased(Appointment)
        appointment_query = select(
            Appointment.id,
            Appointment.branch_id,
            Appointment.status,
            Appointment.starts_at,
            Appointment.patient_id,
            Appointment.doctor_id,
            Appointment.direction_id,
        ).where(
            Appointment.tenant_id == tenant_id,
            Appointment.status.in_(["no_show", "cancelled"]),
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
            ~exists(
                select(later_appointment.id).where(
                    later_appointment.tenant_id == Appointment.tenant_id,
                    later_appointment.patient_id == Appointment.patient_id,
                    Appointment.patient_id.is_not(None),
                    later_appointment.id != Appointment.id,
                    later_appointment.starts_at > Appointment.starts_at,
                    later_appointment.status.in_(["scheduled", "completed", "transferred"]),
                )
            ),
        )
        if branch_id:
            appointment_query = appointment_query.where(Appointment.branch_id == branch_id)
        appointments = (await self.session.execute(appointment_query)).all()

        candidates: list[LossCandidate] = []
        for row in appointments:
            is_no_show = row.status == "no_show"
            if row.patient_id in patient_averages:
                unit_value, basis, basis_confidence = (
                    patient_averages[row.patient_id], "patient_payment_average", Decimal("0.9000")
                )
            elif row.direction_id in direction_averages:
                unit_value, basis, basis_confidence = (
                    direction_averages[row.direction_id], "direction_payment_average", Decimal("0.8000")
                )
            elif row.doctor_id in doctor_averages:
                unit_value, basis, basis_confidence = (
                    doctor_averages[row.doctor_id], "doctor_payment_average", Decimal("0.7000")
                )
            else:
                unit_value, basis, basis_confidence = (
                    average_visit, "clinic_accrual_average", Decimal("0.5000")
                )
            confidence = basis_confidence if is_no_show else basis_confidence * Decimal("0.60")
            estimate = unit_value if is_no_show else unit_value * Decimal("0.60")
            if estimate <= ZERO:
                continue
            candidates.append(
                LossCandidate(
                    fingerprint=self._fingerprint(f"{row.status}:{row.id}"),
                    branch_id=row.branch_id,
                    loss_type=row.status,
                    severity="critical" if is_no_show else "warning",
                    title="Неявка пациента" if is_no_show else "Отменённый приём",
                    description=(
                        "Зарезервированное время врача осталось без завершённого приёма."
                        if is_no_show
                        else "Запись была отменена и требует проверки повторного бронирования."
                    ),
                    recommended_action=(
                        "Связаться с пациентом и предложить два конкретных свободных времени."
                        if is_no_show
                        else "Проверить, создана ли новая запись; при отсутствии — вернуть пациента в работу."
                    ),
                    entity_type="appointment",
                    entity_id=row.id,
                    estimated_amount=estimate.quantize(Decimal("0.01")),
                    confidence=confidence,
                    evidence={
                        "appointment_status": row.status,
                        "starts_at": row.starts_at.isoformat(),
                        "doctor_linked": row.doctor_id is not None,
                        "direction_linked": row.direction_id is not None,
                        "estimation_basis": basis,
                        "unit_value": float(unit_value),
                        "funnel_stage": "visit",
                        "reason_code": row.status,
                        "proof": "no_later_active_appointment",
                    },
                )
            )

        lost_leads_query = select(Lead.id, Lead.branch_id, Lead.source, Lead.created_at).where(
            Lead.tenant_id == tenant_id,
            Lead.status == "lost",
            Lead.patient_id.is_(None),
            Lead.created_at >= start,
            Lead.created_at < end,
        )
        if branch_id:
            lost_leads_query = lost_leads_query.where(Lead.branch_id == branch_id)
        for row in (await self.session.execute(lost_leads_query)).all():
            estimate = contact_value
            if estimate <= ZERO:
                continue
            candidates.append(
                LossCandidate(
                    fingerprint=self._fingerprint(f"lost_lead:{row.id}"),
                    branch_id=row.branch_id,
                    loss_type="lost_lead",
                    severity="warning",
                    title="Обращение не дошло до записи",
                    description="После последнего контакта прошло 14 дней: пациента и записи в 1С нет.",
                    recommended_action="Проверить причину потери и выполнить один контрольный контакт.",
                    entity_type="lead",
                    entity_id=row.id,
                    estimated_amount=estimate.quantize(Decimal("0.01")),
                    confidence=Decimal("0.4500"),
                    evidence={
                        "source": row.source,
                        "created_at": row.created_at.isoformat(),
                        "estimation_basis": "probability_weighted_funnel",
                        "unit_value": float(average_visit),
                        "funnel_stage": "booking",
                        "reason_code": "no_patient_or_appointment_after_14_days",
                        "proof": "lead_stale_and_patient_unlinked",
                        **contact_rates,
                    },
                )
            )

        callback = aliased(Call)
        callback_patient = aliased(Patient)
        callback_appointment = aliased(Appointment)
        missed_calls = select(
            Call.id,
            Call.branch_id,
            Call.started_at,
            Call.duration_seconds,
            Lead.assigned_user_id,
        ).outerjoin(
            Lead,
            (Lead.tenant_id == Call.tenant_id) & (Lead.id == Call.lead_id),
        ).where(
            Call.tenant_id == tenant_id,
            Call.phone_hash.is_not(None),
            func.lower(Call.direction).in_(["in", "incoming", "inbound", "входящий"]),
            func.coalesce(Call.duration_seconds, 0) <= 5,
            Call.started_at >= start,
            Call.started_at < end,
            Call.started_at < datetime.now(UTC) - timedelta(minutes=30),
            ~exists(
                select(callback.id).where(
                    callback.tenant_id == Call.tenant_id,
                    callback.phone_hash == Call.phone_hash,
                    callback.id != Call.id,
                    func.lower(callback.direction).in_(
                        ["out", "outgoing", "outbound", "исходящий"]
                    ),
                    callback.started_at > Call.started_at,
                )
            ),
            ~exists(
                select(callback_appointment.id)
                .join(
                    callback_patient,
                    (callback_patient.tenant_id == callback_appointment.tenant_id)
                    & (callback_patient.id == callback_appointment.patient_id),
                )
                .where(
                    callback_appointment.tenant_id == Call.tenant_id,
                    callback_patient.phone_hash == Call.phone_hash,
                    callback_appointment.starts_at >= Call.started_at,
                    callback_appointment.status.in_(["scheduled", "completed", "transferred"]),
                )
            ),
        )
        if branch_id:
            missed_calls = missed_calls.where(Call.branch_id == branch_id)
        for row in (await self.session.execute(missed_calls)).all():
            estimate = contact_value
            if estimate <= ZERO:
                continue
            candidates.append(
                LossCandidate(
                    fingerprint=self._fingerprint(f"missed_call:{row.id}"),
                    branch_id=row.branch_id,
                    loss_type="missed_call",
                    severity="critical",
                    title="Пропущенный входящий звонок",
                    description="Входящий звонок не перешёл в разговор с клиникой.",
                    recommended_action="Перезвонить и зафиксировать результат обращения.",
                    entity_type="call",
                    entity_id=row.id,
                    estimated_amount=estimate,
                    confidence=Decimal("0.5000"),
                    evidence={
                        "started_at": row.started_at.isoformat(),
                        "duration_seconds": row.duration_seconds or 0,
                        "response_sla_minutes": 30,
                        "estimation_basis": "probability_weighted_funnel",
                        "unit_value": float(average_visit),
                        "funnel_stage": "response",
                        "reason_code": "missed_without_callback",
                        "proof": "no_later_outbound_call_or_appointment",
                        **contact_rates,
                    },
                    assigned_user_id=row.assigned_user_id,
                )
            )

        inbound = aliased(WhatsAppMessage)
        later_outbound = aliased(WhatsAppMessage)
        booked_patient = aliased(Patient)
        booked_appointment = aliased(Appointment)
        unanswered = select(
            inbound.id,
            inbound.conversation_id,
            inbound.provider_timestamp,
            WhatsAppConversation.assigned_user_id,
        ).join(
            WhatsAppConversation,
            (WhatsAppConversation.tenant_id == inbound.tenant_id)
            & (WhatsAppConversation.id == inbound.conversation_id),
        ).where(
            inbound.tenant_id == tenant_id,
            inbound.direction == "in",
            inbound.provider_timestamp >= start,
            inbound.provider_timestamp < end,
            inbound.provider_timestamp < datetime.now(UTC) - timedelta(minutes=30),
            ~exists(
                select(later_outbound.id).where(
                    later_outbound.tenant_id == inbound.tenant_id,
                    later_outbound.conversation_id == inbound.conversation_id,
                    later_outbound.direction == "out",
                    later_outbound.provider_timestamp > inbound.provider_timestamp,
                )
            ),
            ~exists(
                select(booked_appointment.id)
                .join(
                    booked_patient,
                    (booked_patient.tenant_id == booked_appointment.tenant_id)
                    & (booked_patient.id == booked_appointment.patient_id),
                )
                .where(
                    booked_appointment.tenant_id == inbound.tenant_id,
                    booked_patient.phone_hash == WhatsAppConversation.contact_hash,
                    booked_appointment.starts_at >= inbound.provider_timestamp,
                    booked_appointment.status.in_(["scheduled", "completed", "transferred"]),
                )
            ),
        ).distinct(inbound.conversation_id).order_by(
            inbound.conversation_id, inbound.provider_timestamp.desc()
        )
        if branch_id:
            # WhatsApp conversations do not carry a proven branch. Never
            # guess one or expose an unscoped item in a branch-only view.
            unanswered = unanswered.where(False)
        for row in (await self.session.execute(unanswered)).all():
            estimate = contact_value
            if estimate <= ZERO:
                continue
            candidates.append(
                LossCandidate(
                    fingerprint=self._fingerprint(
                        f"whatsapp_unanswered:{row.conversation_id}"
                    ),
                    branch_id=None,
                    loss_type="whatsapp_unanswered",
                    severity="warning",
                    title="WhatsApp без ответа",
                    description="Сообщение пациента осталось без исходящего ответа более 30 минут.",
                    recommended_action="Ответить пациенту и предложить запись.",
                    entity_type="whatsapp_message",
                    entity_id=row.id,
                    estimated_amount=estimate,
                    confidence=Decimal("0.4000"),
                    evidence={
                        "occurred_at": row.provider_timestamp.isoformat(),
                        "response_sla_minutes": 30,
                        "estimation_basis": "probability_weighted_funnel",
                        "unit_value": float(average_visit),
                        "funnel_stage": "response",
                        "reason_code": "whatsapp_unanswered_after_sla",
                        "proof": "no_reply_and_no_appointment",
                        **contact_rates,
                    },
                    assigned_user_id=row.assigned_user_id,
                )
            )

        # Accrual minus cash received is a receivables/finance signal, not
        # proof that a client was lost. It belongs to P&L and cash-flow views,
        # therefore the client loss map intentionally excludes it.
        return candidates

    async def upsert(
        self,
        tenant_id: UUID,
        candidates: list[LossCandidate],
        date_from: date,
        date_to: date,
    ) -> int:
        now = datetime.now(UTC)
        values = [
            {
                "tenant_id": tenant_id,
                "branch_id": item.branch_id,
                "assigned_user_id": item.assigned_user_id,
                "fingerprint": item.fingerprint,
                "loss_type": item.loss_type,
                "severity": item.severity,
                "status": "open",
                "title": item.title,
                "description": item.description,
                "recommended_action": item.recommended_action,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "estimated_amount": item.estimated_amount,
                "recovered_amount": ZERO,
                "currency": "KZT",
                "confidence": item.confidence,
                "evidence": item.evidence,
                "period_start": date_from,
                "period_end": date_to,
                "detected_at": now,
                "last_detected_at": now,
            }
            for item in candidates
        ]
        # A three-month clinic range can yield thousands of cancellations.
        # Sending one INSERT per opportunity made the HTTP refresh take minutes
        # on Render. Keep batches below PostgreSQL's parameter limit while
        # reducing the operation to a handful of round trips.
        for offset in range(0, len(values), 500):
            statement = insert(LossOpportunity).values(values[offset : offset + 500])
            statement = statement.on_conflict_do_update(
                index_elements=["tenant_id", "fingerprint"],
                set_={
                    "branch_id": statement.excluded.branch_id,
                    "assigned_user_id": func.coalesce(
                        LossOpportunity.assigned_user_id, statement.excluded.assigned_user_id
                    ),
                    "severity": statement.excluded.severity,
                    "title": statement.excluded.title,
                    "description": statement.excluded.description,
                    "recommended_action": statement.excluded.recommended_action,
                    "estimated_amount": statement.excluded.estimated_amount,
                    "confidence": statement.excluded.confidence,
                    "evidence": statement.excluded.evidence,
                    "period_start": statement.excluded.period_start,
                    "period_end": statement.excluded.period_end,
                    "last_detected_at": statement.excluded.last_detected_at,
                },
            )
            await self.session.execute(statement)
        return len(candidates)

    async def dismiss_absent(
        self,
        tenant_id: UUID,
        candidates: list[LossCandidate],
        date_from: date,
        date_to: date,
    ) -> int:
        """Close false positives that no longer satisfy loss evidence.

        A recalculation may discover that an appointment was rescheduled, a
        missed call received a callback, or WhatsApp received a reply. Only
        untouched open cards are closed automatically; assigned work remains
        in progress until a person or a confirmed payment resolves it.
        """
        fingerprints = [candidate.fingerprint for candidate in candidates]
        statement = update(LossOpportunity).where(
            LossOpportunity.tenant_id == tenant_id,
            LossOpportunity.period_start == date_from,
            LossOpportunity.period_end == date_to,
            LossOpportunity.status == "open",
        )
        if fingerprints:
            statement = statement.where(~LossOpportunity.fingerprint.in_(fingerprints))
        result = await self.session.execute(
            statement.values(status="dismissed", resolved_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    async def list(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> list[LossOpportunity]:
        statement = (
            select(LossOpportunity)
            .where(
                LossOpportunity.tenant_id == tenant_id,
                LossOpportunity.period_start == date_from,
                LossOpportunity.period_end == date_to,
            )
            .order_by(
                case((LossOpportunity.status == "open", 0), else_=1),
                LossOpportunity.estimated_amount.desc(),
            )
            .limit(500)
        )
        if branch_id:
            statement = statement.where(LossOpportunity.branch_id == branch_id)
        return list((await self.session.scalars(statement)).all())

    async def summary(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> LossTotals:
        """Aggregate the whole map, independently from the 500-card UI page."""
        active_amount = case(
            (
                ~LossOpportunity.status.in_(["recovered", "dismissed"]),
                LossOpportunity.estimated_amount,
            ),
            else_=ZERO,
        )
        statement = select(
            func.coalesce(func.sum(active_amount), ZERO),
            func.coalesce(func.sum(LossOpportunity.recovered_amount), ZERO),
            func.sum(case((LossOpportunity.status == "open", 1), else_=0)),
            func.sum(case((LossOpportunity.status == "in_progress", 1), else_=0)),
            func.sum(case((LossOpportunity.status == "recovered", 1), else_=0)),
            func.sum(
                case(
                    (
                        (LossOpportunity.severity == "critical")
                        & (LossOpportunity.status == "open"),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.count(LossOpportunity.id),
        ).where(
            LossOpportunity.tenant_id == tenant_id,
            LossOpportunity.period_start == date_from,
            LossOpportunity.period_end == date_to,
        )
        if branch_id:
            statement = statement.where(LossOpportunity.branch_id == branch_id)
        row = (await self.session.execute(statement)).one()
        stage = LossOpportunity.evidence["funnel_stage"].astext
        stage_statement = (
            select(
                stage,
                func.count(LossOpportunity.id),
                func.coalesce(func.sum(LossOpportunity.estimated_amount), ZERO),
            )
            .where(
                LossOpportunity.tenant_id == tenant_id,
                LossOpportunity.period_start == date_from,
                LossOpportunity.period_end == date_to,
                ~LossOpportunity.status.in_(["recovered", "dismissed"]),
            )
            .group_by(stage)
        )
        if branch_id:
            stage_statement = stage_statement.where(
                LossOpportunity.branch_id == branch_id
            )
        stage_rows = (await self.session.execute(stage_statement)).all()
        return LossTotals(
            estimated_total=Decimal(row[0] or 0),
            recovered_total=Decimal(row[1] or 0),
            open_count=int(row[2] or 0),
            in_progress_count=int(row[3] or 0),
            recovered_count=int(row[4] or 0),
            critical_count=int(row[5] or 0),
            total_count=int(row[6] or 0),
            stage_counts={str(item[0]): int(item[1]) for item in stage_rows if item[0]},
            stage_amounts={
                str(item[0]): Decimal(item[2] or 0) for item in stage_rows if item[0]
            },
        )

    async def reconcile_recoveries(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> int:
        """Confirm recovery only from a later real payment linked to the same patient.

        A Telegram completion or a manual status change is not financial proof. This
        reconciliation is safe to repeat and never exposes patient data in evidence.
        """
        opportunities = select(LossOpportunity).where(
            LossOpportunity.tenant_id == tenant_id,
            LossOpportunity.period_start == date_from,
            LossOpportunity.period_end == date_to,
            LossOpportunity.status.in_(["open", "in_progress"]),
            LossOpportunity.entity_type.in_(["appointment", "lead", "call", "whatsapp_message"]),
        )
        if branch_id:
            opportunities = opportunities.where(LossOpportunity.branch_id == branch_id)
        items = list((await self.session.scalars(opportunities)).all())
        if not items:
            return 0

        event_by_opportunity: dict[UUID, tuple[UUID | None, datetime | None]] = {}

        appointment_ids = [item.entity_id for item in items if item.entity_type == "appointment"]
        if appointment_ids:
            rows = await self.session.execute(
                select(Appointment.id, Appointment.patient_id, Appointment.starts_at).where(
                    Appointment.tenant_id == tenant_id,
                    Appointment.id.in_(appointment_ids),
                )
            )
            entity_map = {row.id: (row.patient_id, row.starts_at) for row in rows.all()}
            event_by_opportunity.update(
                (item.id, entity_map.get(item.entity_id, (None, None)))
                for item in items
                if item.entity_type == "appointment"
            )

        lead_ids = [item.entity_id for item in items if item.entity_type == "lead"]
        if lead_ids:
            rows = await self.session.execute(
                select(Lead.id, Lead.patient_id, Lead.created_at).where(
                    Lead.tenant_id == tenant_id, Lead.id.in_(lead_ids)
                )
            )
            entity_map = {row.id: (row.patient_id, row.created_at) for row in rows.all()}
            event_by_opportunity.update(
                (item.id, entity_map.get(item.entity_id, (None, None)))
                for item in items
                if item.entity_type == "lead"
            )

        call_ids = [item.entity_id for item in items if item.entity_type == "call"]
        if call_ids:
            rows = await self.session.execute(
                select(Call.id, Lead.patient_id, Call.started_at)
                .outerjoin(
                    Lead,
                    (Lead.tenant_id == Call.tenant_id) & (Lead.id == Call.lead_id),
                )
                .where(Call.tenant_id == tenant_id, Call.id.in_(call_ids))
            )
            entity_map = {row.id: (row.patient_id, row.started_at) for row in rows.all()}
            event_by_opportunity.update(
                (item.id, entity_map.get(item.entity_id, (None, None)))
                for item in items
                if item.entity_type == "call"
            )

        message_ids = [
            item.entity_id for item in items if item.entity_type == "whatsapp_message"
        ]
        if message_ids:
            rows = (
                await self.session.execute(
                    select(
                        WhatsAppMessage.id,
                        WhatsAppMessage.provider_timestamp,
                        WhatsAppMessage.created_at,
                        WhatsAppConversation.contact_hash,
                    )
                    .join(
                        WhatsAppConversation,
                        (WhatsAppConversation.tenant_id == WhatsAppMessage.tenant_id)
                        & (WhatsAppConversation.id == WhatsAppMessage.conversation_id),
                    )
                    .where(
                        WhatsAppMessage.tenant_id == tenant_id,
                        WhatsAppMessage.id.in_(message_ids),
                    )
                )
            ).all()
            hashes = {row.contact_hash for row in rows}
            lead_rows = await self.session.execute(
                select(Lead.external_id, Lead.patient_id).where(
                    Lead.tenant_id == tenant_id, Lead.external_id.in_(hashes)
                )
            )
            patient_by_hash = {row.external_id: row.patient_id for row in lead_rows.all()}
            entity_map = {
                row.id: (
                    patient_by_hash.get(row.contact_hash),
                    row.provider_timestamp or row.created_at,
                )
                for row in rows
            }
            event_by_opportunity.update(
                (item.id, entity_map.get(item.entity_id, (None, None)))
                for item in items
                if item.entity_type == "whatsapp_message"
            )

        patient_ids = {
            patient_id
            for patient_id, event_at in event_by_opportunity.values()
            if patient_id is not None and event_at is not None
        }
        payments_by_patient: dict[UUID, list[tuple[datetime, Decimal]]] = {}
        if patient_ids:
            payment_rows = await self.session.execute(
                select(
                    RevenueFact.patient_id,
                    RevenueFact.occurred_at,
                    RevenueFact.amount,
                ).where(
                    RevenueFact.tenant_id == tenant_id,
                    RevenueFact.patient_id.in_(patient_ids),
                    RevenueFact.recognition_type == "payment",
                )
            )
            for row in payment_rows.all():
                payments_by_patient.setdefault(row.patient_id, []).append(
                    (row.occurred_at, Decimal(row.amount))
                )

        recovered = 0
        for item in items:
            patient_id, event_at = event_by_opportunity.get(item.id, (None, None))
            if patient_id is None or event_at is None:
                continue
            payment = sum(
                (
                    amount
                    for occurred_at, amount in payments_by_patient.get(patient_id, [])
                    if occurred_at >= event_at
                ),
                ZERO,
            )
            if payment <= ZERO:
                continue
            item.status = "recovered"
            item.recovered_amount = payment.quantize(Decimal("0.01"))
            item.resolved_at = datetime.now(UTC)
            item.evidence = {
                **item.evidence,
                "recovery_basis": "later_patient_payment",
                "recovery_confirmed_at": item.resolved_at.isoformat(),
            }
            recovered += 1
        return recovered

    async def get(self, tenant_id: UUID, opportunity_id: UUID) -> LossOpportunity | None:
        return await self.session.scalar(
            select(LossOpportunity).where(
                LossOpportunity.tenant_id == tenant_id,
                LossOpportunity.id == opportunity_id,
            )
        )

    @staticmethod
    def _fingerprint(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=UTC)

    @staticmethod
    def _end(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=UTC)
