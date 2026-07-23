from datetime import date, datetime
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


def appointment_mapping() -> MappingDefinition:
    return MappingDefinition(
        source_entity="appointments_export",
        target_entity="appointment",
        fields={
            "starts_at": FieldMappingRule(
                source_fields=["Дата"],
                time_source_fields=["Начало"],
                required=True,
                transform="date_time_combine",
            ),
        },
    )


def test_date_time_combine_merges_a_timestamp_column_with_a_clock_column() -> None:
    # 1С often exports a full "Дата" timestamp (which is really the record's
    # creation time) alongside a separate "Начало"/"Окончание" clock-time
    # column for the actual appointment slot. We want the calendar date from
    # the first and the time-of-day from the second.
    record = SourceRecord(
        source_entity="appointments_export",
        payload={"Дата": "04.06.2026 15:32:21", "Начало": "15:27"},
    )

    result = CanonicalMapper(appointment_mapping()).normalize(record)

    assert result.is_valid
    assert result.data["starts_at"] == datetime(2026, 6, 4, 15, 27)


def test_date_time_combine_accepts_a_plain_date_source_column() -> None:
    record = SourceRecord(
        source_entity="appointments_export",
        payload={"Дата": "04.06.2026", "Начало": "09:05:00"},
    )

    result = CanonicalMapper(appointment_mapping()).normalize(record)

    assert result.is_valid
    assert result.data["starts_at"] == datetime(2026, 6, 4, 9, 5)


def test_date_time_combine_falls_back_to_midnight_when_time_column_missing() -> None:
    record = SourceRecord(
        source_entity="appointments_export",
        payload={"Дата": "04.06.2026"},
    )

    result = CanonicalMapper(appointment_mapping()).normalize(record)

    assert result.is_valid
    assert result.data["starts_at"] == datetime(2026, 6, 4, 0, 0)


def test_date_time_combine_reports_an_unparseable_time_value() -> None:
    record = SourceRecord(
        source_entity="appointments_export",
        payload={"Дата": "04.06.2026", "Начало": "не время"},
    )

    result = CanonicalMapper(appointment_mapping()).normalize(record)

    assert not result.is_valid
    assert result.issues[0].code == "VALUE_TRANSFORM_FAILED"
    assert result.issues[0].field_name == "starts_at"


def test_required_field_with_a_non_blank_default_is_not_flagged_as_missing() -> None:
    # Used to fake a "constant" mapping value (e.g. recognition_type =
    # "accrual" for every row) by pointing source_fields at a column name
    # that never appears in the file, so the default always applies.
    definition = MappingDefinition(
        source_entity="payments",
        target_entity="revenue_fact",
        fields={
            "recognition_type": FieldMappingRule(
                source_fields=["__never_present__"],
                required=True,
                transform="string",
                default="accrual",
            ),
        },
    )
    record = SourceRecord(source_entity="payments", payload={"Пациент": "Иванов"})

    result = CanonicalMapper(definition).normalize(record)

    assert result.is_valid
    assert result.data["recognition_type"] == "accrual"
