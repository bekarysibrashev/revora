"""Owner-only import and validation of official 1C reports."""

from datetime import date
import hashlib
from pathlib import Path

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.reports.one_c_parser import REPORT_LABELS, parse_official_report
from app.modules.reports.repository import OfficialReportsRepository
from app.modules.reports.schemas import OfficialReportListResponse, OfficialReportResponse

MAX_REPORT_SIZE = 50 * 1024 * 1024


class OfficialReportsService:
    def __init__(self, repository: OfficialReportsRepository) -> None:
        self.repository = repository

    async def upload(
        self, user: User, *, content: bytes, filename: str,
        period_from: date, period_to: date,
    ) -> OfficialReportResponse:
        self._require_owner(user)
        if period_from > period_to:
            raise AppError("INVALID_DATE_RANGE", "Начало периода позже окончания", 422)
        if not content or len(content) > MAX_REPORT_SIZE:
            raise AppError("INVALID_REPORT_SIZE", "Файл должен быть от 1 байта до 50 МБ", 422)
        safe_filename = Path(filename).name[:500]
        parsed = parse_official_report(content, safe_filename)
        source_hash = hashlib.sha256(content).hexdigest()
        duplicate = await self.repository.duplicate(
            user.tenant_id, parsed.report_type, period_from, period_to, source_hash
        )
        if duplicate is not None:
            if not duplicate.is_active:
                await self.repository.activate_existing(duplicate)
            return self._response(duplicate, duplicate=True)

        branches = await self.repository.branches_by_code(user.tenant_id)
        missing = sorted(
            {metric.branch_code for metric in parsed.metrics if metric.branch_code} - set(branches)
        )
        if missing:
            raise AppError(
                "OFFICIAL_REPORT_BRANCH_MISSING",
                f"В Revora отсутствуют филиалы: {', '.join(missing)}",
                422,
            )
        metrics = [{
            "branch_id": branches[metric.branch_code].id if metric.branch_code else None,
            "dimension_type": metric.dimension_type,
            "dimension_key": metric.dimension_key,
            "dimension_label": metric.dimension_label,
            "metric_code": metric.metric_code,
            "value": metric.value,
            "unit": metric.unit,
            "details": metric.details,
        } for metric in parsed.metrics]
        report = await self.repository.replace_active(
            tenant_id=user.tenant_id, report_type=parsed.report_type,
            period_from=period_from, period_to=period_to,
            source_filename=safe_filename, source_hash=source_hash,
            imported_by_user_id=user.id, summary=parsed.summary, metrics=metrics,
        )
        return self._response(report)

    async def list_active(self, user: User) -> OfficialReportListResponse:
        self._require_owner(user)
        reports = await self.repository.list_active(user.tenant_id)
        items = [self._response(report) for report in reports]
        return OfficialReportListResponse(
            items=items, total=len(items), required_report_types=list(REPORT_LABELS)
        )

    @staticmethod
    def _require_owner(user: User) -> None:
        if user.role != UserRole.OWNER:
            raise AppError("FORBIDDEN", "Только владелец может загружать эталонные отчёты 1С", 403)

    @staticmethod
    def _response(report, duplicate: bool = False) -> OfficialReportResponse:
        return OfficialReportResponse(
            id=report.id, report_type=report.report_type,
            report_label=REPORT_LABELS.get(report.report_type, report.report_type),
            period_from=report.period_from, period_to=report.period_to,
            source_filename=report.source_filename, source_hash=report.source_hash,
            metrics_count=len(report.metrics), summary=report.summary,
            is_active=report.is_active, imported_at=report.created_at,
            duplicate=duplicate,
        )
