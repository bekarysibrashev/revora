from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.doctors.models import Doctor
from app.modules.finance.models import (
    AccountBalance,
    CashFlowFact,
    ExpenseFact,
    RevenueFact,
)
from app.modules.integrations.models import (
    IntegrationConnection,
    NormalizationError,
    SyncRun,
)
from app.modules.marketing.models import AttributionFact, MarketingSpendFact
from app.modules.sales.models import Appointment, Lead, Patient
from app.modules.tenancy.models import Branch


@dataclass(frozen=True)
class DatasetSnapshot:
    key: str
    name: str
    count: int
    latest_at: datetime | None
    scope: str = "period"


@dataclass(frozen=True)
class IssueSnapshot:
    code: str
    name: str
    description: str
    severity: str
    count: int
    dataset: str


@dataclass(frozen=True)
class ConnectionSnapshot:
    id: UUID
    provider: str
    name: str
    status: str
    last_sync_at: datetime | None
    last_sync_status: str | None


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def dataset_snapshots(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> list[DatasetSnapshot]:
        period_start = self._start(date_from)
        period_end = self._end(date_to)
        results: list[DatasetSnapshot] = []

        results.append(
            await self._snapshot(
                "patients",
                "Пациенты",
                select(func.count(Patient.id), func.max(Patient.updated_at)).where(
                    Patient.tenant_id == tenant_id
                ),
                scope="tenant",
            )
        )
        results.append(
            await self._snapshot(
                "doctors",
                "Врачи",
                select(func.count(Doctor.id), func.max(Doctor.updated_at)).where(
                    Doctor.tenant_id == tenant_id
                ),
                scope="tenant",
            )
        )

        appointment_query = select(
            func.count(Appointment.id), func.max(Appointment.updated_at)
        ).where(
            Appointment.tenant_id == tenant_id,
            Appointment.starts_at >= period_start,
            Appointment.starts_at < period_end,
        )
        lead_query = select(func.count(Lead.id), func.max(Lead.updated_at)).where(
            Lead.tenant_id == tenant_id,
            Lead.created_at >= period_start,
            Lead.created_at < period_end,
        )
        revenue_query = select(
            func.count(RevenueFact.id), func.max(RevenueFact.updated_at)
        ).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.occurred_at >= period_start,
            RevenueFact.occurred_at < period_end,
        )
        expense_query = select(
            func.count(ExpenseFact.id), func.max(ExpenseFact.updated_at)
        ).where(
            ExpenseFact.tenant_id == tenant_id,
            ExpenseFact.occurred_on >= date_from,
            ExpenseFact.occurred_on <= date_to,
        )
        cashflow_query = select(
            func.count(CashFlowFact.id), func.max(CashFlowFact.updated_at)
        ).where(
            CashFlowFact.tenant_id == tenant_id,
            CashFlowFact.occurred_at >= period_start,
            CashFlowFact.occurred_at < period_end,
        )
        balance_query = select(
            func.count(AccountBalance.id), func.max(AccountBalance.updated_at)
        ).where(
            AccountBalance.tenant_id == tenant_id,
            AccountBalance.balance_at < period_end,
        )
        marketing_query = select(
            func.count(MarketingSpendFact.id), func.max(MarketingSpendFact.updated_at)
        ).where(
            MarketingSpendFact.tenant_id == tenant_id,
            MarketingSpendFact.spend_date >= date_from,
            MarketingSpendFact.spend_date <= date_to,
        )
        attribution_query = (
            select(func.count(AttributionFact.id), func.max(AttributionFact.updated_at))
            .select_from(AttributionFact)
            .join(Lead, Lead.id == AttributionFact.lead_id)
            .where(
                AttributionFact.tenant_id == tenant_id,
                Lead.created_at >= period_start,
                Lead.created_at < period_end,
            )
        )
        if branch_id:
            appointment_query = appointment_query.where(Appointment.branch_id == branch_id)
            lead_query = lead_query.where(Lead.branch_id == branch_id)
            revenue_query = revenue_query.where(RevenueFact.branch_id == branch_id)
            expense_query = expense_query.where(ExpenseFact.branch_id == branch_id)
            cashflow_query = cashflow_query.where(CashFlowFact.branch_id == branch_id)
            balance_query = balance_query.where(AccountBalance.branch_id == branch_id)
            marketing_query = marketing_query.where(MarketingSpendFact.branch_id == branch_id)
            attribution_query = attribution_query.where(Lead.branch_id == branch_id)

        queries = [
            ("appointments", "Записи на приём", appointment_query),
            ("leads", "Лиды", lead_query),
            ("revenue", "Начисления и оплаты", revenue_query),
            ("expenses", "Расходы", expense_query),
            ("cashflow", "Движение денег", cashflow_query),
            ("balances", "Остатки на счетах", balance_query),
            ("marketing_spend", "Расходы на маркетинг", marketing_query),
            ("attribution", "Маркетинговая атрибуция", attribution_query),
        ]
        for key, name, query in queries:
            results.append(await self._snapshot(key, name, query))
        return results

    async def quality_issues(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> list[IssueSnapshot]:
        period_start = self._start(date_from)
        period_end = self._end(date_to)

        appointments_base = [
            Appointment.tenant_id == tenant_id,
            Appointment.starts_at >= period_start,
            Appointment.starts_at < period_end,
        ]
        revenue_base = [
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.occurred_at >= period_start,
            RevenueFact.occurred_at < period_end,
        ]
        expenses_base = [
            ExpenseFact.tenant_id == tenant_id,
            ExpenseFact.occurred_on >= date_from,
            ExpenseFact.occurred_on <= date_to,
        ]
        cashflow_base = [
            CashFlowFact.tenant_id == tenant_id,
            CashFlowFact.occurred_at >= period_start,
            CashFlowFact.occurred_at < period_end,
        ]
        if branch_id:
            appointments_base.append(Appointment.branch_id == branch_id)
            revenue_base.append(RevenueFact.branch_id == branch_id)
            expenses_base.append(ExpenseFact.branch_id == branch_id)
            cashflow_base.append(CashFlowFact.branch_id == branch_id)

        checks = [
            (
                "appointments_without_doctor",
                "Записи без врача",
                "Запись нельзя включить в аналитику эффективности врача.",
                "critical",
                "appointments",
                select(func.count(Appointment.id)).where(
                    *appointments_base, Appointment.doctor_id.is_(None)
                ),
            ),
            (
                "appointments_without_direction",
                "Записи без направления",
                "Невозможно корректно посчитать аналитику по специализациям.",
                "warning",
                "appointments",
                select(func.count(Appointment.id)).where(
                    *appointments_base, Appointment.direction_id.is_(None)
                ),
            ),
            (
                "revenue_without_doctor",
                "Выручка без врача",
                "Сумма попадёт в финансы, но не в показатели конкретного врача.",
                "critical",
                "revenue",
                select(func.count(RevenueFact.id)).where(
                    *revenue_base, RevenueFact.doctor_id.is_(None)
                ),
            ),
            (
                "revenue_without_patient",
                "Выручка без пациента",
                "Нельзя связать оплату с пациентской аналитикой.",
                "warning",
                "revenue",
                select(func.count(RevenueFact.id)).where(
                    *revenue_base, RevenueFact.patient_id.is_(None)
                ),
            ),
            (
                "uncategorized_expenses",
                "Расходы без категории",
                "Расходы видны в сумме, но искажают структуру ОПиУ.",
                "critical",
                "expenses",
                select(func.count(ExpenseFact.id)).where(
                    *expenses_base, ExpenseFact.category_id.is_(None)
                ),
            ),
            (
                "uncategorized_cash_outflow",
                "Списания без категории",
                "Денежные списания нельзя корректно разнести по статьям ДДС.",
                "warning",
                "cashflow",
                select(func.count(CashFlowFact.id)).where(
                    *cashflow_base,
                    CashFlowFact.direction == "out",
                    CashFlowFact.category_id.is_(None),
                ),
            ),
            (
                "doctors_without_specialty",
                "Врачи без специальности",
                "Недоступен корректный срез по специализациям.",
                "warning",
                "doctors",
                select(func.count(Doctor.id)).where(
                    Doctor.tenant_id == tenant_id,
                    (Doctor.specialty.is_(None)) | (Doctor.specialty == ""),
                ),
            ),
            (
                "patients_without_name",
                "Пациенты без имени",
                "Запись существует, но карточка пациента заполнена не полностью.",
                "warning",
                "patients",
                select(func.count(Patient.id)).where(
                    Patient.tenant_id == tenant_id,
                    (Patient.full_name.is_(None)) | (Patient.full_name == ""),
                ),
            ),
            (
                "normalization_errors",
                "Ошибки нормализации",
                "Строки источников находятся в карантине и не попали в аналитику.",
                "critical",
                "integrations",
                select(func.count(NormalizationError.id)).where(
                    NormalizationError.tenant_id == tenant_id,
                    NormalizationError.status == "open",
                ),
            ),
        ]
        issues: list[IssueSnapshot] = []
        for code, name, description, severity, dataset, query in checks:
            count = int((await self.session.scalar(query)) or 0)
            issues.append(
                IssueSnapshot(code, name, description, severity, count, dataset)
            )
        return issues

    async def connections(self, tenant_id: UUID) -> list[ConnectionSnapshot]:
        last_runs = (
            select(
                SyncRun.connection_id,
                func.max(SyncRun.started_at).label("last_sync_at"),
            )
            .where(SyncRun.tenant_id == tenant_id)
            .group_by(SyncRun.connection_id)
            .subquery()
        )
        statement = (
            select(
                IntegrationConnection.id,
                IntegrationConnection.provider,
                IntegrationConnection.name,
                IntegrationConnection.status,
                last_runs.c.last_sync_at,
                SyncRun.status,
            )
            .outerjoin(last_runs, last_runs.c.connection_id == IntegrationConnection.id)
            .outerjoin(
                SyncRun,
                (SyncRun.connection_id == IntegrationConnection.id)
                & (SyncRun.started_at == last_runs.c.last_sync_at),
            )
            .where(IntegrationConnection.tenant_id == tenant_id)
            .order_by(IntegrationConnection.name)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            ConnectionSnapshot(
                id=row[0],
                provider=row[1],
                name=row[2],
                status=row[3],
                last_sync_at=row[4],
                last_sync_status=row[5],
            )
            for row in rows
        ]

    async def active_branch_count(self, tenant_id: UUID) -> int:
        return int(
            (
                await self.session.scalar(
                    select(func.count(Branch.id)).where(
                        Branch.tenant_id == tenant_id, Branch.is_active.is_(True)
                    )
                )
            )
            or 0
        )

    async def _snapshot(self, key: str, name: str, statement, scope: str = "period"):
        row = (await self.session.execute(statement)).one()
        return DatasetSnapshot(
            key=key,
            name=name,
            count=int(row[0] or 0),
            latest_at=row[1],
            scope=scope,
        )

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _end(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)
