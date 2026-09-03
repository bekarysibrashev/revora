"""Tests for the 1C connector token lifecycle and the extension-facing surface
that the "Revora" 1C extension actually uses: token issuance/parsing/hashing,
extension authentication, branch/subdivision mapping, and the
/1c/report-snapshot endpoint's reachability and protection.

These tests replace test_one_c_integration.py, which covered the retired
OData push connector (removed together with its endpoints and background
worker). Only the checks below still apply to the current integration.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.modules.integrations.one_c import (
    ONE_C_PROVIDER,
    connector_token_digest,
    issue_connector_token,
    parse_connector_token,
)
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.service import IntegrationService


# --- token issuance, parsing and hashing -----------------------------------


def test_connector_token_round_trip_and_digest() -> None:
    tenant_id, connection_id = uuid4(), uuid4()

    token, digest = issue_connector_token(tenant_id, connection_id)
    parts = parse_connector_token(token)

    assert parts.tenant_id == tenant_id
    assert parts.connection_id == connection_id
    assert digest == connector_token_digest(token)
    assert token not in digest


# --- extension authentication (authenticate_one_c_connector) --------------


class _FakeConnectorRepository:
    def __init__(self, connection: SimpleNamespace | None) -> None:
        self._connection = connection
        self.context: object | None = None

    async def set_tenant_context(self, tenant_id: object) -> None:
        self.context = tenant_id

    async def get_connection(self, tenant_id: object, connection_id: object):
        if (
            self._connection is not None
            and tenant_id == self._connection.tenant_id
            and connection_id == self._connection.id
        ):
            return self._connection
        return None


@pytest.mark.asyncio
async def test_authenticate_one_c_connector_accepts_a_valid_token() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    connection = SimpleNamespace(
        id=connection_id,
        tenant_id=tenant_id,
        provider=ONE_C_PROVIDER,
        encrypted_credentials=digest,
    )
    service = IntegrationService(_FakeConnectorRepository(connection), canonical_writer=None)

    parts, authenticated_connection = await service.authenticate_one_c_connector(token)

    assert parts.tenant_id == tenant_id
    assert parts.connection_id == connection_id
    assert authenticated_connection is connection


@pytest.mark.asyncio
async def test_authenticate_one_c_connector_rejects_a_malformed_token() -> None:
    service = IntegrationService(_FakeConnectorRepository(None), canonical_writer=None)

    with pytest.raises(AppError) as exc_info:
        await service.authenticate_one_c_connector("not-a-connector-token")

    assert exc_info.value.code == "INVALID_CONNECTOR_TOKEN"
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_authenticate_one_c_connector_rejects_a_digest_mismatch() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, _real_digest = issue_connector_token(tenant_id, connection_id)
    _other_token, unrelated_digest = issue_connector_token(uuid4(), uuid4())
    connection = SimpleNamespace(
        id=connection_id,
        tenant_id=tenant_id,
        provider=ONE_C_PROVIDER,
        encrypted_credentials=unrelated_digest,
    )
    service = IntegrationService(_FakeConnectorRepository(connection), canonical_writer=None)

    with pytest.raises(AppError) as exc_info:
        await service.authenticate_one_c_connector(token)

    assert exc_info.value.code == "INVALID_CONNECTOR_TOKEN"


@pytest.mark.asyncio
async def test_authenticate_one_c_connector_rejects_a_non_one_c_connection() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    token, digest = issue_connector_token(tenant_id, connection_id)
    connection = SimpleNamespace(
        id=connection_id,
        tenant_id=tenant_id,
        provider="whatsapp_business",
        encrypted_credentials=digest,
    )
    service = IntegrationService(_FakeConnectorRepository(connection), canonical_writer=None)

    with pytest.raises(AppError) as exc_info:
        await service.authenticate_one_c_connector(token)

    assert exc_info.value.code == "INVALID_CONNECTOR_TOKEN"


# --- branch / subdivision mapping (shared with the report-snapshot flow) --


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


# --- /1c/report-snapshot reachability and protection -----------------------


def _valid_snapshot_payload() -> dict:
    return {
        "report_type": "cash_receipts",
        "period_from": "2026-07-01",
        "period_to": "2026-07-31",
        "metrics": [
            {
                "dimension_type": "branch",
                "dimension_key": "sf",
                "dimension_label": "Сейфуллина",
                "metric_code": "cash_receipts_total",
                "value": "1000.00",
            }
        ],
    }


def test_report_snapshot_route_requires_a_connector_token() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/integrations/1c/report-snapshot", json=_valid_snapshot_payload()
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "CONNECTOR_TOKEN_REQUIRED"


def test_report_snapshot_route_rejects_a_malformed_connector_token() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/integrations/1c/report-snapshot",
            json=_valid_snapshot_payload(),
            headers={"Authorization": "Bearer not-a-real-connector-token"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CONNECTOR_TOKEN"
