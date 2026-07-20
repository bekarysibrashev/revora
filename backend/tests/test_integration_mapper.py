from datetime import date
from decimal import Decimal

from app.modules.integrations.adapter import SourceRecord
from app.modules.integrations.mapper import CanonicalMapper, compute_record_hash
from app.modules.integrations.schemas import FieldMappingRule, MappingDefinition


def clinic_a_mapping() -> MappingDefinition:
    return MappingDefinition(
        source_entity="payments",
        target_entity="revenue_fact",
        fields={
            "patient_name": FieldMappingRule(
                source_fields=["Пациент"], required=True, transform="string"
            ),
            "doctor_name": FieldMappingRule(
                source_fields=["Врач"], required=True, transform="string"
            ),
            "amount": FieldMappingRule(
                source_fields=["Оплата"], required=True, transform="decimal"
            ),
            "occurred_on": FieldMappingRule(
                source_fields=["Дата"], required=True, transform="date"
            ),
        },
    )


def clinic_b_mapping() -> MappingDefinition:
    return MappingDefinition(
        source_entity="payments",
        target_entity="revenue_fact",
        fields={
            "patient_name": FieldMappingRule(
                source_fields=["Клиент"], required=True, transform="string"
            ),
            "doctor_name": FieldMappingRule(
                source_fields=["Доктор"], required=True, transform="string"
            ),
            "amount": FieldMappingRule(
                source_fields=["Сумма платежа"], required=True, transform="decimal"
            ),
            "occurred_on": FieldMappingRule(
                source_fields=["День операции"], required=True, transform="date"
            ),
        },
    )


def test_two_clinic_formats_normalize_to_one_canonical_shape() -> None:
    clinic_a = SourceRecord(
        source_entity="payments",
        payload={
            "Пациент": "Иванов",
            "Врач": "Ахметов",
            "Оплата": "50 000 ₸",
            "Дата": "10.07.2026",
        },
    )
    clinic_b = SourceRecord(
        source_entity="payments",
        payload={
            "Клиент": "Петров",
            "Доктор": "Садыкова",
            "Сумма платежа": 75000,
            "День операции": "2026-07-11",
        },
    )

    first = CanonicalMapper(clinic_a_mapping()).normalize(clinic_a)
    second = CanonicalMapper(clinic_b_mapping()).normalize(clinic_b)

    assert first.is_valid and second.is_valid
    assert first.target_entity == second.target_entity == "revenue_fact"
    assert first.data.keys() == second.data.keys()
    assert first.data["amount"] == Decimal("50000")
    assert second.data["amount"] == Decimal("75000")
    assert first.data["occurred_on"] == date(2026, 7, 10)
    assert second.data["occurred_on"] == date(2026, 7, 11)


def test_bad_source_row_is_quarantinable_with_specific_issues() -> None:
    record = SourceRecord(
        source_entity="payments",
        payload={
            "Клиент": "Сидоров",
            "Доктор": "",
            "Сумма платежа": "пятьдесят тысяч",
            "День операции": "вчера",
        },
    )

    result = CanonicalMapper(clinic_b_mapping()).normalize(record)

    assert not result.is_valid
    assert {issue.field_name for issue in result.issues} == {
        "doctor_name",
        "amount",
        "occurred_on",
    }
    assert {issue.code for issue in result.issues} == {
        "REQUIRED_FIELD_MISSING",
        "VALUE_TRANSFORM_FAILED",
    }
    assert result.data["patient_name"] == "Сидоров"


def test_record_hash_is_stable_and_detects_content_changes() -> None:
    first = {"Пациент": "Иванов", "Оплата": 50000}
    reordered = {"Оплата": 50000, "Пациент": "Иванов"}
    changed = {"Пациент": "Иванов", "Оплата": 60000}

    assert compute_record_hash("payments", first) == compute_record_hash(
        "payments", reordered
    )
    assert compute_record_hash("payments", first) != compute_record_hash(
        "payments", changed
    )


def test_mapping_rejects_a_different_source_entity() -> None:
    result = CanonicalMapper(clinic_a_mapping()).normalize(
        SourceRecord(source_entity="appointments", payload={})
    )

    assert not result.is_valid
    assert result.issues[0].code == "SOURCE_ENTITY_MISMATCH"
