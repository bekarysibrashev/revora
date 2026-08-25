from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from app.core.errors import AppError
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.analytics.schemas import (
    ConnectionHealth,
    DataQualityResponse,
    DataQualitySummary,
    DatasetHealth,
    MetricCatalogResponse,
    MetricDefinition,
    QualityIssue,
)
from app.modules.auth.models import User, UserRole


METRICS = [
    {
        "key": "revenue_accrual",
        "name": "Начисленная выручка",
        "group": "Финансы",
        "description": "Стоимость оказанных услуг по дате признания.",
        "formula": "Сумма revenue.amount, где recognition_type = accrual",
        "required": ["revenue"],
    },
    {
        "key": "revenue_payment",
        "name": "Оплаченная выручка",
        "group": "Финансы",
        "description": "Фактически полученные оплаты пациентов.",
        "formula": "Сумма revenue.amount, где recognition_type = payment",
        "required": ["revenue"],
    },
    {
        "key": "total_expenses",
        "name": "Расходы",
        "group": "Финансы",
        "description": "Все расходы клиники за период.",
        "formula": "Переменные + постоянные + некатегоризированные расходы",
        "required": ["expenses"],
    },
    {
        "key": "net_profit",
        "name": "Чистая прибыль",
        "group": "Финансы",
        "description": "Финансовый результат клиники за период.",
        "formula": "Начисленная выручка − все расходы",
        "required": ["revenue", "expenses"],
    },
    {
        "key": "net_cash_flow",
        "name": "Чистый денежный поток",
        "group": "ДДС",
        "description": "Изменение денежных средств за период.",
        "formula": "Поступления − списания",
        "required": ["cashflow"],
    },
    {
        "key": "closing_balance",
        "name": "Остаток денежных средств",
        "group": "ДДС",
        "description": "Последний известный остаток не позднее конца периода.",
        "formula": "Последний account_balance по дате",
        "required": ["balances"],
    },
    {
        "key": "appointment_completion_rate",
        "name": "Выполнение записей",
        "group": "Продажи",
        "description": "Доля завершённых приёмов среди всех записей.",
        "formula": "Завершённые записи / все записи × 100%",
        "required": ["appointments"],
    },
    {
        "key": "no_show_rate",
        "name": "Доля неявок",
        "group": "Продажи",
        "description": "Доля записей со статусом «не пришёл».",
        "formula": "Неявки / все записи × 100%",
        "required": ["appointments"],
    },
    {
        "key": "lead_conversion_rate",
        "name": "Конверсия лидов",
        "group": "Продажи",
        "description": "Доля выигранных или конвертированных лидов.",
        "formula": "Выигранные лиды / все лиды × 100%",
        "required": ["leads"],
    },
    {
        "key": "doctor_revenue",
        "name": "Выручка по врачам",
        "group": "Врачи",
        "description": "Начисления, связанные с конкретным врачом.",
        "formula": "Начисленная выручка, сгруппированная по doctor_id",
        "required": ["revenue", "doctors"],
    },
    {
        "key": "marketing_roas",
        "name": "ROAS",
        "group": "Маркетинг",
        "description": "Возврат выручки на рекламные вложения.",
        "formula": "Атрибутированная выручка / расходы на маркетинг",
        "required": ["marketing_spend", "attribution"],
    },
]


class AnalyticsService:
    def __init__(self, repository: AnalyticsRepository) -> None:
        self.repository = repository

    async def quality(
        self,
        user: User,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> DataQualityResponse:
        self._validate(user, date_from, date_to, branch_id)
        now = datetime.now(UTC)
        snapshots = await self.repository.dataset_snapshots(
            user.tenant_id, date_from, date_to, branch_id
        )
        issues = await self.repository.quality_issues(
            user.tenant_id, date_from, date_to, branch_id
        )
        connections = await self.repository.connections(user.tenant_id)
        datasets = [
            DatasetHealth(
                key=item.key,
                name=item.name,
                record_count=item.count,
                latest_at=item.latest_at,
                status=self._dataset_status(
                    item.count, item.latest_at, now, item.scope
                ),
                scope=item.scope,
            )
            for item in snapshots
        ]
        issue_models = [
            QualityIssue(
                code=item.code,
                name=item.name,
                description=item.description,
                severity=item.severity,
                affected_records=item.count,
                dataset=item.dataset,
            )
            for item in issues
            if item.count > 0
        ]
        required = {"patients", "doctors", "appointments", "revenue", "expenses"}
        empty_required = sum(
            1 for item in datasets if item.key in required and item.record_count == 0
        )
        critical = sum(1 for item in issue_models if item.severity == "critical")
        warnings = sum(1 for item in issue_models if item.severity == "warning")
        score = max(0, 100 - empty_required * 12 - critical * 8 - warnings * 4)
        if empty_required == len(required):
            status = "critical"
        elif score >= 85:
            status = "good"
        elif score >= 60:
            status = "warning"
        else:
            status = "critical"
        applicable_datasets = [
            item for item in datasets if item.status != "not_connected"
        ]
        return DataQualityResponse(
            summary=DataQualitySummary(
                score=score,
                status=status,
                ready_datasets=sum(
                    1 for item in applicable_datasets if item.record_count > 0
                ),
                total_datasets=len(applicable_datasets),
                critical_issues=critical,
                warning_issues=warnings,
            ),
            datasets=datasets,
            issues=issue_models,
            connections=[
                ConnectionHealth(
                    id=item.id,
                    provider=item.provider,
                    name=item.name,
                    status=item.status,
                    last_sync_at=item.last_sync_at,
                    last_sync_status=item.last_sync_status,
                )
                for item in connections
            ],
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
            generated_at=now,
        )

    async def metric_catalog(
        self,
        user: User,
        date_from: date,
        date_to: date,
        branch_id: UUID | None,
    ) -> MetricCatalogResponse:
        self._validate(user, date_from, date_to, branch_id)
        snapshots = await self.repository.dataset_snapshots(
            user.tenant_id, date_from, date_to, branch_id
        )
        available_datasets = {item.key for item in snapshots if item.count > 0}
        items = []
        for metric in METRICS:
            missing = [
                item for item in metric["required"] if item not in available_datasets
            ]
            items.append(
                MetricDefinition(
                    key=metric["key"],
                    name=metric["name"],
                    group=metric["group"],
                    description=metric["description"],
                    formula=metric["formula"],
                    required_datasets=metric["required"],
                    available=not missing,
                    missing_datasets=missing,
                )
            )
        return MetricCatalogResponse(
            items=items,
            available=sum(1 for item in items if item.available),
            total=len(items),
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
            generated_at=datetime.now(UTC),
        )

    @staticmethod
    def _dataset_status(
        count: int, latest_at: datetime | None, now: datetime, scope: str = "period"
    ) -> str:
        if count == 0:
            return "not_connected" if scope == "external" else "empty"
        if latest_at is None:
            return "unknown"
        comparable = latest_at if latest_at.tzinfo else latest_at.replace(tzinfo=UTC)
        return "stale" if comparable < now - timedelta(days=7) else "ready"

    @staticmethod
    def _validate(
        user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> None:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError(
                "FORBIDDEN", "Data quality analytics are not available for this role", 403
            )
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        if (date_to - date_from).days > 1095:
            raise AppError("DATE_RANGE_TOO_LARGE", "Date range cannot exceed three years", 422)
        if branch_id is not None and user.branch_links:
            allowed = {link.branch_id for link in user.branch_links}
            if branch_id not in allowed:
                raise AppError("BRANCH_FORBIDDEN", "Branch is outside your access scope", 403)
