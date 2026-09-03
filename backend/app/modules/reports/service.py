"""Owner-only import and validation of official 1C reports."""

from datetime import date
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.reports.one_c_parser import REPORT_LABELS, parse_official_report
from app.modules.reports.repository import OfficialReportsRepository
from app.modules.reports.schemas import (
    OfficialReportListResponse,
    OfficialReportResponse,
    OneCReportSnapshotBatchResponse,
    OneCReportSnapshotRequest,
)

MAX_REPORT_SIZE = 50 * 1024 * 1024
REPORT_METRIC_CODES = {
    "cash_receipts": {"revenue_payment", "cash_inflow"},
    "service_revenue": {"services_count", "revenue_accrual", "revenue_before_discount"},
    "payroll": {"payroll_accrual", "payroll_paid", "payroll_due"},
    "doctor_revenue": {"doctor_revenue_payment"},
    "purchases": {
        "purchases_accrual_all_entities", "purchases_paid_all_entities",
        "purchases_accrual", "purchases_paid",
    },
    "patients": {
        "patients_total", "patients_primary", "patient_visits",
        "patient_report_revenue", "patient_report_paid",
        "patient_seen", "patient_primary_seen",
    },
    "appointments": {
        "appointments_total", "appointments_primary", "appointments_completed",
        "appointments_cancelled", "appointments_no_show",
        "appointment_report_revenue", "appointment_report_paid",
    },
}


def _normalize_branch_name(value: object) -> str:
    text_value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return re.sub(r"[^a-zа-я0-9]+", "", text_value)


def _transliterate_branch_name(value: str) -> str:
    return value.translate(str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
        "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
        "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
        "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
    }))


def _branch_matches_unit(unit_name: str, *, branch_name: str, branch_code: str) -> bool:
    unit_aliases = {unit_name, _transliterate_branch_name(unit_name)}
    return any(
        branch_alias
        and unit_alias
        and (
            branch_alias == unit_alias
            or branch_alias in unit_alias
            or unit_alias in branch_alias
        )
        for branch_alias in {branch_name, branch_code}
        for unit_alias in unit_aliases
    )


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

    async def ingest_connector_snapshot(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        branch_code_map: dict[str, str],
        payload: OneCReportSnapshotRequest,
    ) -> OfficialReportResponse:
        if payload.period_from > payload.period_to:
            raise AppError("INVALID_DATE_RANGE", "Начало периода позже окончания", 422)
        allowed_codes = REPORT_METRIC_CODES[payload.report_type]
        unexpected = sorted({item.metric_code for item in payload.metrics} - allowed_codes)
        if unexpected:
            raise AppError(
                "INVALID_1C_REPORT_METRIC",
                f"Недопустимые показатели: {', '.join(unexpected)}",
                422,
            )

        branches = await self.repository.branches_by_code(tenant_id)
        payload_branch_labels = {
            item.branch_key.casefold(): item.dimension_label
            for item in payload.metrics
            if item.dimension_type == "branch" and item.branch_key
        }
        effective_branch_code_map = {
            key.casefold(): code for key, code in branch_code_map.items()
        }
        for source_key, source_label in payload_branch_labels.items():
            if source_key in effective_branch_code_map:
                continue
            unit_name = _normalize_branch_name(source_label)
            matches = [
                branch
                for branch in branches.values()
                if _branch_matches_unit(
                    unit_name,
                    branch_name=_normalize_branch_name(branch.name),
                    branch_code=_normalize_branch_name(branch.code),
                )
            ]
            if len(matches) == 1:
                effective_branch_code_map[source_key] = str(matches[0].code)

        metrics: list[dict] = []
        unmapped_branches: dict[str, str] = {}
        for item in payload.metrics:
            branch_id = None
            if item.dimension_type != "clinic" and not item.branch_key:
                raise AppError(
                    "ONE_C_BRANCH_KEY_REQUIRED",
                    f"Для измерения {item.dimension_type} требуется ключ подразделения 1С",
                    422,
                )
            if item.branch_key:
                source_key = item.branch_key.casefold()
                branch_code = effective_branch_code_map.get(source_key)
                if not branch_code:
                    unmapped_branches[source_key] = payload_branch_labels.get(
                        source_key, item.branch_key
                    )
                    continue
                branch = branches.get(branch_code)
                if branch is None:
                    unmapped_branches[source_key] = payload_branch_labels.get(
                        source_key, branch_code
                    )
                    continue
                branch_id = branch.id
            metrics.append({
                "branch_id": branch_id,
                "dimension_type": item.dimension_type,
                "dimension_key": item.dimension_key,
                "dimension_label": item.dimension_label,
                "metric_code": item.metric_code,
                "value": item.value,
                "unit": item.unit,
                "details": item.details,
            })

        summary = dict(payload.summary)
        if unmapped_branches:
            summary["unmapped_branches"] = [
                {"source_key": key, "source_label": label}
                for key, label in sorted(unmapped_branches.items())
            ]

        canonical = payload.model_dump(mode="json")
        source_hash = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        duplicate = await self.repository.duplicate(
            tenant_id, payload.report_type, payload.period_from, payload.period_to, source_hash
        )
        if duplicate is not None:
            if not duplicate.is_active:
                await self.repository.activate_existing(duplicate)
            return self._response(duplicate, duplicate=True)

        report = await self.repository.replace_active(
            tenant_id=tenant_id,
            report_type=payload.report_type,
            period_from=payload.period_from,
            period_to=payload.period_to,
            source_filename=f"1c-extension:{connection_id}:{payload.report_type}",
            source_hash=source_hash,
            imported_by_user_id=None,
            summary=summary,
            metrics=metrics,
        )
        return self._response(report)

    async def ingest_connector_snapshots(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        branch_code_map: dict[str, str],
        snapshots: list[OneCReportSnapshotRequest],
    ) -> OneCReportSnapshotBatchResponse:
        items = [
            await self.ingest_connector_snapshot(
                tenant_id=tenant_id,
                connection_id=connection_id,
                branch_code_map=branch_code_map,
                payload=snapshot,
            )
            for snapshot in snapshots
        ]
        return OneCReportSnapshotBatchResponse(items=items, total=len(items))

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
