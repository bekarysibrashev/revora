from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.modules.integrations.one_c import (
    SAFE_ONE_C_ENTITIES,
    connector_token_digest,
    issue_connector_token,
    parse_connector_token,
    source_record_id,
)
from app.modules.integrations.schemas import (
    OneCMetadataRequest,
    OneCNormalizeRequest,
    OneCPushRequest,
)
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.service import EXCLUDED_BRANCH_CODE, IntegrationService


class _FakeNestedTransaction:
    """Mirrors AsyncSession.begin_nested(): a no-op SAVEPOINT for fakes that
    do not talk to a real database. An exception inside the block still
    propagates, matching how a real SAVEPOINT rolls back and re-raises."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def begin_nested(self):
        return _FakeNestedTransaction()


class FakeOneCRepository:
    def __init__(self, tenant_id, connection_id, digest):
        self.session = _FakeSession()
        self.connection = SimpleNamespace(
            id=connection_id,
            tenant_id=tenant_id,
            provider="1c_odata_push",
            encrypted_credentials=digest,
            settings={"allowed_entities": list(SAFE_ONE_C_ENTITIES)},
            status="awaiting_data",
        )
        self.context = None
        self.hashes = set()
        self.raw_records = {}
        self.finished = None
        self.quarantined = []
        self.metadata = None
        self.reset_count = 0
        self.removed_canonical = []

    async def set_tenant_context(self, tenant_id):
        self.context = tenant_id

    async def get_connection(self, tenant_id, connection_id):
        if tenant_id == self.connection.tenant_id and connection_id == self.connection.id:
            return self.connection
        return None

    async def create_sync_run(self, tenant_id, connection_id):
        return SimpleNamespace(id=uuid4())

    async def store_raw_record(self, **kwargs):
        created = kwargs["record_hash"] not in self.hashes
        self.hashes.add(kwargs["record_hash"])
        raw = self.raw_records.get(kwargs["record_hash"])
        if raw is None:
            raw = SimpleNamespace(
                id=uuid4(),
                connection_id=kwargs["connection_id"],
                status="pending",
                source_entity=kwargs["source_entity"],
                source_record_id=kwargs["source_record_id"],
                payload=kwargs["payload"],
            )
            self.raw_records[kwargs["record_hash"]] = raw
        return raw, created

    async def single_active_branch_code(self, tenant_id):
        return "main"

    async def one_c_branch_code_map(self, tenant_id, connection_id):
        return {}

    async def one_c_payroll_document_payload(self, tenant_id, connection_id, ref_key):
        for raw in self.raw_records.values():
            if (
                raw.connection_id == connection_id
                and raw.source_entity == "Document_НачислениеЗарплаты"
                and raw.source_record_id == ref_key
            ):
                return dict(raw.payload)
        return None

    async def mark_raw_normalized(self, raw_record):
        raw_record.status = "normalized"

    async def remove_one_c_canonical_record(self, **kwargs):
        self.removed_canonical.append(kwargs)

    async def quarantine(self, **kwargs):
        kwargs["raw_record"].status = "quarantined"
        self.quarantined.append(kwargs)

    async def pending_one_c_records(self, *, source_entities, period_from, limit, **kwargs):
        return [
            row
            for row in self.raw_records.values()
            if row.status == "pending"
            and row.source_entity in source_entities
            and datetime.fromisoformat(str(row.payload["Period"])).replace(tzinfo=UTC)
            >= period_from
        ][:limit]

    async def pending_one_c_record_count(self, *, source_entities, period_from, **kwargs):
        return len(
            await self.pending_one_c_records(
                source_entities=source_entities,
                period_from=period_from,
                limit=100_000,
            )
        )

    async def reset_one_c_records_for_reprocessing(self, **kwargs):
        reset = 0
        for row in self.raw_records.values():
            if row.status in {"normalized", "quarantined"}:
                row.status = "pending"
                reset += 1
        self.reset_count += reset
        return reset

    async def finish_sync_run(self, run, **kwargs):
        self.finished = kwargs

    async def mark_connection_synced(self, connection, *, entity, synced_at):
        connection.status = "connected"
        connection.settings = {
            **connection.settings,
            "last_entity": entity,
            "last_synced_at": synced_at.isoformat(),
        }

    async def upsert_one_c_metadata(self, **kwargs):
        self.metadata = SimpleNamespace(**kwargs)
        return self.metadata

    async def get_one_c_metadata(self, tenant_id, connection_id):
        if (
            self.metadata is not None
            and tenant_id == self.connection.tenant_id
            and connection_id == self.connection.id
        ):
            return self.metadata
        return None


class FakeOneCWriter:
    def __init__(self, fail_at_call_index: int | None = None):
        self.writes = []
        self._fail_at = fail_at_call_index
        self._calls = 0

    async def write(self, **kwargs):
        index = self._calls
        self._calls += 1
        if self._fail_at is not None and index == self._fail_at:
            # Simulates a raw database error (for example a value that does
            # not fit the target column) rather than a CanonicalWriteError.
            raise SQLAlchemyError("simulated PostgreSQL numeric overflow")
        self.writes.append(kwargs)
        return uuid4()


def test_reprocess_keeps_only_latest_raw_version_per_one_c_identity() -> None:
    older = SimpleNamespace(
        id=uuid4(),
        source_entity="AccumulationRegister_Выручка_RecordType",
        source_record_id="document|2026-07-01|1",
        record_hash="old",
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    newer = SimpleNamespace(
        id=uuid4(),
        source_entity=older.source_entity,
        source_record_id=older.source_record_id,
        record_hash="new",
        received_at=datetime(2026, 8, 2, tzinfo=UTC),
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    independent = SimpleNamespace(
        id=uuid4(),
        source_entity=older.source_entity,
        source_record_id="document|2026-07-01|2",
        record_hash="other",
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    latest, superseded = IntegrationRepository._latest_one_c_record_versions(
        [older, newer, independent]
    )

    assert set(latest) == {newer.id, independent.id}
    assert superseded == [older.id]


def test_connector_token_round_trip_and_digest() -> None:
    tenant_id, connection_id = uuid4(), uuid4()

    token, digest = issue_connector_token(tenant_id, connection_id)
    parts = parse_connector_token(token)

    assert parts.tenant_id == tenant_id
    assert parts.connection_id == connection_id
    assert digest == connector_token_digest(token)
    assert token not in digest


def test_allowlist_includes_only_field_protected_operational_sources() -> None:
    assert "Catalog_Заявки" in SAFE_ONE_C_ENTITIES
    assert "Catalog_Контрагенты" in SAFE_ONE_C_ENTITIES
    assert "Document_ПоступлениеДенежныхСредств" in SAFE_ONE_C_ENTITIES
    assert "Document_СписаниеДенежныхСредств_Затраты" in SAFE_ONE_C_ENTITIES
    assert "AccumulationRegister_Выручка_RecordType" in SAFE_ONE_C_ENTITIES
    assert "Catalog_СтруктурныеЕдиницы" in SAFE_ONE_C_ENTITIES
    assert "Document_НачислениеЗарплаты_РасчетЗарплаты" in SAFE_ONE_C_ENTITIES


def test_structural_unit_mapping_overrides_default_branch() -> None:
    payload = {"СтруктурнаяЕдиница_Key": "UNIT-SEIFULLINA"}

    assert IntegrationService._one_c_record_branch_code(
        payload, {"unit-seifullina": "seifullina"}, "default"
    ) == "seifullina"


def test_unknown_structural_unit_never_falls_back_to_default_branch() -> None:
    payload = {"СтруктурнаяЕдиница_Key": "UNKNOWN-UNIT"}

    assert IntegrationService._one_c_record_branch_code(
        payload, {"known-unit": "batys-mura"}, "default"
    ) == EXCLUDED_BRANCH_CODE


def test_record_without_structural_unit_can_use_single_branch_fallback() -> None:
    assert IntegrationService._one_c_record_branch_code({}, {}, "main") == "main"


def test_cyrillic_structural_units_match_latin_branch_codes() -> None:
    assert IntegrationRepository._branch_matches_unit(
        IntegrationRepository._normalize_branch_name("SAN (Сейфуллина)"),
        branch_name="seifullina",
        branch_code="seifullina",
    )
    assert IntegrationRepository._branch_matches_unit(
        IntegrationRepository._normalize_branch_name("SAN (Батыс Мура)"),
        branch_name="batysmura",
        branch_code="batysmura",
    )


def test_unrelated_structural_unit_is_not_mapped() -> None:
    assert not IntegrationRepository._branch_matches_unit(
        IntegrationRepository._normalize_branch_name("ИП Dent.Co"),
        branch_name="seifullina",
        branch_code="seifullina",
    )


def test_source_record_id_is_stable_for_register_rows() -> None:
    record = {
        "Recorder": "doc-1",
        "Period": "2026-07-31T12:00:00",
        "LineNumber": 3,
        "Сумма": 1000,
    }

    assert source_record_id(record) == "doc-1|2026-07-31T12:00:00|3"


def test_source_record_id_keeps_each_document_table_line() -> None:
    assert source_record_id({"Ref_Key": "payroll-1", "LineNumber": 7}) == "payroll-1|7"


@pytest.mark.asyncio
async def test_push_stores_allowed_records_and_deduplicates() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    writer = FakeOneCWriter()
    service = IntegrationService(repository, writer)
    entity = "AccumulationRegister_Выручка_RecordType"
    payload = OneCPushRequest(
        entity=entity,
        records=[{
            "Recorder": "doc-1",
            "LineNumber": 1,
            "Period": "2026-07-31T12:00:00",
            "Сумма": 5000,
        }],
    )

    first = await service.ingest_one_c_push(token, payload)
    second = await service.ingest_one_c_push(token, payload)

    assert first.records_stored == 1
    assert second.records_duplicate == 1
    assert first.records_normalized == 1
    assert second.records_normalized == 0
    assert len(writer.writes) == 1
    assert repository.removed_canonical == [
        {
            "tenant_id": tenant_id,
            "source_entity": entity,
            "source_record_id": "doc-1|2026-07-31T12:00:00|1",
        }
    ]
    assert repository.context == tenant_id
    assert repository.connection.status == "connected"


@pytest.mark.asyncio
async def test_push_isolates_a_bad_record_instead_of_failing_the_whole_batch() -> None:
    """A raw database error on one record (e.g. an amount PostgreSQL's
    Numeric column rejects) must not abort the whole batch. Before the
    SAVEPOINT fix, this raised out of ingest_one_c_push entirely and every
    other record in the same request -- good or bad -- was lost with it."""

    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    writer = FakeOneCWriter(fail_at_call_index=1)  # the middle 'doc-bad' record
    service = IntegrationService(repository, writer)
    entity = "AccumulationRegister_Выручка_RecordType"
    payload = OneCPushRequest(
        entity=entity,
        records=[
            {"Recorder": "doc-1", "LineNumber": 1, "Period": "2026-07-31T12:00:00", "Сумма": 1000},
            {"Recorder": "doc-bad", "LineNumber": 1, "Period": "2026-07-31T12:00:00", "Сумма": 2000},
            {"Recorder": "doc-3", "LineNumber": 1, "Period": "2026-07-31T12:00:00", "Сумма": 3000},
        ],
    )

    result = await service.ingest_one_c_push(token, payload)

    assert result.records_stored == 3
    assert result.records_normalized == 2
    assert result.records_quarantined == 1
    assert len(writer.writes) == 2
    assert len(repository.quarantined) == 1
    assert repository.quarantined[0]["issues"][0].code == "ONE_C_CANONICAL_WRITE_FAILED"


@pytest.mark.asyncio
async def test_push_removes_postgres_unsupported_null_characters() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    service = IntegrationService(repository, FakeOneCWriter())

    result = await service.ingest_one_c_push(
        token,
        OneCPushRequest(
            entity="Catalog_Специализации",
            records=[{
                "Ref_Key": "specialty-null-char",
                "Description": "Ортодонт\x00",
                "DeletionMark": False,
            }],
        ),
    )

    assert result.records_stored == 1
    stored = next(iter(repository.raw_records.values()))
    assert stored.payload["Description"] == "Ортодонт"


@pytest.mark.asyncio
async def test_existing_connector_token_uses_current_server_allowlist() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    repository.connection.settings["allowed_entities"] = [
        "AccumulationRegister_Выручка_RecordType"
    ]
    service = IntegrationService(repository, FakeOneCWriter())

    result = await service.ingest_one_c_push(
        token,
        OneCPushRequest(
            entity="Catalog_Специализации",
            records=[{
                "Ref_Key": "specialty-1",
                "Description": "Ортодонт",
                "DeletionMark": False,
            }],
        ),
    )

    assert result.status == "completed"
    assert result.records_stored == 1


@pytest.mark.asyncio
async def test_payroll_expense_line_inherits_parent_period_and_branch_context() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    writer = FakeOneCWriter()
    service = IntegrationService(repository, writer)

    await service.ingest_one_c_push(
        token,
        OneCPushRequest(
            entity="Document_НачислениеЗарплаты",
            records=[{
                "Ref_Key": "payroll-1",
                "Date": "2026-08-05T10:00:00",
                "Posted": True,
                "ДатаОкончанияПериода": "2026-07-31T23:59:59",
                "СуммаДокумента": 700000,
            }],
        ),
    )
    result = await service.ingest_one_c_push(
        token,
        OneCPushRequest(
            entity="Document_НачислениеЗарплаты_Затраты",
            records=[{
                "Ref_Key": "payroll-1",
                "LineNumber": 1,
                "Сотрудник_Key": "employee-1",
                "Дата": "2026-07-31T23:59:59",
                "Сумма": 481048.99,
            }],
        ),
    )

    assert result.records_normalized == 1
    assert writer.writes[-1]["target_entity"] == "payroll_fact"
    assert str(writer.writes[-1]["data"]["amount"]) == "481048.99"
    assert writer.writes[-1]["data"]["occurred_on"].isoformat() == "2026-07-31"


@pytest.mark.asyncio
async def test_push_rejects_an_entity_outside_allowlist() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    service = IntegrationService(
        FakeOneCRepository(tenant_id, connection_id, digest), FakeOneCWriter()
    )

    with pytest.raises(AppError) as error:
        await service.ingest_one_c_push(
            token,
            OneCPushRequest(
                entity="Document_НеРазрешен",
                records=[{"Ref_Key": "not-approved"}],
            ),
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_server_rejects_raw_patient_phone_even_for_approved_entity() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    service = IntegrationService(
        FakeOneCRepository(tenant_id, connection_id, digest), FakeOneCWriter()
    )

    with pytest.raises(AppError) as error:
        await service.ingest_one_c_push(
            token,
            OneCPushRequest(
                entity="Catalog_Контрагенты",
                records=[{
                    "Ref_Key": "patient-1",
                    "Description": "Пациент",
                    "Телефон": "+7 700 000 00 00",
                }],
            ),
        )

    assert error.value.status_code == 422
    assert error.value.code == "ONE_C_FIELDS_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_connector_can_upload_schema_without_patient_rows() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    service = IntegrationService(repository, FakeOneCWriter())

    result = await service.ingest_one_c_metadata(
        token,
        OneCMetadataRequest(
            entities=[
                {
                    "name": "Catalog_Patients",
                    "entity_type": "StandardODATA.Catalog_Patients",
                    "properties": [
                        {"name": "Ref_Key", "type": "Edm.Guid", "nullable": False},
                        {"name": "Description", "type": "Edm.String", "nullable": True},
                    ],
                }
            ]
        ),
    )

    assert result.entity_count == 1
    assert result.property_count == 2
    assert len(result.fingerprint) == 64
    assert repository.metadata.entities[0]["name"] == "Catalog_Patients"
    assert "records" not in repository.metadata.entities[0]
    assert repository.connection.settings["allowed_entities"] == ["Catalog_Patients"]


@pytest.mark.asyncio
async def test_metadata_declared_entity_and_fields_are_accepted_dynamically() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    service = IntegrationService(repository, FakeOneCWriter())
    await service.ingest_one_c_metadata(
        token,
        OneCMetadataRequest(
            entities=[
                {
                    "name": "InformationRegister_НовыйОтчет",
                    "entity_type": "StandardODATA.InformationRegister_НовыйОтчет",
                    "properties": [
                        {"name": "Period", "type": "Edm.DateTime", "nullable": False},
                        {"name": "НовыйПоказатель", "type": "Edm.Decimal", "nullable": True},
                    ],
                }
            ]
        ),
    )

    result = await service.ingest_one_c_push(
        token,
        OneCPushRequest(
            entity="InformationRegister_НовыйОтчет",
            records=[{"Period": "2026-07-31T00:00:00", "НовыйПоказатель": 42}],
        ),
    )

    assert result.records_stored == 1
    assert result.records_normalized == 0
    assert next(iter(repository.raw_records.values())).status == "normalized"


@pytest.mark.asyncio
async def test_dynamic_entity_rejects_field_missing_from_metadata() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    service = IntegrationService(repository, FakeOneCWriter())
    await service.ingest_one_c_metadata(
        token,
        OneCMetadataRequest(
            entities=[
                {
                    "name": "Catalog_Новый",
                    "entity_type": "StandardODATA.Catalog_Новый",
                    "properties": [
                        {"name": "Ref_Key", "type": "Edm.Guid", "nullable": False}
                    ],
                }
            ]
        ),
    )

    with pytest.raises(AppError) as error:
        await service.ingest_one_c_push(
            token,
            OneCPushRequest(
                entity="Catalog_Новый",
                records=[{"Ref_Key": "row-1", "НесуществующееПоле": 1}],
            ),
        )

    assert error.value.code == "ONE_C_FIELDS_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_existing_pending_rows_can_be_backfilled_into_canonical_tables() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    _, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    writer = FakeOneCWriter()
    service = IntegrationService(repository, writer)
    entity = "AccumulationRegister_Выручка_RecordType"
    raw = SimpleNamespace(
        id=uuid4(),
        status="pending",
        source_entity=entity,
        source_record_id="doc-old|1",
        payload={"Period": datetime.now(UTC).isoformat(), "Сумма": 7500},
    )
    repository.raw_records["old"] = raw
    user = SimpleNamespace(tenant_id=tenant_id, role="owner")

    result = await service.normalize_existing_one_c_records(
        user,
        connection_id,
        OneCNormalizeRequest(history_days=90, batch_size=200),
    )

    assert result.processed == 1
    assert result.normalized == 1
    assert result.remaining == 0
    assert raw.status == "normalized"
    assert writer.writes[0]["target_entity"] == "revenue_fact"


@pytest.mark.asyncio
async def test_existing_normalized_rows_can_be_reset_for_new_rules() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    _, digest = issue_connector_token(tenant_id, connection_id)
    repository = FakeOneCRepository(tenant_id, connection_id, digest)
    writer = FakeOneCWriter()
    service = IntegrationService(repository, writer)
    raw = SimpleNamespace(
        id=uuid4(),
        status="normalized",
        source_entity="AccumulationRegister_Выручка_RecordType",
        source_record_id="payment-old|1",
        payload={
            "Period": datetime.now(UTC).isoformat(),
            "Сумма": 5000,
            "ВидОперации": "Оплата от пациента",
        },
    )
    repository.raw_records["old-normalized"] = raw
    user = SimpleNamespace(tenant_id=tenant_id, role="owner")

    result = await service.normalize_existing_one_c_records(
        user,
        connection_id,
        OneCNormalizeRequest(history_days=90, batch_size=200, reset_existing=True),
    )

    assert result.reset == 1
    assert result.normalized == 1
    assert raw.status == "normalized"
