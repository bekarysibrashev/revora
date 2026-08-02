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
from app.modules.integrations.schemas import OneCPushRequest
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
        self.finished = None

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
        return SimpleNamespace(id=uuid4()), created

    async def finish_sync_run(self, run, **kwargs):
        self.finished = kwargs

    async def mark_connection_synced(self, connection, *, entity, synced_at):
        connection.status = "connected"
        connection.settings = {
            **connection.settings,
            "last_entity": entity,
            "last_synced_at": synced_at.isoformat(),
        }


class UnusedWriter:
    pass


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
    service = IntegrationService(repository, UnusedWriter())
    entity = "AccumulationRegister_Выручка_RecordType"
    payload = OneCPushRequest(
        entity=entity,
        records=[{"Recorder": "doc-1", "LineNumber": 1, "Сумма": 5000}],
    )

    first = await service.ingest_one_c_push(token, payload)
    second = await service.ingest_one_c_push(token, payload)

    assert first.records_stored == 1
    assert second.records_duplicate == 1
    assert repository.context == tenant_id
    assert repository.connection.status == "connected"


@pytest.mark.asyncio
async def test_push_rejects_an_entity_outside_allowlist() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    service = IntegrationService(
        FakeOneCRepository(tenant_id, connection_id, digest), UnusedWriter()
    )

    with pytest.raises(AppError) as error:
        await service.ingest_one_c_push(
            token,
            OneCPushRequest(entity="Catalog_Заявки", records=[{"Ref_Key": "pii"}]),
        )

    assert error.value.status_code == 403
