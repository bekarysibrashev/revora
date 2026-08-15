from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

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
from app.modules.integrations.service import IntegrationService


class FakeOneCRepository:
    def __init__(self, tenant_id, connection_id, digest):
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
                status="pending",
                source_entity=kwargs["source_entity"],
                source_record_id=kwargs["source_record_id"],
                payload=kwargs["payload"],
            )
            self.raw_records[kwargs["record_hash"]] = raw
        return raw, created

    async def single_active_branch_code(self, tenant_id):
        return "main"

    async def mark_raw_normalized(self, raw_record):
        raw_record.status = "normalized"

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
    def __init__(self):
        self.writes = []

    async def write(self, **kwargs):
        self.writes.append(kwargs)
        return uuid4()


def test_connector_token_round_trip_and_digest() -> None:
    tenant_id, connection_id = uuid4(), uuid4()

    token, digest = issue_connector_token(tenant_id, connection_id)
    parts = parse_connector_token(token)

    assert parts.tenant_id == tenant_id
    assert parts.connection_id == connection_id
    assert digest == connector_token_digest(token)
    assert token not in digest


def test_allowlist_excludes_patient_and_payment_documents() -> None:
    assert "Catalog_Заявки" not in SAFE_ONE_C_ENTITIES
    assert "Document_ПоступлениеДенежныхСредств" not in SAFE_ONE_C_ENTITIES
    assert "AccumulationRegister_Выручка_RecordType" in SAFE_ONE_C_ENTITIES


def test_source_record_id_is_stable_for_register_rows() -> None:
    record = {
        "Recorder": "doc-1",
        "Period": "2026-07-31T12:00:00",
        "LineNumber": 3,
        "Сумма": 1000,
    }

    assert source_record_id(record) == "doc-1|2026-07-31T12:00:00|3"


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
    assert repository.context == tenant_id
    assert repository.connection.status == "connected"


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
            OneCPushRequest(entity="Catalog_Заявки", records=[{"Ref_Key": "pii"}]),
        )

    assert error.value.status_code == 403


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
