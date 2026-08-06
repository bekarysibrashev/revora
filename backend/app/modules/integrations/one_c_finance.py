"""Conservative 1C Stoma financial-register normalization.

Only registers with a clear business meaning are mapped. Ambiguous rows are
reported instead of being guessed, because double-counting is worse than an
explicitly incomplete dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re

from app.modules.integrations.schemas import MappingIssue


REVENUE_ENTITY = "AccumulationRegister_Выручка_RecordType"
MONEY_ENTITY = "AccumulationRegister_ДенежныеСредства_RecordType"
EXPENSE_ENTITY = "AccumulationRegister_Затраты_RecordType"
SALES_ENTITY = "AccumulationRegister_Продажи_RecordType"
MAPPABLE_ONE_C_ENTITIES = (REVENUE_ENTITY, MONEY_ENTITY, EXPENSE_ENTITY, SALES_ENTITY)


@dataclass(frozen=True, slots=True)
class OneCFinanceMapping:
    target_entity: str
    data: dict[str, object]
    issues: list[MappingIssue]

    @property
    def is_valid(self) -> bool:
        return not self.issues


def normalize_one_c_finance_record(
    *,
    source_entity: str,
    source_record_id: str,
    payload: dict[str, object],
    branch_code: str | None,
) -> OneCFinanceMapping | None:
    """Map one raw 1C row to a canonical financial fact.

    ``None`` means the register is intentionally excluded from financial totals.
    This keeps supporting/link registers from double-counting the same operation.
    """

    if source_entity not in MAPPABLE_ONE_C_ENTITIES:
        return None

    normalized = {_normalize_key(key): value for key, value in payload.items()}
    issues: list[MappingIssue] = []
    occurred_at = _period(normalized, issues)
    amount = _amount(normalized, issues)
    if payload.get("Active") is False:
        amount = Decimal("0")

    external_id = "1c:" + sha256(
        f"{source_entity}|{source_record_id}".encode("utf-8")
    ).hexdigest()
    base: dict[str, object] = {
        "external_id": external_id,
        "currency": "KZT",
    }

    if source_entity in {REVENUE_ENTITY, SALES_ENTITY}:
        if not branch_code:
            issues.append(
                MappingIssue(
                    code="ONE_C_BRANCH_MAPPING_REQUIRED",
                    message="A single/default Revora branch is required for 1C revenue",
                    field_name="branch_code",
                )
            )
        base.update(
            {
                "branch_code": branch_code,
                "recognition_type": "payment" if source_entity == REVENUE_ENTITY else "accrual",
                "occurred_at": occurred_at,
                "amount": amount,
            }
        )
        return OneCFinanceMapping("revenue_fact", base, issues)

    if source_entity == EXPENSE_ENTITY:
        category = _text_value(
            normalized,
            "СтатьяЗатрат",
            "КатегорияЗатрат",
            "ВидЗатрат",
            "Категория",
        )
        operation = _text_value(normalized, "ВидОперации", "Операция", "Содержание")
        base.update(
            {
                "branch_code": branch_code,
                "occurred_on": occurred_at.date() if occurred_at else None,
                "amount": amount,
                "category_name": category or "1С: Затраты",
                "description": operation or "Затраты из 1С",
            }
        )
        return OneCFinanceMapping("expense_fact", base, issues)

    direction = _cash_direction(normalized, amount, issues)
    base.update(
        {
            "branch_code": branch_code,
            "occurred_at": occurred_at,
            "direction": direction,
            "amount": abs(amount) if amount is not None else None,
            "category_name": _text_value(
                normalized, "СтатьяДвиженияДенежныхСредств", "Категория", "ВидОперации"
            ),
        }
    )
    return OneCFinanceMapping("cash_flow_fact", base, issues)


def _normalize_key(value: object) -> str:
    return re.sub(r"[\s_]+", "", str(value)).casefold()


def _find(source: dict[str, object], *aliases: str) -> tuple[str | None, object | None]:
    for alias in aliases:
        key = _normalize_key(alias)
        if key in source and source[key] not in (None, ""):
            return key, source[key]
    return None, None


def _period(
    source: dict[str, object], issues: list[MappingIssue]
) -> datetime | None:
    _, raw = _find(source, "Period", "Период", "Дата", "ДатаОперации")
    if raw is None:
        issues.append(
            MappingIssue(
                code="ONE_C_PERIOD_MISSING",
                message="1C row has no recognizable period field",
                field_name="Period",
            )
        )
        return None
    try:
        value = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).strip())
        comparable = (
            value.astimezone(UTC).replace(tzinfo=None)
            if value.tzinfo is not None
            else value
        )
        if value.year < 2000 or comparable > datetime.now(UTC).replace(tzinfo=None) + timedelta(days=366):
            raise ValueError("date is outside the supported business range")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone(timedelta(hours=5)))
        return value
    except (TypeError, ValueError) as exc:
        issues.append(
            MappingIssue(
                code="ONE_C_PERIOD_INVALID",
                message=f"Cannot convert 1C period: {exc}",
                field_name="Period",
                raw_value=raw,
            )
        )
        return None


def _amount(
    source: dict[str, object], issues: list[MappingIssue]
) -> Decimal | None:
    preferred = (
        "Сумма",
        "СуммаПродажи",
        "СуммаЗатрат",
        "СуммаДенежныхСредств",
        "Стоимость",
        "Выручка",
    )
    key, raw = _find(source, *preferred)
    if raw is None:
        candidates = [
            (name, value)
            for name, value in source.items()
            if ("сумм" in name or "стоим" in name)
            and not name.endswith("key")
            and value not in (None, "")
        ]
        if len(candidates) == 1:
            key, raw = candidates[0]
        elif len(candidates) > 1:
            issues.append(
                MappingIssue(
                    code="ONE_C_AMOUNT_AMBIGUOUS",
                    message="Several possible monetary fields were found",
                    field_name=", ".join(name for name, _ in candidates),
                )
            )
            return None
    if raw is None:
        issues.append(
            MappingIssue(
                code="ONE_C_AMOUNT_MISSING",
                message="1C row has no recognizable amount field",
                field_name="Сумма",
            )
        )
        return None
    try:
        if isinstance(raw, bool):
            raise InvalidOperation("boolean is not an amount")
        text = str(raw).strip().replace("\u00a0", "").replace(" ", "")
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        issues.append(
            MappingIssue(
                code="ONE_C_AMOUNT_INVALID",
                message=f"Cannot convert 1C amount: {exc}",
                field_name=key,
                raw_value=raw,
            )
        )
        return None


def _text_value(source: dict[str, object], *aliases: str) -> str | None:
    _, value = _find(source, *aliases)
    if value is None:
        return None
    text = str(value).strip()
    # Internal UUID references are not useful human-facing labels.
    if re.fullmatch(r"[0-9a-fA-F-]{36}", text):
        return None
    return text[:250] or None


def _cash_direction(
    source: dict[str, object],
    amount: Decimal | None,
    issues: list[MappingIssue],
) -> str | None:
    _, raw = _find(source, "RecordType", "ТипДвижения", "ВидДвижения", "ВидОперации")
    text = _normalize_key(raw or "")
    if any(marker in text for marker in ("expense", "расход", "списан", "выплат", "выдач")):
        return "out"
    if any(marker in text for marker in ("receipt", "приход", "поступ", "взнос", "получен")):
        return "in"
    if amount is not None and amount < 0:
        return "out"
    issues.append(
        MappingIssue(
            code="ONE_C_CASH_DIRECTION_UNKNOWN",
            message="Cash direction cannot be safely inferred from the 1C row",
            field_name="RecordType/ВидОперации",
            raw_value=raw,
        )
    )
    return None
