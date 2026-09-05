from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.modules.integrations.canonical_writer import CanonicalWriteError
from app.modules.integrations.schemas import OneCOperationalBatchRequest
from app.modules.integrations.service import IntegrationService


class _Writer:
    def __init__(self) -> None:
        self.rows: list[tuple[object, str, dict[str, object]]] = []

    async def write(self, *, tenant_id, target_entity, data):
        if data.get("external_id") == "bad":
            raise CanonicalWriteError("invalid test row")
        self.rows.append((tenant_id, target_entity, data))
        return uuid4()


class _Repository:
    def __init__(self) -> None:
        self.connection = SimpleNamespace(settings={}, status="connected")
        self.marked = False

    async def match_one_c_branch_code(self, tenant_id, label):
        return "seifullina" if label == "SAN (Сейфуллина)" else None

    async def single_active_branch_code(self, tenant_id):
        return None

    async def get_connection(self, tenant_id, connection_id):
        return self.connection

    async def mark_connection_synced(self, connection, *, entity, synced_at):
        self.marked = entity == "operational_batch"


@pytest.mark.asyncio
async def test_operational_batch_maps_branch_and_quarantines_expected_bad_row() -> None:
    tenant_id, connection_id = uuid4(), uuid4()
    repository, writer = _Repository(), _Writer()
    service = IntegrationService(repository, writer)
    payload = OneCOperationalBatchRequest.model_validate({
        "batch_id": "patients-1",
        "cursor": "200",
        "records": [
            {
                "target_entity": "patient",
                "data": {
                    "external_id": "patient-1",
                    "branch_key": "unit-guid",
                    "branch_label": "SAN (Сейфуллина)",
                    "phone_hash": "a" * 64,
                },
            },
            {"target_entity": "patient", "data": {"external_id": "bad"}},
        ],
    })

    result = await service.ingest_one_c_operational_batch(
        tenant_id=tenant_id,
        connection_id=connection_id,
        branch_code_map={},
        payload=payload,
    )

    assert result.received == 2
    assert result.upserted == 1
    assert result.rejected == 1
    assert result.cursor == "200"
    assert writer.rows[0][2]["branch_code"] == "seifullina"
    assert "branch_key" not in writer.rows[0][2]
    assert repository.marked


def test_operational_batch_route_requires_connector_token() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    payload = {
        "batch_id": "patients-1",
        "records": [{
            "target_entity": "patient",
            "data": {"external_id": "patient-1"},
        }],
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/integrations/1c/operational-records/batch",
            json=payload,
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "CONNECTOR_TOKEN_REQUIRED"


def test_operational_batch_rejects_arbitrary_target() -> None:
    with pytest.raises(ValueError):
        OneCOperationalBatchRequest.model_validate({
            "batch_id": "unsafe",
            "records": [{
                "target_entity": "users",
                "data": {"external_id": "x"},
            }],
        })


def test_operational_batch_allows_normalized_one_c_expense_fact() -> None:
    payload = OneCOperationalBatchRequest.model_validate({
        "batch_id": "expenses-1",
        "records": [{
            "target_entity": "expense_fact",
            "data": {
                "external_id": "expense-guid",
                "occurred_on": "2026-06-01",
                "amount": "125000.50",
                "paid_amount": "125000.50",
                "currency": "KZT",
                "category_name": "Аренда",
            },
        }],
    })

    assert payload.records[0].target_entity == "expense_fact"
