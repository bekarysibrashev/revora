from app.modules.integrations.one_c_operational import (
    APPOINTMENT_ENTITY,
    LEAD_ENTITY,
    MARKETING_SPEND_ENTITY,
    PATIENT_ENTITY,
    SERVICE_ENTITY,
    normalize_one_c_operational_record,
)


def test_patient_mapping_accepts_only_local_phone_hash() -> None:
    result = normalize_one_c_operational_record(
        source_entity=PATIENT_ENTITY,
        source_record_id="patient-1",
        payload={
            "Ref_Key": "patient-1",
            "Description": "Пациент",
            "PhoneHash": "a" * 64,
            "КаналПривлеченияЗначение": "Instagram",
        },
        branch_code="main",
    )

    assert result is not None
    assert result.target_entity == "patient"
    assert result.data["phone_hash"] == "a" * 64
    assert "phone" not in result.data
    assert result.issues == []


def test_lead_mapping_normalizes_lost_status_and_utm_source() -> None:
    result = normalize_one_c_operational_record(
        source_entity=LEAD_ENTITY,
        source_record_id="lead-1",
        payload={
            "Ref_Key": "lead-1",
            "ДатаСоздания": "2026-08-01T10:00:00",
            "Статус": "Отказ клиента",
            "utm_source": "instagram",
            "ОсновнойКлиент_Key": "patient-1",
        },
        branch_code="main",
    )

    assert result is not None
    assert result.target_entity == "lead"
    assert result.data["status"] == "lost"
    assert result.data["source"] == "instagram"
    assert result.issues == []


def test_appointment_with_reception_is_completed() -> None:
    result = normalize_one_c_operational_record(
        source_entity=APPOINTMENT_ENTITY,
        source_record_id="appointment-1",
        payload={
            "Ref_Key": "appointment-1",
            "Date": "2026-08-02T09:30:00",
            "Контрагент_Key": "patient-1",
            "Врач_Key": "doctor-1",
            "СсылкаНаПрием_Key": "reception-1",
            "Статус": "Запланирован",
        },
        branch_code="main",
    )

    assert result is not None
    assert result.target_entity == "appointment"
    assert result.data["status"] == "completed"
    assert result.issues == []


def test_non_service_nomenclature_is_not_mapped_to_service_direction() -> None:
    result = normalize_one_c_operational_record(
        source_entity=SERVICE_ENTITY,
        source_record_id="stock-1",
        payload={"Ref_Key": "stock-1", "Description": "Перчатки", "ЭтоУслуга": False},
        branch_code="main",
    )

    assert result is None


def test_marketing_spend_maps_utm_dimensions_without_comment() -> None:
    result = normalize_one_c_operational_record(
        source_entity=MARKETING_SPEND_ENTITY,
        source_record_id="spend-1",
        payload={
            "Дата": "2026-08-03T00:00:00",
            "utmSource": "meta",
            "utmCampaign": "Implants",
            "Сумма": 12500,
        },
        branch_code="main",
    )

    assert result is not None
    assert result.target_entity == "marketing_spend_fact"
    assert result.data["campaign_name"] == "Implants"
    assert result.data["amount"] == 12500
    assert result.issues == []
