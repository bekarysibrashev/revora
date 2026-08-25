"""Security and record identity helpers for the local 1C OData connector."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import secrets
from uuid import UUID


ONE_C_PROVIDER = "1c_odata_push"
CONNECTOR_TOKEN_PREFIX = "rvo1"

# The companion connector applies a per-entity $select allowlist. Patient phone
# numbers are transformed to a SHA-256 digest locally before a batch is sent.
SAFE_ONE_C_ENTITIES = (
    "AccumulationRegister_Выручка_RecordType",
    "AccumulationRegister_ДенежныеСредства_RecordType",
    "AccumulationRegister_Затраты_RecordType",
    "AccumulationRegister_НарядЗаказы_RecordType",
    "AccumulationRegister_Продажи_RecordType",
    "AccumulationRegister_ПродажиСебестоимость_RecordType",
    "AccumulationRegister_РабочееВремяСотрудников_RecordType",
    "AccumulationRegister_РасчетыСПерсоналом_RecordType",
    "Catalog_Контрагенты",
    "Catalog_Сотрудники",
    "Catalog_Сотрудники_СпецилазацииСотрудника",
    "Catalog_Специализации",
    "Catalog_Номенклатура",
    "Catalog_СтатьиДвиженияДенежныхСредств",
    "Catalog_СтатьиДоходовИРасходов",
    "Catalog_НачисленияИУдержанияСотрудников",
    "Catalog_СтруктурныеЕдиницы",
    "Catalog_Заявки",
    "Document_Событие",
    "Document_Событие_Услуги",
    "Document_ПланЛечения",
    "Document_НачислениеЗарплаты",
    "Document_НачислениеЗарплаты_РасчетЗарплаты",
    "InformationRegister_РекламныеРасходы",
)

SAFE_ONE_C_FIELDS: dict[str, frozenset[str]] = {
    "AccumulationRegister_Выручка_RecordType": frozenset(("Recorder", "Period", "LineNumber", "Active", "Касса_Key", "СтруктурнаяЕдиница_Key", "Организация_Key", "ТипДенежныхСредств", "ВидОперации", "Контрагент_Key", "Куратор_Key", "Сумма", "Recorder_Type")),
    "AccumulationRegister_ДенежныеСредства_RecordType": frozenset(("Recorder", "Period", "LineNumber", "Active", "RecordType", "СтруктурнаяЕдиница_Key", "ТипДенежныхСредств", "БанковскийСчетКасса", "Сумма", "СтатьяДДС_Key", "Recorder_Type")),
    "AccumulationRegister_Затраты_RecordType": frozenset(("Recorder", "Period", "LineNumber", "Active", "СтруктурнаяЕдиница_Key", "Номенклатура_Key", "Контрагент_Key", "Сотрудник_Key", "СтатьяЗатрат", "Сумма", "Recorder_Type", "СтатьяЗатрат_Type")),
    "AccumulationRegister_НарядЗаказы_RecordType": frozenset(("Recorder", "Period", "LineNumber", "Active", "RecordType", "СтруктурнаяЕдиница_Key", "Номенклатура_Key", "Контрагент_Key", "НарядЗаказ_Key", "НомерЗаказа", "Количество", "КлючСтроки", "Recorder_Type")),
    "AccumulationRegister_Продажи_RecordType": frozenset(("Recorder", "Period", "LineNumber", "Active", "СтруктурнаяЕдиница_Key", "Номенклатура_Key", "ДокументПродажи", "Сотрудник_Key", "Контрагент_Key", "Количество", "Стоимость", "СтоимостьБезСкидки", "СуммаНДС", "Recorder_Type", "ДокументПродажи_Type")),
    "AccumulationRegister_ПродажиСебестоимость_RecordType": frozenset(("Recorder", "Period", "LineNumber", "Active", "СтруктурнаяЕдиница_Key", "Номенклатура_Key", "Материал_Key", "ДокументПродажи", "Контрагент_Key", "Сотрудник_Key", "Количество", "Стоимость", "СуммаНДС", "Recorder_Type", "ДокументПродажи_Type")),
    "AccumulationRegister_РабочееВремяСотрудников_RecordType": frozenset(("Recorder_Key", "Period", "LineNumber", "Active", "СтруктурнаяЕдиница_Key", "Сотрудник_Key", "Врач_Key", "Дней", "Часов")),
    "AccumulationRegister_РасчетыСПерсоналом_RecordType": frozenset(("Recorder", "Period", "LineNumber", "Active", "RecordType", "СтруктурнаяЕдиница_Key", "Сотрудник_Key", "МесяцНачисления", "ДокументНачисления_Key", "Сумма", "Recorder_Type")),
    "Catalog_Контрагенты": frozenset(("Ref_Key", "Description", "DeletionMark", "ДатаРегистрации", "Имя", "Отчество", "Фамилия", "НаименованиеПолное", "ИсточникИнформации_Key", "КаналПривлечения_Key", "КаналПривлеченияЗначение", "СотрудникРегистрации_Key", "СтруктурнаяЕдиница_Key", "PhoneHash")),
    "Catalog_Сотрудники": frozenset(("Ref_Key", "Description", "DeletionMark", "Должность_Key", "Имя", "Отчество", "Фамилия", "НаименованиеСокращенное", "ПредставлениеДляОнлайнЗаписи", "Роль", "Служебный")),
    "Catalog_Сотрудники_СпецилазацииСотрудника": frozenset(("Ref_Key", "LineNumber", "Специализация_Key", "Основная")),
    "Catalog_Специализации": frozenset(("Ref_Key", "Description", "Code", "Parent_Key", "IsFolder", "DeletionMark")),
    "Catalog_Номенклатура": frozenset(("Ref_Key", "Description", "DeletionMark", "НаименованиеПолное", "Специализация_Key", "ТипНоменклатуры", "НормаВремени", "ЭтоУслуга", "ЭтоЗапас")),
    "Catalog_СтатьиДвиженияДенежныхСредств": frozenset(("Ref_Key", "Description", "Code", "Parent_Key", "IsFolder", "DeletionMark", "Описание")),
    "Catalog_СтатьиДоходовИРасходов": frozenset(("Ref_Key", "Description", "Code", "Parent_Key", "IsFolder", "DeletionMark", "ВидСтатьиДоходовИРасходов", "ВидРаспределенияРасходов")),
    "Catalog_НачисленияИУдержанияСотрудников": frozenset(("Ref_Key", "Description", "Code", "DeletionMark", "СтруктурнаяЕдиница_Key", "НачислениеУдержание", "ТипНачисленияУдержания", "ПлюсМинус", "ПолноеНаименование")),
    "Catalog_СтруктурныеЕдиницы": frozenset(("Ref_Key", "Description", "Code", "DeletionMark")),
    "Catalog_Заявки": frozenset(("Ref_Key", "DeletionMark", "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term", "ДатаОбработки", "ДатаСоздания", "КаналПривлечения_Key", "КаналПривлеченияЗначение", "PhoneHash", "ОсновнойКлиент_Key", "ОсновнойМенеджер_Key", "РекламныйИсточник_Key", "Статус", "СтатусПациента", "СтруктурнаяЕдиница_Key", "Направление_Key", "Категория_Key")),
    "Document_Событие": frozenset(("Ref_Key", "Number", "Date", "DeletionMark", "Posted", "Врач_Key", "ДатаОкончания", "ДатаСоздания", "ИсточникЗаписи_Key", "Контрагент_Key", "ПричинаОтмены_Key", "Сделка_Key", "СсылкаНаПрием_Key", "Статус", "СтатусПациента", "СтруктурнаяЕдиница_Key", "ТипСобытия")),
    "Document_Событие_Услуги": frozenset(("Ref_Key", "LineNumber", "ДатаНачала", "ДатаОкончания", "Номенклатура_Key", "НормаВремени", "Помещение_Key", "ПричинаЗаписи_Key", "Сотрудник_Key", "Цена")),
    "Document_ПланЛечения": frozenset(("Ref_Key", "Number", "Date", "DeletionMark", "Posted", "Контрагент_Key", "Куратор_Key", "Сотрудник_Key", "Статус", "СтруктурнаяЕдиница_Key", "СуммаДокумента", "СуммаОплачено")),
    "Document_НачислениеЗарплаты": frozenset(("Ref_Key", "Number", "Date", "DeletionMark", "Posted", "ДатаНачалаПериода", "ДатаОкончанияПериода", "Сотрудник_Key", "СтруктурнаяЕдиница_Key", "СуммаДокумента", "СтатьяРасходов_Key")),
    "Document_НачислениеЗарплаты_РасчетЗарплаты": frozenset(("Ref_Key", "LineNumber", "Сотрудник_Key", "Код", "НачислениеУдержание_Key", "ПериодС", "ПериодПо", "Сумма")),
    "InformationRegister_РекламныеРасходы": frozenset(("utmCampaign", "utmContent", "utmMedium", "utmSource", "utmTerm", "Дата", "Сумма")),
}


class InvalidConnectorToken(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectorTokenParts:
    tenant_id: UUID
    connection_id: UUID


def issue_connector_token(tenant_id: UUID, connection_id: UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    token = f"{CONNECTOR_TOKEN_PREFIX}.{tenant_id}.{connection_id}.{secret}"
    return token, connector_token_digest(token)


def parse_connector_token(token: str) -> ConnectorTokenParts:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != CONNECTOR_TOKEN_PREFIX or len(parts[3]) < 32:
        raise InvalidConnectorToken("Invalid 1C connector token")
    try:
        return ConnectorTokenParts(tenant_id=UUID(parts[1]), connection_id=UUID(parts[2]))
    except (ValueError, AttributeError) as exc:
        raise InvalidConnectorToken("Invalid 1C connector token") from exc


def connector_token_digest(token: str) -> str:
    return f"sha256:{sha256(token.encode('utf-8')).hexdigest()}"


def source_record_id(record: dict[str, object]) -> str:
    """Build a stable identity for OData catalog, document and register rows."""

    ref_key = record.get("Ref_Key")
    if ref_key:
        line_number = record.get("LineNumber")
        if line_number is not None:
            return f"{ref_key}|{line_number}"
        return str(ref_key)

    identity = [
        record.get("Recorder_Key") or record.get("Recorder"),
        record.get("Period"),
        record.get("LineNumber"),
    ]
    if any(value is not None for value in identity):
        return "|".join("" if value is None else str(value) for value in identity)

    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()
