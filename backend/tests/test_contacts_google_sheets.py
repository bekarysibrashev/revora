"""Google Sheets sync for the "new inquiries" (новые обращения) feature."""
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.modules.contacts.google_sheets import (
    GoogleSheetsClient,
    GoogleSheetsCredentialsError,
    GoogleSheetsSyncError,
    build_new_contact_row,
)
from app.modules.contacts.service import ContactRegistry


# ---------------------------------------------------------------------------
# build_new_contact_row: only fields Revora can actually know get filled in.
# ---------------------------------------------------------------------------


def test_row_matches_the_clinic_sheet_column_order_and_leaves_judgment_columns_blank() -> None:
    row = build_new_contact_row(
        phone_e164="+77012345678",
        source="whatsapp",
        first_inbound_at=datetime(2026, 3, 4, 9, 30, tzinfo=UTC),
    )

    assert row == [
        "2026-03-04",  # Дата
        "Март",  # Месяц
        "",  # ФИО
        "77012345678",  # Телефон
        "",  # Откуда узнал
        "WA",  # Канал Связи
        "",  # Квалификация
        "",  # Креатив
        "",  # Отделение
        "",  # Направление
        "",  # Запись
        "",  # Причина отказа
        "",  # Врач
        "",  # Куратор
        "Занесено автоматически Revora",  # Дополнительные комментарии
    ]


def test_kcell_source_maps_to_the_incoming_call_channel_label() -> None:
    row = build_new_contact_row(
        phone_e164="+77012345678", source="kcell", first_inbound_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert row[5] == "Входящий звонок"


def test_missing_phone_leaves_the_phone_column_blank_instead_of_guessing() -> None:
    row = build_new_contact_row(
        phone_e164=None, source="kcell", first_inbound_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert row[3] == ""


def test_january_maps_to_the_russian_nominative_month_name() -> None:
    row = build_new_contact_row(
        phone_e164="+77012345678", source="kcell", first_inbound_at=datetime(2026, 1, 15, tzinfo=UTC)
    )

    assert row[1] == "Январь"


# ---------------------------------------------------------------------------
# GoogleSheetsClient: credentials validation and the actual append call.
# ---------------------------------------------------------------------------


def _rsa_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def _service_account_json(**overrides: str) -> str:
    payload = {
        "client_email": "revora-sheets@example.iam.gserviceaccount.com",
        "private_key": _rsa_private_key_pem(),
        "token_uri": "https://oauth2.googleapis.com/token",
        **overrides,
    }
    return json.dumps(payload)


def test_credentials_json_must_be_valid_json() -> None:
    with pytest.raises(GoogleSheetsCredentialsError):
        GoogleSheetsClient(credentials_json="not json", spreadsheet_id="sheet-1", sheet_name="Отчет КЦ")


def test_credentials_json_must_include_the_service_account_fields() -> None:
    with pytest.raises(GoogleSheetsCredentialsError):
        GoogleSheetsClient(
            credentials_json='{"client_email": "svc@example.iam.gserviceaccount.com"}',
            spreadsheet_id="sheet-1",
            sheet_name="Отчет КЦ",
        )


@pytest.mark.asyncio
async def test_append_row_exchanges_a_token_then_posts_the_values() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "fake-token", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer fake-token"
        assert request.url.params["valueInputOption"] == "USER_ENTERED"
        return httpx.Response(200, json={"updates": {"updatedRows": 1}})

    client = GoogleSheetsClient(
        credentials_json=_service_account_json(),
        spreadsheet_id="sheet-1",
        sheet_name="Отчет КЦ",
        transport=httpx.MockTransport(handler),
    )

    await client.append_row(["2026-03-04", "Март"])

    assert len(calls) == 2
    assert calls[0].url.path == "/token"
    assert "spreadsheets/sheet-1/values" in str(calls[1].url)


@pytest.mark.asyncio
async def test_append_row_reuses_the_cached_token_on_a_second_call() -> None:
    token_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/token":
            token_requests += 1
            return httpx.Response(200, json={"access_token": "fake-token", "expires_in": 3600})
        return httpx.Response(200, json={})

    client = GoogleSheetsClient(
        credentials_json=_service_account_json(),
        spreadsheet_id="sheet-1",
        sheet_name="Отчет КЦ",
        transport=httpx.MockTransport(handler),
    )

    await client.append_row(["row one"])
    await client.append_row(["row two"])

    assert token_requests == 1


@pytest.mark.asyncio
async def test_append_row_raises_on_a_google_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "fake-token", "expires_in": 3600})
        return httpx.Response(403, json={"error": "permission denied"})

    client = GoogleSheetsClient(
        credentials_json=_service_account_json(),
        spreadsheet_id="sheet-1",
        sheet_name="Отчет КЦ",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GoogleSheetsSyncError):
        await client.append_row(["row"])


# ---------------------------------------------------------------------------
# ContactRegistry wiring: sync fires once per brand-new contact, never blocks
# the webhook if Google Sheets is unreachable or misconfigured.
# ---------------------------------------------------------------------------


class _FakeContactRepository:
    def __init__(self) -> None:
        self.items: dict = {}

    async def identity(self, tenant_id, digest, *, lock=False):
        return self.items.get((tenant_id, digest))

    async def is_patient(self, tenant_id, candidates):
        return False

    async def prior_inbound(self, tenant_id, candidates):
        return (None, None)

    async def add_if_missing(self, item):
        key = (item.tenant_id, item.phone_hash)
        if key in self.items:
            return None
        self.items[key] = item
        return item


class _RecordingSheetsClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.rows: list[list[object]] = []

    async def append_row(self, values: list[object]) -> None:
        if self.fail:
            raise GoogleSheetsSyncError("boom")
        self.rows.append(values)


@pytest.mark.asyncio
async def test_registry_appends_a_row_only_for_a_brand_new_contact() -> None:
    sheets_client = _RecordingSheetsClient()
    registry = ContactRegistry(_FakeContactRepository(), sheets_client=sheets_client)
    tenant_id = uuid4()
    first_contact = datetime(2026, 3, 4, 9, tzinfo=UTC)

    await registry.register_inbound(
        tenant_id=tenant_id, phone="87012345678", source="whatsapp", occurred_at=first_contact
    )
    # Same person messages again later -- must not create a second row.
    await registry.register_inbound(
        tenant_id=tenant_id,
        phone="87012345678",
        source="whatsapp",
        occurred_at=first_contact.replace(hour=10),
    )

    assert len(sheets_client.rows) == 1
    assert sheets_client.rows[0][3] == "77012345678"


@pytest.mark.asyncio
async def test_registry_never_raises_when_the_sheet_sync_fails() -> None:
    registry = ContactRegistry(_FakeContactRepository(), sheets_client=_RecordingSheetsClient(fail=True))

    item = await registry.register_inbound(
        tenant_id=uuid4(), phone="87012345678", source="kcell", occurred_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert item is not None  # the webhook's own result is unaffected


@pytest.mark.asyncio
async def test_registry_is_a_no_op_without_a_configured_sheets_client() -> None:
    registry = ContactRegistry(_FakeContactRepository())  # sheets_client defaults to None

    item = await registry.register_inbound(
        tenant_id=uuid4(), phone="87012345678", source="kcell", occurred_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert item is not None
