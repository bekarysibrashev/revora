"""Append new-inquiry rows to a clinic-owned Google Sheet.

Revora never reads, formats or manages the rest of the sheet -- it only
appends one row per brand-new contact via the Sheets v4 REST API,
authenticated as a service account the clinic explicitly shares the sheet
with (Editor access on that one file). Disabled as a silent no-op until both
the service account key and the spreadsheet id are configured.

Deliberately avoids the google-api-python-client / google-auth SDKs: the
project already depends on httpx and python-jose[cryptography], and a
service-account bearer token is just one RS256-signed JWT exchanged for an
access token, so no extra dependency earns its place for one API call.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx
from jose import jwt

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
_TOKEN_LIFETIME_SECONDS = 3600
_TOKEN_REFRESH_MARGIN_SECONDS = 60

RUSSIAN_MONTHS = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}

# Exact column order of the clinic's "Отчет КЦ" tab (from РПО SAN 2026.xlsx,
# row 1). Keep this in sync with the sheet -- Google Sheets append writes by
# position, not by header name.
NEW_CONTACT_COLUMNS = [
    "Дата", "Месяц", "ФИО", "Телефон", "Откуда узнал", "Канал Связи",
    "Квалификация", "Креатив", "Отделение", "Направление", "Запись ",
    "Причина отказа", "Врач", "Куратор", "Дополнительные комментарии",
]

# "Канал Связи" is a validated dropdown in the clinic's sheet (see the
# "Справочник" tab); these are the two values Revora's own sources map to.
SOURCE_CHANNEL_LABELS = {"kcell": "Входящий звонок", "whatsapp": "WA"}

AUTO_ENTRY_NOTE = "Занесено автоматически Revora"


class GoogleSheetsSyncError(RuntimeError):
    """A row could not be appended. Callers should log this and continue."""


class GoogleSheetsCredentialsError(GoogleSheetsSyncError):
    """The configured service account JSON is missing, malformed or rejected."""


def build_new_contact_row(
    *, phone_e164: str | None, source: str, first_inbound_at: datetime,
) -> list[str]:
    """Map a brand-new contact to one "Отчет КЦ" row.

    Only fields Revora can know for certain at the moment of first contact
    are filled in: date, phone and channel. Everything staff normally judge
    during the call or chat -- lead source, qualification, department,
    doctor, curator, booking outcome -- is left blank on purpose. Revora
    never invents a value for those; the project's own rule is to ask
    explicitly (or here, leave a blank cell) rather than guess.
    """

    phone_digits = phone_e164.lstrip("+") if phone_e164 else ""
    row = {name: "" for name in NEW_CONTACT_COLUMNS}
    row["Дата"] = first_inbound_at.date().isoformat()
    row["Месяц"] = RUSSIAN_MONTHS[first_inbound_at.month]
    row["Телефон"] = phone_digits
    row["Канал Связи"] = SOURCE_CHANNEL_LABELS.get(source, source)
    row["Дополнительные комментарии"] = AUTO_ENTRY_NOTE
    return [row[name] for name in NEW_CONTACT_COLUMNS]


class GoogleSheetsClient:
    """Minimal async Sheets v4 client authenticated as a service account."""

    def __init__(
        self,
        *,
        credentials_json: str,
        spreadsheet_id: str,
        sheet_name: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # transport is test-only: it lets unit tests inject an httpx.MockTransport
        # instead of making real calls to Google. Production never sets it.
        self._transport = transport
        try:
            credentials = json.loads(credentials_json)
        except (TypeError, ValueError) as exc:
            raise GoogleSheetsCredentialsError(
                "Google service account JSON is not valid JSON"
            ) from exc
        try:
            self._client_email = credentials["client_email"]
            self._private_key = credentials["private_key"]
        except KeyError as exc:
            raise GoogleSheetsCredentialsError(
                f"service account JSON is missing required field {exc}"
            ) from exc
        self._token_uri = credentials.get("token_uri", DEFAULT_TOKEN_URL)
        self._spreadsheet_id = spreadsheet_id
        self._sheet_name = sheet_name
        self._cached_token: str | None = None
        self._cached_token_expires_at: float = 0.0

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        now = time.time()
        if self._cached_token and now < self._cached_token_expires_at - _TOKEN_REFRESH_MARGIN_SECONDS:
            return self._cached_token
        claims = {
            "iss": self._client_email,
            "scope": SHEETS_SCOPE,
            "aud": self._token_uri,
            "iat": int(now),
            "exp": int(now) + _TOKEN_LIFETIME_SECONDS,
        }
        try:
            assertion = jwt.encode(claims, self._private_key, algorithm="RS256")
        except Exception as exc:  # python-jose raises its own JWTError family
            raise GoogleSheetsCredentialsError(
                "could not sign the service account JWT -- check the private_key field"
            ) from exc
        response = await client.post(
            self._token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        if response.status_code >= 400:
            raise GoogleSheetsCredentialsError(
                f"Google token exchange failed: {response.status_code} {response.text[:200]}"
            )
        payload = response.json()
        self._cached_token = payload["access_token"]
        self._cached_token_expires_at = now + float(
            payload.get("expires_in", _TOKEN_LIFETIME_SECONDS)
        )
        return self._cached_token

    async def append_row(self, values: list[object]) -> None:
        """Append one row to the configured tab. Raises on any failure."""

        range_ = f"{self._sheet_name}!A1"
        url = (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{self._spreadsheet_id}/values/{quote(range_, safe='')}:append"
        )
        async with httpx.AsyncClient(timeout=10, transport=self._transport) as client:
            token = await self._access_token(client)
            response = await client.post(
                url,
                params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                headers={"Authorization": f"Bearer {token}"},
                json={"values": [values]},
            )
        if response.status_code >= 400:
            raise GoogleSheetsSyncError(
                f"Google Sheets append failed: {response.status_code} {response.text[:300]}"
            )


@lru_cache(maxsize=4)
def _cached_client(credentials_json: str, spreadsheet_id: str, sheet_name: str) -> GoogleSheetsClient:
    # Cached (not re-built per request) so the OAuth access token is reused
    # across new-contact events instead of re-signed and re-exchanged every
    # time -- ContactRegistry is otherwise constructed fresh per request.
    return GoogleSheetsClient(
        credentials_json=credentials_json, spreadsheet_id=spreadsheet_id, sheet_name=sheet_name
    )


def get_google_sheets_client(settings: "Settings") -> GoogleSheetsClient | None:
    """Return the shared client, or None while the integration is unconfigured."""

    credentials_json = settings.google_sheets_service_account_json.get_secret_value()
    spreadsheet_id = settings.google_sheets_new_contacts_spreadsheet_id
    if not credentials_json or not spreadsheet_id:
        return None
    try:
        return _cached_client(
            credentials_json, spreadsheet_id, settings.google_sheets_new_contacts_sheet_name
        )
    except GoogleSheetsCredentialsError:
        logger.error("Google Sheets sync is configured but the credentials are invalid", exc_info=True)
        return None
