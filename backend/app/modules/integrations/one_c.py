"""Connector-token issuance and verification for 1C connections (used by the 1C extension's report-snapshot endpoint)."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import secrets
from uuid import UUID


# Legacy identifier: this is the historical provider value stored on the
# existing IntegrationConnection row from the old OData push connector. It is
# kept only so that connection is not orphaned, and must not be renamed --
# the 1C "Revora" extension authenticates via the connector token, not this
# string, so it has no effect on the current (report-snapshot) integration.
ONE_C_PROVIDER = "1c_odata_push"
CONNECTOR_TOKEN_PREFIX = "rvo1"


class InvalidConnectorToken(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectorTokenParts:
    tenant_id: UUID
    connection_id: UUID


def issue_connector_token(tenant_id: UUID, connection_id: UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    token = f"{CONNECTOR_TOKEN_PREFIX}.{tenant_id}.{connection_id}.{secret}"
    return token, connector_token_digest(token)


def parse_connector_token(token: str) -> ConnectorTokenParts:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != CONNECTOR_TOKEN_PREFIX or len(parts[3]) < 32:
        raise InvalidConnectorToken("Invalid 1C connector token")
    try:
        return ConnectorTokenParts(tenant_id=UUID(parts[1]), connection_id=UUID(parts[2]))
    except (ValueError, AttributeError) as exc:
        raise InvalidConnectorToken("Invalid 1C connector token") from exc


def connector_token_digest(token: str) -> str:
    return f"sha256:{sha256(token.encode('utf-8')).hexdigest()}"
