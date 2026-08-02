"""Security and record identity helpers for the local 1C OData connector."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import secrets
from uuid import UUID


ONE_C_PROVIDER = "1c_odata_push"
CONNECTOR_TOKEN_PREFIX = "rvo1"

# These entities contain financial identifiers but no direct patient names or
# phone numbers in the metadata supplied by SAN Dental. Leads and payment
# documents are deliberately excluded until field-level PII protection exists.
SAFE_ONE_C_ENTITIES = (
    "AccumulationRegister_Выручка_RecordType",
    "AccumulationRegister_ДенежныеСредства_RecordType",
    "AccumulationRegister_Затраты_RecordType",
    "AccumulationRegister_НарядЗаказы_RecordType",
    "AccumulationRegister_Продажи_RecordType",
    "AccumulationRegister_ПродажиСебестоимость_RecordType",
    "AccumulationRegister_РабочееВремяСотрудников_RecordType",
    "AccumulationRegister_РасчетыСПерсоналом_RecordType",
)


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


def source_record_id(record: dict[str, object]) -> str:
    """Build a stable identity for OData catalog, document and register rows."""

    ref_key = record.get("Ref_Key")
    if ref_key:
        return str(ref_key)

    identity = [
        record.get("Recorder_Key") or record.get("Recorder"),
        record.get("Period"),
        record.get("LineNumber"),
    ]
    if any(value is not None for value in identity):
        return "|".join("" if value is None else str(value) for value in identity)

    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()
