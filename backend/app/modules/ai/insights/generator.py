"""Deterministic, auditable V1 insight generation."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AIInsight
from app.modules.doctors.repository import DoctorsRepository
from app.modules.finance.repository import FinanceRepository
from app.modules.marketing.repository import MarketingRepository
from app.modules.sales.repository import SalesRepository
from app.modules.tenancy.models import Branch


@dataclass(frozen=True)
class InsightCandidate:
    insight_type: str
    severity: str
    title: str
    description: str
    evidence: dict[str, object]


def evaluate_metrics(
    *, revenue: Decimal, expenses: Decimal, net_cash_flow: Decimal,
    closing_balance: Decimal | None, leads_total: int, leads_won: int,
    appointments_total: int, no_show: int, marketing_spend: Decimal,
    attributed_revenue: Decimal,
) -> list[InsightCandidate]:
    """Apply stable business thresholds; kept pure so every alert is testable."""
    items: list[InsightCandidate] = []
    profit = revenue - expenses
    if revenue > 0 and profit < 0:
        items.append(InsightCandidate("loss", "critical", "Клиника работает в минус",
            "Расходы за последние 30 дней превысили начисленную выручку.",
            {"revenue": float(revenue), "expenses": float(expenses), "profit": float(profit)}))
    if leads_total >= 10:
        conversion = Decimal(leads_won) / Decimal(leads_total) * 100
        if conversion < 25:
            items.append(InsightCandidate("performance", "warning", "Низкая конверсия лидов",
                "Менее четверти обращений перешли в успешную продажу.",
                {"leads_total": leads_total, "leads_won": leads_won, "conversion_percent": float(conversion)}))
    if appointments_total >= 10:
        rate = Decimal(no_show) / Decimal(appointments_total) * 100
        if rate > 15:
            items.append(InsightCandidate("loss", "warning", "Много пациентов не приходят",
                "Доля неявок выше 15%. Проверьте напоминания и подтверждение записей.",
                {"appointments_total": appointments_total, "no_show": no_show, "no_show_percent": float(rate)}))
    if marketing_spend > 0:
        roas = attributed_revenue / marketing_spend
        if roas < 1:
            items.append(InsightCandidate("performance", "warning", "Реклама не окупается",
                "Связанная с рекламой выручка ниже затрат за последние 30 дней.",
                {"spend": float(marketing_spend), "attributed_revenue": float(attributed_revenue), "roas": float(roas)}))
    if closing_balance is not None:
        projected = closing_balance + (net_cash_flow / Decimal(30) * Decimal(14))
        if projected < 0:
            items.append(InsightCandidate("forecast", "critical", "Риск кассового разрыва",
                "При сохранении текущего денежного потока прогнозный остаток через 14 дней станет отрицательным.",
                {"closing_balance": float(closing_balance), "net_cash_flow_30d": float(net_cash_flow), "projected_balance_14d": float(projected)}))
    return items


class InsightGenerator:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def generate_for_tenant(self, tenant_id: UUID, today: date | None = None) -> int:
        today = today or datetime.now(UTC).date()
        await self.session.execute(text("SELECT set_config('app.tenant_id', :value, true)"), {"value": str(tenant_id)})
        branches = list((await self.session.scalars(select(Branch.id).where(Branch.tenant_id == tenant_id, Branch.is_active.is_(True)))).all())
        created = 0
        for branch_id in [None, *branches]:
            start = today - timedelta(days=29)
            finance = await FinanceRepository(self.session).pnl_totals(tenant_id, start, today, branch_id)
            cash = await FinanceRepository(self.session).cashflow_totals(tenant_id, start, today, branch_id)
            sales = await SalesRepository(self.session).overview(tenant_id, start, today, [branch_id] if branch_id else None, None)
            marketing = await MarketingRepository(self.session).overview(tenant_id, start, today, branch_id)
            spend = sum(marketing.spend_by_source.values(), Decimal(0))
            attributed = sum(marketing.revenue_by_source.values(), Decimal(0))
            candidates = evaluate_metrics(revenue=finance.revenue_accrual,
                expenses=finance.variable_expenses + finance.fixed_expenses + finance.uncategorized_expenses,
                net_cash_flow=cash.inflow - cash.outflow, closing_balance=cash.closing_balance,
                leads_total=sales.leads_total, leads_won=sales.leads_won,
                appointments_total=sales.appointments_total, no_show=sales.appointments_no_show,
                marketing_spend=spend, attributed_revenue=attributed)
            for item in candidates:
                fingerprint = sha256(f"{tenant_id}:{branch_id}:{item.insight_type}:{item.title}:{today.isocalendar().year}-{today.isocalendar().week}".encode()).hexdigest()
                statement = insert(AIInsight).values(tenant_id=tenant_id, branch_id=branch_id,
                    fingerprint=fingerprint, insight_type=item.insight_type, severity=item.severity,
                    title=item.title, description=item.description, evidence=item.evidence,
                    detected_at=datetime.now(UTC), valid_until=datetime.now(UTC) + timedelta(days=8))
                statement = statement.on_conflict_do_update(index_elements=["tenant_id", "fingerprint"],
                    set_={"severity": item.severity, "description": item.description,
                          "evidence": item.evidence, "detected_at": datetime.now(UTC),
                          "valid_until": datetime.now(UTC) + timedelta(days=8)})
                await self.session.execute(statement)
                created += 1
        return created
