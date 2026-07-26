from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import RevenueFact
from app.modules.losses.models import LossOpportunity
from app.modules.sales.models import Appointment, Lead

ZERO = Decimal("0")


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
        average_visit = accrual / completed if completed else ZERO

        appointment_query = select(
            Appointment.id,
            Appointment.branch_id,
            Appointment.status,
            Appointment.starts_at,
            Appointment.doctor_id,
            Appointment.direction_id,
        ).where(
            Appointment.tenant_id == tenant_id,
            Appointment.status.in_(["no_show", "cancelled"]),
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
        )
        if branch_id:
            appointment_query = appointment_query.where(Appointment.branch_id == branch_id)
        appointments = (await self.session.execute(appointment_query)).all()

        candidates: list[LossCandidate] = []
        for row in appointments:
            is_no_show = row.status == "no_show"
            confidence = Decimal("0.9000") if is_no_show else Decimal("0.5500")
            estimate = average_visit if is_no_show else average_visit * Decimal("0.60")
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
                        "estimation_basis": "average_accrual_per_completed_visit",
                        "average_visit": float(average_visit),
                    },
                )
            )

        won_count_query = select(func.count(Lead.id)).where(
            Lead.tenant_id == tenant_id,
            Lead.status.in_(["won", "converted"]),
            Lead.created_at >= start,
            Lead.created_at < end,
        )
        payment_query = select(func.coalesce(func.sum(RevenueFact.amount), 0)).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.recognition_type == "payment",
            RevenueFact.occurred_at >= start,
            RevenueFact.occurred_at < end,
        )
        lost_leads_query = select(Lead.id, Lead.branch_id, Lead.source, Lead.created_at).where(
            Lead.tenant_id == tenant_id,
            Lead.status == "lost",
            Lead.created_at >= start,
            Lead.created_at < end,
        )
        if branch_id:
            won_count_query = won_count_query.where(Lead.branch_id == branch_id)
            payment_query = payment_query.where(RevenueFact.branch_id == branch_id)
            lost_leads_query = lost_leads_query.where(Lead.branch_id == branch_id)
        won_count = int((await self.session.scalar(won_count_query)) or 0)
        payments = Decimal((await self.session.scalar(payment_query)) or 0)
        value_per_won_lead = payments / won_count if won_count else average_visit
        for row in (await self.session.execute(lost_leads_query)).all():
            estimate = value_per_won_lead * Decimal("0.35")
            candidates.append(
                LossCandidate(
                    fingerprint=self._fingerprint(f"lost_lead:{row.id}"),
                    branch_id=row.branch_id,
                    loss_type="lost_lead",
                    severity="warning",
                    title="Потерянный лид",
                    description="Обращение закрыто как потерянное и не принесло оплату.",
                    recommended_action="Проверить причину потери и выполнить один контрольный контакт.",
                    entity_type="lead",
                    entity_id=row.id,
                    estimated_amount=estimate.quantize(Decimal("0.01")),
                    confidence=Decimal("0.4500"),
                    evidence={
                        "source": row.source,
                        "created_at": row.created_at.isoformat(),
                        "estimation_basis": "35_percent_of_payment_per_won_lead",
                        "value_per_won_lead": float(value_per_won_lead),
                    },
                )
            )

        revenue_by_branch = select(
            RevenueFact.branch_id,
            func.coalesce(
                func.sum(
                    case(
                        (RevenueFact.recognition_type == "accrual", RevenueFact.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (RevenueFact.recognition_type == "payment", RevenueFact.amount),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.occurred_at >= start,
            RevenueFact.occurred_at < end,
        )
        if branch_id:
            revenue_by_branch = revenue_by_branch.where(RevenueFact.branch_id == branch_id)
        revenue_by_branch = revenue_by_branch.group_by(RevenueFact.branch_id)
        for row in (await self.session.execute(revenue_by_branch)).all():
            gap = max(ZERO, Decimal(row[1]) - Decimal(row[2]))
            if gap <= ZERO:
                continue
            branch_key = str(row[0]) if row[0] else "all"
            candidates.append(
                LossCandidate(
                    fingerprint=self._fingerprint(
                        f"payment_gap:{branch_key}:{date_from}:{date_to}"
                    ),
                    branch_id=row[0],
                    loss_type="payment_gap",
                    severity="critical" if gap >= max(average_visit * 3, Decimal("1")) else "warning",
                    title="Разрыв между начислениями и оплатами",
                    description="Часть начисленной выручки ещё не подтверждена фактическими оплатами.",
                    recommended_action="Проверить задолженности, рассрочки, возвраты и несвязанные платежи.",
                    entity_type="period",
                    entity_id=None,
                    estimated_amount=gap.quantize(Decimal("0.01")),
                    confidence=Decimal("0.7000"),
                    evidence={
                        "accrual": float(Decimal(row[1])),
                        "payment": float(Decimal(row[2])),
                        "estimation_basis": "accrual_minus_payment",
                    },
                )
            )
        return candidates

    async def upsert(
        self,
        tenant_id: UUID,
        candidates: list[LossCandidate],
        date_from: date,
        date_to: date,
    ) -> int:
        now = datetime.now(UTC)
        for item in candidates:
            statement = insert(LossOpportunity).values(
                tenant_id=tenant_id,
                branch_id=item.branch_id,
                fingerprint=item.fingerprint,
                loss_type=item.loss_type,
                severity=item.severity,
                status="open",
                title=item.title,
                description=item.description,
                recommended_action=item.recommended_action,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                estimated_amount=item.estimated_amount,
                recovered_amount=ZERO,
                currency="KZT",
                confidence=item.confidence,
                evidence=item.evidence,
                period_start=date_from,
                period_end=date_to,
                detected_at=now,
                last_detected_at=now,
            )
            statement = statement.on_conflict_do_update(
                index_elements=["tenant_id", "fingerprint"],
                set_={
                    "branch_id": statement.excluded.branch_id,
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
