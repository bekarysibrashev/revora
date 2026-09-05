from hashlib import sha256
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.security import normalize_phone_e164, phone_hash, phone_hash_candidates
from app.core.config import Settings
from app.modules.contacts.models import ContactIdentity
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

    result = await registry.register_inbound(
        tenant_id=tenant_id, phone="87012345678", source="kcell", occurred_at=first
    )
    repeated = await registry.register_inbound(
        tenant_id=tenant_id,
        phone="+7 701 234 56 78",
        source="whatsapp",
        occurred_at=first + timedelta(hours=1),
    )

    assert repeated.identity is result.identity
    assert result.identity.first_inbound_source == "kcell"
    assert result.identity.inbound_count == 2
    assert result.identity.call_count == 1
    assert result.identity.message_count == 1
    assert len(repository.items) == 1
    # Different formats of the same number ("87012345678" then
    # "+7 701 234 56 78") resolve to the same phone_hash, so the second
    # inbound is a repeat_contact on the very same row, never a new one.
    assert result.classification == "new_contact"
    assert repeated.classification == "repeat_contact"


@pytest.mark.asyncio
async def test_registry_classifies_a_number_absent_from_1c_as_new_contact() -> None:
    registry = ContactRegistry(FakeContactRepository(patient=False))

    result = await registry.register_inbound(
        tenant_id=uuid4(),
        phone="77012345678",
        source="whatsapp",
        occurred_at=datetime.now(UTC),
    )

    assert result.identity is not None and result.identity.was_known_patient is False
    assert result.classification == "new_contact"


@pytest.mark.asyncio
async def test_registry_does_not_mark_an_odata_patient_as_new() -> None:
    registry = ContactRegistry(FakeContactRepository(patient=True))

    result = await registry.register_inbound(
        tenant_id=uuid4(),
        phone="77012345678",
        source="whatsapp",
        occurred_at=datetime.now(UTC),
    )

    assert result.identity is not None and result.identity.was_known_patient is True
    # A known 1C patient reaching out for the first time on this channel is
    # not a marketing "new contact" -- must not be logged to "Отчет КЦ".
    assert result.classification == "existing_1c_patient"


@pytest.mark.asyncio
async def test_registry_classifies_a_repeat_call_as_repeat_contact() -> None:
    repository = FakeContactRepository(patient=False)
    registry = ContactRegistry(repository)
    tenant_id = uuid4()
    first = datetime(2026, 8, 27, 9, tzinfo=UTC)

    first_call = await registry.register_inbound(
        tenant_id=tenant_id, phone="77012345678", source="kcell", occurred_at=first
    )
    second_call = await registry.register_inbound(
        tenant_id=tenant_id,
        phone="77012345678",
        source="kcell",
        occurred_at=first + timedelta(days=3),
    )

    assert first_call.classification == "new_contact"
    assert second_call.classification == "repeat_contact"
    assert second_call.identity.call_count == 2
    assert second_call.identity.inbound_count == 2


@pytest.mark.asyncio
async def test_registry_classifies_missing_phone_as_unknown_patient() -> None:
    registry = ContactRegistry(FakeContactRepository())

    result = await registry.register_inbound(
        tenant_id=uuid4(), phone="", source="kcell", occurred_at=datetime.now(UTC)
    )

    assert result.identity is None
    assert result.classification == "unknown_patient"


@pytest.mark.asyncio
async def test_registry_classifies_an_unparseable_phone_as_unknown_patient() -> None:
    registry = ContactRegistry(FakeContactRepository())

    result = await registry.register_inbound(
        tenant_id=uuid4(), phone="123", source="whatsapp", occurred_at=datetime.now(UTC)
    )

    assert result.identity is None
    assert result.classification == "unknown_patient"
    assert len(registry.repository.items) == 0


class RaceConditionRepository(FakeContactRepository):
    """Models a Kcell call and a WhatsApp message landing on the same phone
    number at (near) the same instant: both webhooks read identity() as
    None, but only one wins the unique-key insert. The loser must fall back
    to the winner's row instead of raising or silently dropping the inbound
    -- and the two channels must merge into one contact, not two.
    """

    def __init__(self) -> None:
        super().__init__()
        self._conflict_pending = True

    async def add_if_missing(self, item):
        key = (item.tenant_id, item.phone_hash)
        if key in self.items:
            return None
        if self._conflict_pending:
            self._conflict_pending = False
            winner = ContactIdentity(
                id=uuid4(),
                tenant_id=item.tenant_id,
                phone_hash=item.phone_hash,
                phone_masked=item.phone_masked,
                phone_ciphertext=item.phone_ciphertext,
                first_inbound_at=item.first_inbound_at,
                first_inbound_source="whatsapp",
                last_inbound_at=item.first_inbound_at,
                last_inbound_source="whatsapp",
                inbound_count=1,
                call_count=0,
                message_count=1,
                was_known_patient=item.was_known_patient,
            )
            self.items[key] = winner
            return None
        self.items[key] = item
        return item


@pytest.mark.asyncio
async def test_registry_merges_a_simultaneous_call_and_whatsapp_into_one_contact() -> None:
    repository = RaceConditionRepository()
    registry = ContactRegistry(repository)
    tenant_id = uuid4()
    occurred_at = datetime(2026, 8, 30, 12, tzinfo=UTC)

    result = await registry.register_inbound(
        tenant_id=tenant_id, phone="77012345678", source="kcell", occurred_at=occurred_at
    )

    assert len(repository.items) == 1
    assert result.identity is not None
    assert result.identity.call_count == 1
    assert result.identity.message_count == 1
    assert result.identity.inbound_count == 2


@pytest.mark.asyncio
async def test_registry_recovers_first_contact_from_legacy_history() -> None:
    prior = datetime(2026, 8, 20, 10, tzinfo=UTC)
    registry = ContactRegistry(FakeContactRepository(prior=(prior, "whatsapp")))

    result = await registry.register_inbound(
        tenant_id=uuid4(),
        phone="77012345678",
        source="kcell",
        occurred_at=prior + timedelta(days=7),
    )

    assert result.identity is not None
    assert result.identity.first_inbound_at == prior
    assert result.identity.first_inbound_source == "whatsapp"


@pytest.mark.asyncio
async def test_registry_encrypts_full_phone_for_authorized_list() -> None:
    secret = "contact-list-test-secret-long-enough"
    registry = ContactRegistry(FakeContactRepository(), secret)

    result = await registry.register_inbound(
        tenant_id=uuid4(),
        phone="8 701 234 56 78",
        source="kcell",
        occurred_at=datetime.now(UTC),
    )

    assert result.identity is not None
    assert result.identity.phone_ciphertext != "+77012345678"
    assert decrypt_contact(result.identity.phone_ciphertext, secret) == "+77012345678"


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
