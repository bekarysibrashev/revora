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
PAYROLL_ENTITY = "Document_НачислениеЗарплаты"
PAYROLL_LINE_ENTITY = "Document_НачислениеЗарплаты_РасчетЗарплаты"
PAYROLL_REGISTER_ENTITY = "AccumulationRegister_РасчетыСПерсоналом_RecordType"
PAYROLL_EXPENSE_LINE_ENTITY = "Document_НачислениеЗарплаты_Затраты"
RECEPTION_ENTITY = "Document_Прием"
RECEPTION_SERVICE_ENTITY = "Document_Прием_Лечение"
RETAIL_SALE_ENTITY = "Document_Реализация"
RETAIL_SALE_SERVICE_ENTITY = "Document_Реализация_Услуги"
PURCHASE_ENTITY = "Document_Поступление"
INCOMING_PAYMENT_ENTITY = "Document_ПоступлениеДенежныхСредств"
INCOMING_PAYMENT_LINE_ENTITY = "Document_ПоступлениеДенежныхСредств_РасшифровкаПлатежа"
OUTGOING_PAYMENT_ENTITY = "Document_СписаниеДенежныхСредств"
OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY = "Document_СписаниеДенежныхСредств_Затраты"
OUTGOING_PAYMENT_LINE_ENTITY = "Document_СписаниеДенежныхСредств_РасшифровкаПлатежа"
MAPPABLE_ONE_C_ENTITIES = (
    REVENUE_ENTITY,
    MONEY_ENTITY,
    EXPENSE_ENTITY,
    SALES_ENTITY,
    PAYROLL_ENTITY,
    PAYROLL_LINE_ENTITY,
    PAYROLL_REGISTER_ENTITY,
    PAYROLL_EXPENSE_LINE_ENTITY,
    RECEPTION_ENTITY,
    RECEPTION_SERVICE_ENTITY,
    RETAIL_SALE_ENTITY,
    RETAIL_SALE_SERVICE_ENTITY,
    PURCHASE_ENTITY,
    INCOMING_PAYMENT_ENTITY,
    INCOMING_PAYMENT_LINE_ENTITY,
    OUTGOING_PAYMENT_ENTITY,
    OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY,
    OUTGOING_PAYMENT_LINE_ENTITY,
)


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
    if source_entity == PAYROLL_EXPENSE_LINE_ENTITY:
        occurred_at = _payroll_period(normalized, issues)
        amount = _amount(normalized, issues)
    elif source_entity == PAYROLL_LINE_ENTITY:
        occurred_at = _payroll_period(normalized, issues)
        # Superseded source: calculation rows contain bases, corrections and
        # deductions and therefore do not equal the official accrued payroll.
        amount = Decimal("0")
    elif source_entity == PAYROLL_ENTITY:
        occurred_at = _payroll_period(normalized, issues)
        # Header totals contain a broader composition than the report column.
        amount = Decimal("0")
    elif source_entity == PAYROLL_REGISTER_ENTITY:
        occurred_at = _payroll_register_period(normalized, issues)
        # Retain a zero fact so reprocessing removes values written by the old
        # register-based rule without counting the same payroll twice.
        amount = Decimal("0")
    else:
        occurred_at = _period(normalized, issues)
        amount = _amount(normalized, issues)
    if payload.get("Active") is False:
        amount = Decimal("0")
    if source_entity in {
        PAYROLL_ENTITY,
        PAYROLL_LINE_ENTITY,
        PAYROLL_EXPENSE_LINE_ENTITY,
        RECEPTION_ENTITY,
        RECEPTION_SERVICE_ENTITY,
        RETAIL_SALE_ENTITY,
        RETAIL_SALE_SERVICE_ENTITY,
        PURCHASE_ENTITY,
        INCOMING_PAYMENT_ENTITY,
        INCOMING_PAYMENT_LINE_ENTITY,
        OUTGOING_PAYMENT_ENTITY,
        OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY,
        OUTGOING_PAYMENT_LINE_ENTITY,
    } and (
        payload.get("DeletionMark") is True or payload.get("Posted") is False
    ):
        amount = Decimal("0")

    external_id = one_c_finance_external_id(source_entity, source_record_id)
    base: dict[str, object] = {
        "external_id": external_id,
        "currency": "KZT",
    }

    if source_entity in {
        REVENUE_ENTITY,
        SALES_ENTITY,
        RECEPTION_SERVICE_ENTITY,
        RETAIL_SALE_SERVICE_ENTITY,
        INCOMING_PAYMENT_LINE_ENTITY,
        OUTGOING_PAYMENT_LINE_ENTITY,
    }:
        if not branch_code:
            issues.append(
                MappingIssue(
                    code="ONE_C_BRANCH_MAPPING_REQUIRED",
                    message="A Revora branch mapping is required for 1C revenue",
                    field_name="branch_code",
                )
            )
        if source_entity == REVENUE_ENTITY and not _is_actual_patient_payment(normalized):
            # Keep an excluded row as a zero-valued fact. Reprocessing can then
            # safely correct canonical rows created by an older broader mapper.
            amount = Decimal("0")
        if source_entity == SALES_ENTITY:
            # The Sales accumulation register is a posting layer, not the
            # report source. Service document lines below are authoritative.
            amount = Decimal("0")
        is_doctor_payment = source_entity in {
            INCOMING_PAYMENT_LINE_ENTITY,
            OUTGOING_PAYMENT_LINE_ENTITY,
        }
        if is_doctor_payment and not _is_doctor_payment_operation(normalized):
            # Payment breakdown tables are reused by 1C for salary, supplier
            # and internal-transfer documents. Only patient/deposit/refund/
            # insurance operations belong to the paid-by-doctor report.
            amount = Decimal("0")
        if source_entity == OUTGOING_PAYMENT_LINE_ENTITY and amount is not None:
            amount = -abs(amount)
        base.update(
            {
                "branch_code": branch_code,
                "patient_external_id": _reference_value(normalized, "Контрагент_Key"),
                "doctor_external_id": _reference_value(
                    normalized, "Сотрудник_Key", "Куратор_Key"
                ),
                "direction_external_id": _reference_value(
                    normalized, "Номенклатура_Key"
                ),
                "recognition_type": (
                    "doctor_payment"
                    if is_doctor_payment
                    else "payment"
                    if source_entity == REVENUE_ENTITY
                    else "accrual"
                ),
                "occurred_at": occurred_at,
                "amount": amount,
            }
        )
        return OneCFinanceMapping("revenue_fact", base, issues)

    if source_entity in {
        PAYROLL_ENTITY,
        PAYROLL_LINE_ENTITY,
        PAYROLL_REGISTER_ENTITY,
        PAYROLL_EXPENSE_LINE_ENTITY,
        INCOMING_PAYMENT_ENTITY,
        OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY,
    }:
        is_payroll_payment = source_entity in {
            INCOMING_PAYMENT_ENTITY,
            OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY,
        } and _is_payroll_payment_document(normalized)
        if source_entity in {
            INCOMING_PAYMENT_ENTITY,
            OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY,
        } and not is_payroll_payment:
            return None
        if not branch_code:
            issues.append(
                MappingIssue(
                    code="ONE_C_BRANCH_MAPPING_REQUIRED",
                    message="A Revora branch mapping is required for 1C payroll",
                    field_name="branch_code",
                )
            )
        base.update(
            {
                "branch_code": branch_code,
                "employee_external_id": _reference_value(normalized, "Сотрудник_Key"),
                "occurred_on": (
                    _payroll_payment_period(normalized, issues).date()
                    if is_payroll_payment
                    else occurred_at.date() if occurred_at else None
                ),
                "amount": amount if source_entity == PAYROLL_EXPENSE_LINE_ENTITY else Decimal("0"),
                "paid_amount": (
                    abs(amount or Decimal("0"))
                    if source_entity == OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY
                    else -abs(amount or Decimal("0"))
                    if source_entity == INCOMING_PAYMENT_ENTITY
                    else Decimal("0")
                ),
            }
        )
        return OneCFinanceMapping("payroll_fact", base, issues)

    if source_entity in {EXPENSE_ENTITY, PURCHASE_ENTITY}:
        if not branch_code:
            issues.append(
                MappingIssue(
                    code="ONE_C_BRANCH_MAPPING_REQUIRED",
                    message="A Revora branch mapping is required for 1C expenses",
                    field_name="branch_code",
                )
            )
        if source_entity == EXPENSE_ENTITY:
            amount = Decimal("0")
        category = _text_value(
            normalized,
            "_ResolvedCategoryName",
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
                "paid_amount": (
                    _decimal_from_alias(normalized, "СуммаОплачено", issues)
                    if source_entity == PURCHASE_ENTITY
                    else Decimal("0")
                ),
                "category_name": category or "1С: Затраты",
                "cost_behavior": _expense_cost_behavior(category),
                "description": operation or "Затраты из 1С",
            }
        )
        return OneCFinanceMapping("expense_fact", base, issues)

    if source_entity in {RECEPTION_ENTITY, RETAIL_SALE_ENTITY}:
        # Header rows are dependencies for their service table parts.
        return None

    if source_entity != MONEY_ENTITY:
        return None

    if not branch_code:
        issues.append(
            MappingIssue(
                code="ONE_C_BRANCH_MAPPING_REQUIRED",
                message="A Revora branch mapping is required for 1C cash flow",
                field_name="branch_code",
            )
        )
    direction = _cash_direction(normalized, amount, issues)
    # The money register includes transfers between the clinic's own accounts.
    # Preserve zero facts only to remove values written by older formulas. The
    # direction must be resolved before zeroing the amount because older 1C
    # rows encode an outflow only through a negative amount.
    amount = Decimal("0")
    base.update(
        {
            "branch_code": branch_code,
            "occurred_at": occurred_at,
            "direction": direction,
            "amount": abs(amount) if amount is not None else None,
            "category_name": _text_value(
                normalized,
                "_ResolvedCategoryName",
                "СтатьяДвиженияДенежныхСредств",
                "Категория",
                "ВидОперации",
            ),
            "account_ref": _reference_value(
                normalized, "БанковскийСчетКасса", "Касса_Key"
            ) or _text_value(normalized, "ТипДенежныхСредств"),
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
    _, raw = _find(source, "Period", "Date", "Период", "Дата", "ДатаОперации")
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
        "СуммаДокумента",
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
    return _decimal_value(raw, key, issues)


def _payroll_period(
    source: dict[str, object], issues: list[MappingIssue]
) -> datetime | None:
    _, raw = _find(source, "ДатаОкончанияПериода", "ДатаНачалаПериода", "Date")
    if raw is None:
        issues.append(
            MappingIssue(
                code="ONE_C_PERIOD_MISSING",
                message="1C payroll document has no accounting period",
                field_name="ДатаОкончанияПериода",
            )
        )
        return None
    try:
        value = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).strip())
        return value if value.tzinfo else value.replace(tzinfo=timezone(timedelta(hours=5)))
    except (TypeError, ValueError) as exc:
        issues.append(
            MappingIssue(
                code="ONE_C_PERIOD_INVALID",
                message=f"Cannot convert 1C payroll period: {exc}",
                field_name="ДатаОкончанияПериода",
                raw_value=raw,
            )
        )
        return None


def _payroll_register_period(
    source: dict[str, object], issues: list[MappingIssue]
) -> datetime | None:
    _, raw = _find(source, "МесяцНачисления", "Period", "Период")
    if raw is None:
        issues.append(
            MappingIssue(
                code="ONE_C_PERIOD_MISSING",
                message="1C personnel settlement row has no accrual month",
                field_name="МесяцНачисления",
            )
        )
        return None
    try:
        value = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).strip())
        return value if value.tzinfo else value.replace(tzinfo=timezone(timedelta(hours=5)))
    except (TypeError, ValueError) as exc:
        issues.append(
            MappingIssue(
                code="ONE_C_PERIOD_INVALID",
                message=f"Cannot convert 1C payroll month: {exc}",
                field_name="МесяцНачисления",
                raw_value=raw,
            )
        )
        return None


def _payroll_payment_period(
    source: dict[str, object], issues: list[MappingIssue]
) -> datetime:
    _, raw = _find(source, "ВыплатаЗПМесяц", "ВозвратВыплатыЗПМесяц")
    if raw is None:
        # Some 1C documents do not fill the dedicated month even though the
        # operation is a salary payment. Fall back to the document date.
        value = _period(source, issues)
        return value or datetime.now(timezone(timedelta(hours=5)))
    try:
        value = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).strip())
        return value if value.tzinfo else value.replace(tzinfo=timezone(timedelta(hours=5)))
    except (TypeError, ValueError) as exc:
        issues.append(
            MappingIssue(
                code="ONE_C_PERIOD_INVALID",
                message=f"Cannot convert 1C payroll payment month: {exc}",
                field_name="ВыплатаЗПМесяц",
                raw_value=raw,
            )
        )
        return datetime.now(timezone(timedelta(hours=5)))


def _is_payroll_payment_document(source: dict[str, object]) -> bool:
    operation = _normalize_key(_text_value(source, "ВидОперации") or "").replace("ё", "е")
    return "зарплат" in operation or "выплатазп" in operation


def _decimal_from_alias(
    source: dict[str, object], alias: str, issues: list[MappingIssue]
) -> Decimal:
    key, raw = _find(source, alias)
    if raw is None:
        return Decimal("0")
    value = _decimal_value(raw, key, issues)
    return value if value is not None else Decimal("0")


def _is_payroll_accrual(
    source: dict[str, object], issues: list[MappingIssue]
) -> bool:
    _, raw = _find(source, "RecordType", "ТипДвижения", "ВидДвижения")
    text = _normalize_key(raw or "").replace("ё", "е")
    if any(marker in text for marker in ("receipt", "приход")):
        return True
    if any(marker in text for marker in ("expense", "расход")):
        return False
    if _reference_value(source, "ДокументНачисления_Key"):
        return True
    issues.append(
        MappingIssue(
            code="ONE_C_PAYROLL_MOVEMENT_UNKNOWN",
            message="Personnel settlement movement is neither accrual nor payment",
            field_name="RecordType",
            raw_value=raw,
        )
    )
    return False


def _is_resolved_payroll_deduction(source: dict[str, object]) -> bool:
    """Return true only when the referenced 1C payroll type is unambiguous."""

    value = _text_value(
        source,
        "_ResolvedPayrollKind",
        "НачислениеУдержание",
        "ТипНачисленияУдержания",
        "ПлюсМинус",
    )
    text = _normalize_key(value or "").replace("ё", "е")
    return any(marker in text for marker in ("удержан", "вычет", "минус"))


def _decimal_value(
    raw: object, key: str | None, issues: list[MappingIssue]
) -> Decimal | None:
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


def _reference_value(source: dict[str, object], *aliases: str) -> str | None:
    _, value = _find(source, *aliases)
    text = str(value).strip() if value is not None else ""
    if not text or text == "00000000-0000-0000-0000-000000000000":
        return None
    return text


def _is_actual_patient_payment(source: dict[str, object]) -> bool:
    operation = _text_value(source, "ВидОперации")
    normalized = _normalize_key(operation or "").replace("ё", "е")
    exact_match = any(
        marker in normalized
        for marker in (
            "оплатаотпациента",
            "оплатаотклиента",
            "взносналицевойсчет",
            "возвратоплатыпациенту",
            "возвратоплатыклиенту",
            "возвратслицевогосчета",
        )
    )
    # 1C configurations expose the same enum with slightly different labels
    # (for example, "ОплатаПациентом" instead of
    # "ОплатаОтПациента"). Keep the rule semantic and
    # explicitly exclude insurance payments verified as a separate report row.
    semantic_match = (
        "пациент" in normalized
        and any(marker in normalized for marker in ("оплат", "взнос", "возврат"))
        and "страх" not in normalized
    )
    return exact_match or semantic_match


def _is_doctor_payment_operation(source: dict[str, object]) -> bool:
    """Return whether a payment breakdown row belongs to doctor revenue.

    Unlike the clinic cash-receipts KPI, the official doctor report includes
    insurance payments. Salary and supplier payment lines must stay excluded.
    """

    operation = _text_value(source, "ВидОперации")
    normalized = _normalize_key(operation or "").replace("ё", "е")
    exact_match = any(
        marker in normalized
        for marker in (
            "оплатаотпациента",
            "оплатапациентом",
            "оплатаотклиента",
            "взносналицевойсчет",
            "возвратоплатыпациенту",
            "возвратоплатыпациента",
            "возвратоплатыклиенту",
            "возвратслицевогосчета",
            "оплатаотстраховойкомпании",
        )
    )
    semantic_patient_match = (
        any(marker in normalized for marker in ("пациент", "клиент"))
        and any(marker in normalized for marker in ("оплат", "взнос", "возврат"))
    )
    insurance_match = "страх" in normalized and "оплат" in normalized
    return exact_match or semantic_patient_match or insurance_match


def one_c_finance_external_id(source_entity: str, source_record_id: str) -> str:
    """Return the canonical identity shared by normalization and rebuilds."""

    return "1c:" + sha256(
        f"{source_entity}|{source_record_id}".encode("utf-8")
    ).hexdigest()


def _expense_cost_behavior(category: str | None) -> str | None:
    text = _normalize_key(category or "").replace("ё", "е")
    if any(
        marker in text
        for marker in (
            "лаборатор",
            "материал",
            "медикамент",
            "расходн",
            "себестоим",
            "медицинскогоперсонала",
        )
    ):
        return "variable"
    if any(
        marker in text
        for marker in (
            "аренд",
            "реклам",
            "коммуналь",
            "бухгалтер",
            "юридическ",
            "офис",
            "ремонт",
            "обслуживаниеоборудования",
            "телефон",
            "интернет",
            "транспорт",
            "курьер",
            "корпоратив",
            "административ",
        )
    ):
        return "fixed"
    return None


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
