from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.auth.models import User, UserRole
from app.modules.integrations.adapter import SourceRecord
from app.modules.integrations.schemas import FieldMappingRule, MappingDefinition
from app.modules.integrations.service import IntegrationService


class ListAdapter:
    def __init__(self, records):
        self.records = records

    async def fetch(self):
        for record in self.records:
            yield record


class FakeCanonicalWriter:
    SUPPORTED_TARGETS = {"patient"}

    def __init__(self):
        self.writes = []

    async def write(self, **kwargs):
        self.writes.append(kwargs)
        return uuid4()


class FakeIntegrationRepository:
    def __init__(self, tenant_id, connection_id, profile_id, definition):
        self.connection = SimpleNamespace(id=connection_id, tenant_id=tenant_id)
        self.profile = SimpleNamespace(
            id=profile_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            rules=definition.model_dump(mode="json"),
        )
        self.run = SimpleNamespace(id=uuid4())
        self.hashes = set()
        self.quarantined = []
        self.normalized = []
        self.finished = None
        self.profile_deactivated = False

    async def get_connection(self, tenant_id, connection_id):
        if tenant_id == self.connection.tenant_id and connection_id == self.connection.id:
            return self.connection
        return None

    async def get_mapping_profile(self, **kwargs):
        if kwargs["mapping_profile_id"] == self.profile.id:
            return self.profile
        return None

    async def create_sync_run(self, tenant_id, connection_id):
        return self.run

    async def store_raw_record(self, **kwargs):
        raw = SimpleNamespace(id=uuid4(), status="pending")
        if kwargs["record_hash"] in self.hashes:
            return raw, False
        self.hashes.add(kwargs["record_hash"])
        return raw, True

    async def quarantine(self, **kwargs):
        self.quarantined.append(kwargs)

    async def mark_normalized(self, **kwargs):
        self.normalized.append(kwargs)

    async def finish_sync_run(self, run, **kwargs):
        self.finished = kwargs

    async def deactivate_mapping_profile(self, *, tenant_id, connection_id, mapping_profile_id):
        if (
            tenant_id == self.profile.tenant_id
            and connection_id == self.profile.connection_id
            and mapping_profile_id == self.profile.id
        ):
            self.profile_deactivated = True
            return True
        return False


def make_owner(tenant_id):
    return User(
        id=uuid4(),
        tenant_id=tenant_id,
        email="owner@example.test",
        full_name="Owner",
        password_hash="unused",
        role=UserRole.OWNER,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_ingestion_normalizes_quarantines_and_skips_duplicates() -> None:
    tenant_id = uuid4()
    connection_id = uuid4()
    profile_id = uuid4()
    definition = MappingDefinition(
        source_entity="patients",
        target_entity="patient",
        fields={
            "external_id": FieldMappingRule(
                source_fields=["ID"], required=True, transform="string"
            ),
            "full_name": FieldMappingRule(
                source_fields=["Пациент"], required=True, transform="string"
            ),
        },
    )
    repository = FakeIntegrationRepository(
        tenant_id, connection_id, profile_id, definition
    )
    writer = FakeCanonicalWriter()
    service = IntegrationService(repository, writer)
    valid = SourceRecord(
        source_entity="patients", payload={"ID": "p-1", "Пациент": "Иванов"}
    )
    invalid = SourceRecord(
        source_entity="patients", payload={"ID": "p-2", "Пациент": ""}
    )

    result = await service.ingest(
        make_owner(tenant_id),
        connection_id=connection_id,
        mapping_profile_id=profile_id,
        adapter=ListAdapter([valid, invalid, valid]),
    )

    assert result.status == "completed_with_errors"
    assert result.records_read == 3
    assert result.records_normalized == 1
    assert result.records_quarantined == 1
    assert result.records_duplicate == 1
    assert writer.writes[0]["data"] == {"external_id": "p-1", "full_name": "Иванов"}
    assert repository.finished["records_written"] == 1


@pytest.mark.asyncio
async def test_delete_mapping_profile_deactivates_it() -> None:
    tenant_id, connection_id, profile_id = uuid4(), uuid4(), uuid4()
    definition = MappingDefinition(
        source_entity="patients",
        target_entity="patient",
        fields={"external_id": FieldMappingRule(source_fields=["ID"], transform="string")},
    )
    repository = FakeIntegrationRepository(tenant_id, connection_id, profile_id, definition)
    service = IntegrationService(repository, FakeCanonicalWriter())

    await service.delete_mapping_profile(make_owner(tenant_id), connection_id, profile_id)

    assert repository.profile_deactivated is True


@pytest.mark.asyncio
async def test_delete_mapping_profile_raises_when_not_found() -> None:
    from app.core.errors import AppError

    tenant_id, connection_id, profile_id = uuid4(), uuid4(), uuid4()
    definition = MappingDefinition(
        source_entity="patients",
        target_entity="patient",
        fields={"external_id": FieldMappingRule(source_fields=["ID"], transform="string")},
    )
    repository = FakeIntegrationRepository(tenant_id, connection_id, profile_id, definition)
    service = IntegrationService(repository, FakeCanonicalWriter())

    with pytest.raises(AppError):
        await service.delete_mapping_profile(make_owner(tenant_id), connection_id, uuid4())
