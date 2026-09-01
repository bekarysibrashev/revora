from dataclasses import dataclass
from datetime import date, timedelta
from typing import Awaitable, Callable
from uuid import UUID
from pydantic import BaseModel, ConfigDict, ValidationError
from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.dashboard.service import DashboardService
from app.modules.doctors.service import DoctorsService
from app.modules.finance.service import FinanceService
from app.modules.marketing.service import MarketingService
from app.modules.sales.service import SalesService

class PeriodArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_from: date | None = None
    date_to: date | None = None

@dataclass(frozen=True)
class ToolResult:
    name: str
    label: str
    payload: dict
    date_from: date
    date_to: date
    branch_id: UUID | None
    data_as_of: str | None

@dataclass(frozen=True)
class AnalystTool:
    name: str
    label: str
    description: str
    roles: frozenset[UserRole]
    execute: Callable[[User, date, date, UUID | None], Awaitable[BaseModel]]

ALL = frozenset(UserRole)
MANAGEMENT = frozenset({UserRole.OWNER, UserRole.MANAGER})
OPERATIONS = frozenset({UserRole.OWNER, UserRole.MANAGER, UserRole.ADMINISTRATOR})

class AnalystToolRegistry:
    def __init__(self, finance: FinanceService, sales: SalesService, doctors: DoctorsService,
                 marketing: MarketingService, dashboard: DashboardService) -> None:
        self._tools = {
            item.name: item for item in (
                AnalystTool("finance_summary", "Финансовая сводка", "Начисленная и оплаченная выручка, расходы, прибыль, денежный поток и остаток.", MANAGEMENT, finance.summary),
                AnalystTool("pnl", "Прибыли и убытки", "Выручка, расходы по категориям и управленческий результат с явным признаком полноты данных.", MANAGEMENT, finance.pnl),
                AnalystTool("cashflow", "Движение денег", "Поступления, списания, чистый денежный поток и остаток.", MANAGEMENT, finance.cashflow),
                AnalystTool("sales_overview", "Продажи и записи", "Лиды, конверсия, статусы записей, неявки и оплаченная выручка в разрешённом scope.", ALL, sales.overview),
                AnalystTool("doctors_overview", "Эффективность врачей", "Нагрузка, завершение записей, выручка и рейтинги врачей.", OPERATIONS, doctors.overview),
                AnalystTool("marketing_overview", "Маркетинг", "Расходы, атрибутированная выручка и ROAS по источникам.", MANAGEMENT, marketing.overview),
                AnalystTool("ceo_dashboard", "Обзор клиники", "Сводный управленческий обзор финансов, продаж, врачей и маркетинга.", MANAGEMENT, dashboard.ceo),
            )
        }

    def definitions(self, user: User) -> list[dict]:
        return [{"type":"function","name":tool.name,"description":tool.description,"strict":True,
                 "parameters":{"type":"object","properties":{
                    "date_from":{"type":["string","null"],"description":"Начало периода YYYY-MM-DD"},
                    "date_to":{"type":["string","null"],"description":"Конец периода YYYY-MM-DD"}},
                    "required":["date_from","date_to"],"additionalProperties":False}}
                for tool in self._tools.values() if user.role in tool.roles]

    async def run(self, name: str, arguments: dict, *, user: User, branch_id: UUID | None,
                  default_from: date, default_to: date) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None or user.role not in tool.roles:
            raise AppError("AI_TOOL_FORBIDDEN", "The requested analytical tool is unavailable for this role", 403)
        try: args = PeriodArgs.model_validate(arguments)
        except ValidationError as exc: raise AppError("AI_TOOL_ARGUMENTS_INVALID", "Invalid analytical tool arguments", 422) from exc
        date_from, date_to = args.date_from or default_from, args.date_to or default_to
        if date_from > date_to or (date_to-date_from).days > 366:
            raise AppError("AI_DATE_RANGE_INVALID", "AI analysis period must be valid and no longer than 366 days", 422)
        response = await tool.execute(user, date_from, date_to, branch_id)
        raw_payload = response.model_dump(mode="json")
        data_as_of = _find_data_as_of(raw_payload)
        payload = _cap_large_lists(_privacy_safe_payload(raw_payload))
        return ToolResult(name, tool.label, payload, date_from, date_to, branch_id, data_as_of)

def _find_data_as_of(payload: dict) -> str | None:
    direct = payload.get("data_as_of")
    if direct: return str(direct)
    meta = payload.get("meta")
    if isinstance(meta, dict) and meta.get("data_as_of"): return str(meta["data_as_of"])
    candidates=[]
    for value in payload.values():
        if isinstance(value, dict):
            found=_find_data_as_of(value)
            if found:candidates.append(found)
    return max(candidates) if candidates else None

def _privacy_safe_payload(payload: dict) -> dict:
    """Strip direct identifiers before analytical results leave Revora for an LLM."""
    person_number = 0
    forbidden = {
        "full_name", "first_name", "last_name", "email", "phone", "phone_e164",
        "phone_hash", "iin", "external_id", "patient_id", "user_id",
    }

    def clean(value):
        nonlocal person_number
        if isinstance(value, list):
            return [clean(item) for item in value]
        if not isinstance(value, dict):
            return value
        is_doctor = "doctor_id" in value or "full_name" in value
        result = {}
        if is_doctor:
            person_number += 1
            result["analyst_label"] = f"Врач {person_number}"
        for key, item in value.items():
            normalized = key.lower()
            if normalized in forbidden or normalized == "doctor_id" or normalized.endswith("_id") or normalized.endswith("_ids"):
                continue
            result[key] = clean(item)
        return result

    return clean(payload)


_RANKING_KEYS = (
    "revenue_accrual", "revenue_payment", "amount", "total", "value", "spend", "count",
)


def _as_number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def _cap_large_lists(payload: dict, max_items: int = 20) -> dict:
    """Keep tool payloads small before they are serialized into the LLM prompt.

    A handful of Revora tools (doctors_overview, sales/marketing breakdowns) can
    return one row per doctor/campaign with no upper bound. Sent verbatim, a
    clinic with 100+ doctors blows past the LLM provider's request-size limit
    (observed as a raw HTTP 413 from Groq) on an ordinary question. Instead, any
    list longer than max_items is sorted by the most relevant numeric field
    (so "which doctor earned the most" style questions keep the doctors that
    matter) and truncated, with a note the model can quote to the user.
    """

    def cap(value):
        if isinstance(value, dict):
            return {key: cap(item) for key, item in value.items()}
        if isinstance(value, list):
            items = [cap(item) for item in value]
            if len(items) <= max_items:
                return items
            sort_key = None
            if items and isinstance(items[0], dict):
                for key in _RANKING_KEYS:
                    if key in items[0]:
                        sort_key = key
                        break
            if sort_key:
                items = sorted(items, key=lambda item: _as_number(item.get(sort_key)), reverse=True)
            kept = items[:max_items]
            note = f"top {max_items} of {len(items)} rows"
            if sort_key:
                note += f", sorted by {sort_key} descending"
            kept.append({"analyst_note": note})
            return kept
        return value

    return cap(payload)
