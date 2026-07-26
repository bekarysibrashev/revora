from datetime import UTC, date, datetime
from decimal import Decimal
from math import sqrt
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.ml.repository import MLRepository, ReadinessStats
from app.modules.ml.schemas import (
    CohortMetric,
    DatasetSnapshotListResponse,
    DatasetSnapshotResponse,
    FeatureCoverage,
    MLRegistryResponse,
    NoShowReadinessResponse,
)


FEATURES = {
    "doctor_id": "Врач, ведущий приём",
    "direction_id": "Направление лечения",
    "lead_source": "Источник привлечения пациента",
    "booking_lead_time": "Количество времени от создания записи до приёма",
}

WEEKDAYS = {
    "0": "Воскресенье",
    "1": "Понедельник",
    "2": "Вторник",
    "3": "Среда",
    "4": "Четверг",
    "5": "Пятница",
    "6": "Суббота",
}
TIME_LABELS = {
    "morning": "Утро, до 12:00",
    "afternoon": "День, 12:00–17:00",
    "evening": "Вечер, после 17:00",
}


class MLService:
    def __init__(self, repository: MLRepository) -> None:
        self.repository = repository

    async def no_show_readiness(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> NoShowReadinessResponse:
        self._validate(user, date_from, date_to, branch_id)
        stats = await self.repository.readiness(
            user.tenant_id, date_from, date_to, branch_id
        )
        cohort_rows = await self.repository.cohorts(
            user.tenant_id, date_from, date_to, branch_id
        )
        features = self._features(stats)
        positive_rate = (
            Decimal(stats.positive_count) / Decimal(stats.row_count)
            if stats.row_count
            else Decimal("0")
        )
        status, reason = self._readiness_status(stats)
        cohorts = []
        for row in cohort_rows:
            rate = Decimal(row.no_shows) / Decimal(row.appointments)
            low, high = wilson_interval(row.no_shows, row.appointments)
            lift = rate / positive_rate if positive_rate > 0 else None
            cohorts.append(
                CohortMetric(
                    dimension=row.dimension,
                    value=row.value,
                    label=(
                        WEEKDAYS.get(row.value, row.value)
                        if row.dimension == "weekday"
                        else TIME_LABELS.get(row.value, row.value)
                    ),
                    appointments=row.appointments,
                    no_shows=row.no_shows,
                    no_show_rate=rate,
                    lift_vs_baseline=lift,
                    confidence_low=low,
                    confidence_high=high,
                    reliable=row.appointments >= 30,
                )
            )
        return NoShowReadinessResponse(
            status=status,
            status_reason=reason,
            row_count=stats.row_count,
            positive_count=stats.positive_count,
            positive_rate=positive_rate,
            date_min=stats.date_min,
            date_max=stats.date_max,
            source_max_updated_at=stats.source_max_updated_at,
            recommended_train_rows=1000,
            recommended_positive_rows=100,
            feature_coverage=features,
            cohorts=cohorts,
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
            generated_at=datetime.now(UTC),
        )

    async def create_snapshot(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> DatasetSnapshotResponse:
        response = await self.no_show_readiness(user, date_from, date_to, branch_id)
        stats = await self.repository.readiness(
            user.tenant_id, date_from, date_to, branch_id
        )
        feature_schema = {
            item.name: {
                "description": item.description,
                "coverage_rate": float(item.coverage_rate),
                "usable": item.usable,
            }
            for item in response.feature_coverage
        }
        quality_report = {
            "status": response.status,
            "status_reason": response.status_reason,
            "positive_rate": float(response.positive_rate),
            "leakage_guard": "Only information known before appointment start may be used",
            "split_strategy": "Temporal split; newest observations are reserved for validation",
        }
        snapshot = await self.repository.create_snapshot(
            user.tenant_id,
            branch_id,
            date_from,
            date_to,
            stats,
            feature_schema,
            quality_report,
        )
        return self._snapshot(snapshot)

    async def snapshots(self, user: User) -> DatasetSnapshotListResponse:
        self._require_owner_or_manager(user)
        items = [
            self._snapshot(item)
            for item in await self.repository.list_snapshots(user.tenant_id)
        ]
        return DatasetSnapshotListResponse(items=items, total=len(items))

    async def registry(self, user: User) -> MLRegistryResponse:
        self._require_owner_or_manager(user)
        datasets, experiments, versions, predictions, active = (
            await self.repository.registry_counts(user.tenant_id)
        )
        return MLRegistryResponse(
            dataset_snapshots=datasets,
            experiments=experiments,
            model_versions=versions,
            predictions=predictions,
            active_model=active,
        )

    @staticmethod
    def _features(stats: ReadinessStats) -> list[FeatureCoverage]:
        counts = {
            "doctor_id": stats.doctor_count,
            "direction_id": stats.direction_count,
            "lead_source": stats.lead_source_count,
            "booking_lead_time": stats.lead_time_count,
        }
        return [
            FeatureCoverage(
                name=name,
                description=FEATURES[name],
                available_count=count,
                coverage_rate=(
                    Decimal(count) / Decimal(stats.row_count)
                    if stats.row_count
                    else Decimal("0")
                ),
                usable=stats.row_count > 0 and count / stats.row_count >= 0.70,
            )
            for name, count in counts.items()
        ]

    @staticmethod
    def _readiness_status(stats: ReadinessStats) -> tuple[str, str]:
        if stats.row_count == 0:
            return "empty", "Нет завершённых приёмов и неявок в выбранном периоде."
        if stats.positive_count < 30:
            return (
                "insufficient",
                "Слишком мало неявок для устойчивого обучения; доступен только исследовательский анализ.",
            )
        if stats.row_count < 1000 or stats.positive_count < 100:
            return (
                "exploratory",
                "Данных достаточно для baseline и проверки гипотез, но не для production-модели.",
            )
        return "ready", "Данных достаточно для временного train/validation разделения."

    @staticmethod
    def _snapshot(item) -> DatasetSnapshotResponse:
        return DatasetSnapshotResponse(
            id=item.id,
            purpose=item.purpose,
            snapshot_key=item.snapshot_key,
            branch_id=item.branch_id,
            date_from=item.date_from,
            date_to=item.date_to,
            row_count=item.row_count,
            positive_count=item.positive_count,
            feature_schema=item.feature_schema,
            quality_report=item.quality_report,
            source_max_updated_at=item.source_max_updated_at,
            created_at=item.created_at,
        )

    @staticmethod
    def _require_owner_or_manager(user: User) -> None:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("FORBIDDEN", "ML Lab is not available for this role", 403)

    @classmethod
    def _validate(
        cls, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> None:
        cls._require_owner_or_manager(user)
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        if (date_to - date_from).days > 1095:
            raise AppError("DATE_RANGE_TOO_LARGE", "Date range cannot exceed three years", 422)
        allowed = {link.branch_id for link in user.branch_links}
        if branch_id and allowed and branch_id not in allowed:
            raise AppError("BRANCH_FORBIDDEN", "Branch is outside your access scope", 403)


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[Decimal, Decimal]:
    if total == 0:
        return Decimal("0"), Decimal("0")
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return Decimal(str(max(0.0, center - margin))), Decimal(str(min(1.0, center + margin)))
