from hashlib import sha256
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.security import normalize_phone_e164, phone_hash, phone_hash_candidates
from app.core.config import Settings
from app.modules.contacts.service import ContactRegistry, ContactService
from app.modules.whatsapp.security import decrypt_contact


def test_kazakhstan_phone_formats_share_one_hash() -> None:
    values = ("+7 701 234 56 78", "87012345678", "7012345678", "77012345678")

    assert {normalize_phone_e164(value) for value in values} == {"+77012345678"}
    assert len({phone_hash(value) for value in values}) == 1


def test_legacy_provider_hashes_are_candidates() -> None:
    candidates = phone_hash_candidates("+7 701 234 56 78")

    assert phone_hash("87012345678") in candidates
    assert sha256("77012345678".encode()).hexdigest() in candidates
    assert sha256("87012345678".encode()).hexdigest() in candidates


class FakeContactRepository:
    def __init__(self, *, patient: bool = False, prior=None) -> None:
        self.patient = patient
        self.prior = prior or (None, None)
        self.items = {}

    async def identity(self, tenant_id, digest, *, lock=False):
        return self.items.get((tenant_id, digest))

    async def is_patient(self, tenant_id, candidates):
        return self.patient

    async def prior_inbound(self, tenant_id, candidates):
        return self.prior

    async def add_if_missing(self, item):
        key = (item.tenant_id, item.phone_hash)
        if key in self.items:
            return None
        self.items[key] = item
        return item


@pytest.mark.asyncio
async def test_registry_deduplicates_channels_and_keeps_first_source() -> None:
    repository = FakeContactRepository()
    registry = ContactRegistry(repository)
    tenant_id = uuid4()
    first = datetime(2026, 8, 27, 9, tzinfo=UTC)

    item = await registry.register_inbound(
        tenant_id=tenant_id, phone="87012345678", source="kcell", occurred_at=first
    )
    repeated = await registry.register_inbound(
        tenant_id=tenant_id,
        phone="+7 701 234 56 78",
        source="whatsapp",
        occurred_at=first + timedelta(hours=1),
    )

    assert repeated is item
    assert item.first_inbound_source == "kcell"
    assert item.inbound_count == 2
    assert item.call_count == 1
    assert item.message_count == 1
    assert len(repository.items) == 1


@pytest.mark.asyncio
async def test_registry_does_not_mark_an_odata_patient_as_new() -> None:
    registry = ContactRegistry(FakeContactRepository(patient=True))

    item = await registry.register_inbound(
        tenant_id=uuid4(),
        phone="77012345678",
        source="whatsapp",
        occurred_at=datetime.now(UTC),
    )

    assert item is not None and item.was_known_patient is True


@pytest.mark.asyncio
async def test_registry_recovers_first_contact_from_legacy_history() -> None:
    prior = datetime(2026, 8, 20, 10, tzinfo=UTC)
    registry = ContactRegistry(FakeContactRepository(prior=(prior, "whatsapp")))

    item = await registry.register_inbound(
        tenant_id=uuid4(),
        phone="77012345678",
        source="kcell",
        occurred_at=prior + timedelta(days=7),
    )

    assert item is not None
    assert item.first_inbound_at == prior
    assert item.first_inbound_source == "whatsapp"


@pytest.mark.asyncio
async def test_registry_encrypts_full_phone_for_authorized_list() -> None:
    secret = "contact-list-test-secret-long-enough"
    registry = ContactRegistry(FakeContactRepository(), secret)

    item = await registry.register_inbound(
        tenant_id=uuid4(),
        phone="8 701 234 56 78",
        source="kcell",
        occurred_at=datetime.now(UTC),
    )

    assert item is not None
    assert item.phone_ciphertext != "+77012345678"
    assert decrypt_contact(item.phone_ciphertext, secret) == "+77012345678"


class FakeHistoryRepository(FakeContactRepository):
    def __init__(self, occurred_at: datetime) -> None:
        super().__init__()
        self.occurred_at = occurred_at

    async def historical_kcell_inbounds(self, tenant_id, date_from, date_to):
        return [({"phone": "8 (701) 234-56-78"}, self.occurred_at)]

    async def historical_whatsapp_inbounds(self, tenant_id, date_from, date_to):
        return []


@pytest.mark.asyncio
async def test_history_materialization_restores_full_kcell_phone() -> None:
    secret = "historical-contact-secret-long-enough"
    repository = FakeHistoryRepository(datetime(2026, 8, 1, 8, tzinfo=UTC))
    service = ContactService(
        repository,
        Settings(whatsapp_data_key=secret),
    )
    tenant_id = uuid4()

    await service._materialize_history(
        tenant_id,
        datetime(2026, 8, 1, tzinfo=UTC).date(),
        datetime(2026, 8, 28, tzinfo=UTC).date(),
    )

    item = repository.items[(tenant_id, phone_hash("+77012345678"))]
    assert item.phone_masked is None
    assert decrypt_contact(item.phone_ciphertext, secret) == "+77012345678"
    assert item.first_inbound_source == "kcell"
