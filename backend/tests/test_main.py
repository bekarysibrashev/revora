from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_endpoint_and_request_id() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-request-id"] == "test-request"


def test_docs_are_available_outside_production() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.get("/api/v1/docs")

    assert response.status_code == 200


def test_protected_auth_route_uses_error_envelope() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_admin_branches_route_is_registered_and_protected() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.get("/api/v1/admin/branches")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_admin_branch_mutations_are_registered_and_protected() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    branch_id = "00000000-0000-0000-0000-000000000001"

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/admin/branches",
            json={"name": "SAN Abaya", "code": "abaya"},
        )
        update_response = client.patch(
            f"/api/v1/admin/branches/{branch_id}",
            json={"is_active": False},
        )

    assert create_response.status_code == 401
    assert update_response.status_code == 401


def test_integration_routes_are_registered_and_protected() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.get("/api/v1/integrations/connections")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_finance_routes_are_registered_and_protected() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/finance/summary?date_from=2026-07-01&date_to=2026-07-31"
        )

    assert response.status_code == 401


def test_domain_analytics_routes_are_in_openapi() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        paths = client.get("/api/v1/openapi.json").json()["paths"]

    assert "/api/v1/sales/overview" in paths
    assert "/api/v1/doctors/overview" in paths
    assert "/api/v1/marketing/overview" in paths
    assert "/api/v1/dashboard/ceo" in paths
