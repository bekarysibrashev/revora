"""Strict mappings for the approved non-clinical 1C Stoma entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256

from app.modules.integrations.schemas import MappingIssue


PATIENT_ENTITY = "Catalog_Контрагенты"
EMPLOYEE_ENTITY = "Catalog_Сотрудники"
SERVICE_ENTITY = "Catalog_Номенклатура"
LEAD_ENTITY = "Catalog_Заявки"
APPOINTMENT_ENTITY = "Document_Событие"
TREATMENT_PLAN_ENTITY = "Document_ПланЛечения"
MARKETING_SPEND_ENTITY = "InformationRegister_РекламныеРасходы"

MAPPABLE_OPERATIONAL_ENTITIES = (
    PATIENT_ENTITY,
    EMPLOYEE_ENTITY,
    SERVICE_ENTITY,
    LEAD_ENTITY,
    APPOINTMENT_ENTITY,
    TREATMENT_PLAN_ENTITY,
    MARKETING_SPEND_ENTITY,
)


@dataclass(frozen=True, slots=True)
class OneCOperationalMapping:
    target_entity: str
    data: dict[str, object]
    issues: list[MappingIssue]


def normalize_one_c_operational_record(
    *, source_entity: str, source_record_id: str, payload: dict[str, object], branch_code: str | None
) -> OneCOperationalMapping | None:
    if source_entity not in MAPPABLE_OPERATIONAL_ENTITIES:
        return None
    issues: list[MappingIssue] = []
    external_id = _text(payload.get("Ref_Key")) or source_record_id

    if source_entity == PATIENT_ENTITY:
        full_name = _text(payload.get("Description"))
        if not full_name:
            issues.append(_missing("Description", "Patient name is missing"))
        phone_hash = _text(payload.get("PhoneHash"))
        if phone_hash and (len(phone_hash) != 64 or any(c not in "0123456789abcdef" for c in phone_hash.lower())):
            issues.append(_missing("PhoneHash", "Locally protected phone hash is invalid"))
        return OneCOperationalMapping("patient", {
            "external_id": external_id,
            "full_name": full_name,
            "phone_hash": phone_hash,
            "lead_source": _first_text(payload, "КаналПривлеченияЗначение", "ИсточникИнформации_Key", "КаналПривлечения_Key"),
        }, issues)

    if source_entity == EMPLOYEE_ENTITY:
        full_name = _text(payload.get("Description")) or " ".join(filter(None, (
            _text(payload.get("Фамилия")), _text(payload.get("Имя")), _text(payload.get("Отчество"))
        )))
        if not full_name:
            issues.append(_missing("Description", "Employee name is missing"))
        return OneCOperationalMapping("doctor", {
            "external_id": external_id,
            "full_name": full_name,
            "specialty": _first_text(payload, "Роль", "НаименованиеСокращенное"),
        }, issues)

    if source_entity == SERVICE_ENTITY:
        if payload.get("ЭтоУслуга") is not True:
            return None
        name = _first_text(payload, "НаименованиеПолное", "Description")
        if not name:
            issues.append(_missing("Description", "Service name is missing"))
        return OneCOperationalMapping("service_direction", {
            "external_id": external_id, "name": name,
        }, issues)

    if source_entity == LEAD_ENTITY:
        created_at = _datetime(payload.get("ДатаСоздания"), "ДатаСоздания", issues)
        if not branch_code:
            issues.append(_missing("branch_code", "A single/default Revora branch is required for 1C leads"))
        return OneCOperationalMapping("lead", {
            "external_id": external_id,
            "branch_code": branch_code,
            "patient_external_id": _guid(payload.get("ОсновнойКлиент_Key")),
            "source": _first_text(payload, "utm_source", "КаналПривлеченияЗначение", "РекламныйИсточник_Key") or "1c",
            "status": _lead_status(payload.get("Статус")),
            "created_at": created_at,
        }, issues)

    if source_entity == APPOINTMENT_ENTITY:
        starts_at = _datetime(payload.get("Date"), "Date", issues)
        patient_id = _guid(payload.get("Контрагент_Key"))
        if not patient_id:
            issues.append(_missing("Контрагент_Key", "Appointment has no patient"))
        if not branch_code:
            issues.append(_missing("branch_code", "A single/default Revora branch is required for appointments"))
        return OneCOperationalMapping("appointment", {
            "external_id": external_id,
            "branch_code": branch_code,
            "patient_external_id": patient_id,
            "doctor_external_id": _guid(payload.get("Врач_Key")),
            "starts_at": starts_at,
            "status": _appointment_status(
                payload.get("Статус"),
                payload.get("СсылкаНаПрием_Key"),
                bool(payload.get("DeletionMark")),
            ),
            "is_primary": _is_primary_patient_status(payload.get("СтатусПациента")),
        }, issues)

    if source_entity == TREATMENT_PLAN_ENTITY:
        patient_id = _guid(payload.get("Контрагент_Key"))
        if not patient_id:
            issues.append(_missing("Контрагент_Key", "Treatment plan has no patient"))
        status = _text(payload.get("Статус")) or "unknown"
        return OneCOperationalMapping("treatment_plan", {
            "external_id": external_id,
            "patient_external_id": patient_id,
            "status": status,
            "accepted_at": _datetime(payload.get("Date"), "Date", issues) if _is_positive_status(status) else None,
        }, issues)

    spend_date = _datetime(payload.get("Дата"), "Дата", issues)
    amount = payload.get("Сумма")
    if amount is None:
        issues.append(_missing("Сумма", "Marketing spend amount is missing"))
    source = _first_text(payload, "utmSource", "utmMedium") or "1c"
    identity = "|".join(str(payload.get(key) or "") for key in (
        "Дата", "utmSource", "utmMedium", "utmCampaign", "utmContent", "utmTerm"
    ))
    return OneCOperationalMapping("marketing_spend_fact", {
        "external_id": "1c:" + sha256(identity.encode("utf-8")).hexdigest(),
        "branch_code": branch_code,
        "source": source[:50],
        "campaign_name": _text(payload.get("utmCampaign")),
        "spend_date": spend_date.date() if spend_date else None,
        "amount": amount,
        "currency": "KZT",
    }, issues)


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _first_text(payload: dict[str, object], *fields: str) -> str | None:
    for field in fields:
        value = _text(payload.get(field))
        if value and value != "00000000-0000-0000-0000-000000000000":
            return value
    return None


def _guid(value: object) -> str | None:
    result = _text(value)
    return None if not result or result == "00000000-0000-0000-0000-000000000000" else result


def _datetime(value: object, field: str, issues: list[MappingIssue]) -> datetime | None:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return result if result.tzinfo else result.replace(tzinfo=timezone(timedelta(hours=5)))
    except (TypeError, ValueError):
        issues.append(_missing(field, f"{field} is not a valid date"))
        return None


def _missing(field: str, message: str) -> MappingIssue:
    return MappingIssue(code="ONE_C_OPERATIONAL_FIELD_INVALID", message=message, field_name=field)


def _lead_status(value: object) -> str:
    text = (_text(value) or "").casefold().replace("ё", "е")
    if any(marker in text for marker in ("успеш", "выигран", "конверт", "реализован")):
        return "won"
    if any(marker in text for marker in ("потер", "отказ", "неуспеш", "закрыт")):
        return "lost"
    return "new"


def _appointment_status(value: object, reception_key: object, deleted: bool = False) -> str:
    if deleted:
        return "deleted"
    text = (_text(value) or "").casefold().replace("ё", "е")
    # This check must precede the generic "состоял" marker. Otherwise the
    # literal 1C status "Прием не состоялся" is incorrectly counted as done.
    if any(marker in text for marker in ("не состоял", "не приш", "неяв", "no_show")):
        return "no_show"
    if any(marker in text for marker in ("отмен", "аннулир")):
        return "cancelled"
    if _guid(reception_key):
        return "completed"
    if any(marker in text for marker in ("окончен", "заверш", "выполн", "состоял", "пришел")):
        return "completed"
    return "scheduled"


def _is_primary_patient_status(value: object) -> bool:
    text = (_text(value) or "").casefold().replace("ё", "е")
    return "первич" in text


def _is_positive_status(value: str) -> bool:
    text = value.casefold().replace("ё", "е")
    return any(marker in text for marker in ("принят", "согласован", "выполн", "заверш"))
