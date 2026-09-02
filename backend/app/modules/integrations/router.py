"""HTTP surface for integration setup, mapping and tabular ingestion."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.modules.auth.dependencies import CurrentUser
from app.modules.integrations.dependencies import get_integration_service
from app.modules.integrations.schemas import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionSyncStatusResponse,
    IngestionSummaryResponse,
    MappingProfileCreateRequest,
    MappingProfileListResponse,
    MappingProfileResponse,
    OneCConnectorTokenResponse,
    OneCNormalizeRequest,
    OneCNormalizeResponse,
    OneCMetadataRequest,
    OneCMetadataResponse,
    OneCPushRequest,
    OneCPushResponse,
    OneCSyncManifestRequest,
    OneCSyncManifestResponse,
)
from app.modules.integrations.service import IntegrationService
from app.modules.integrations.tabular_adapter import TabularFileAdapter
from app.modules.reports.dependencies import get_official_reports_service
from app.modules.reports.schemas import OneCReportSnapshotRequest, OfficialReportResponse
from app.modules.reports.service import OfficialReportsService

router = APIRouter(prefix="/integrations", tags=["integrations"])
IntegrationServiceDependency = Annotated[
    IntegrationService, Depends(get_integration_service)
]
OfficialReportsServiceDependency = Annotated[
    OfficialReportsService, Depends(get_official_reports_service)
]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
connector_bearer = HTTPBearer(auto_error=False)


@router.post("/1c/push", response_model=OneCPushResponse)
async def push_one_c_batch(
    payload: OneCPushRequest,
    service: IntegrationServiceDependency,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(connector_bearer)
    ],
) -> OneCPushResponse:
    if credentials is None:
        raise AppError("CONNECTOR_TOKEN_REQUIRED", "Connector token is required", 401)
    return await service.ingest_one_c_push(credentials.credentials, payload)


@router.post("/1c/report-snapshot", response_model=OfficialReportResponse)
async def push_one_c_report_snapshot(
    payload: OneCReportSnapshotRequest,
    service: IntegrationServiceDependency,
    reports_service: OfficialReportsServiceDependency,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(connector_bearer)
    ],
) -> OfficialReportResponse:
    if credentials is None:
        raise AppError("CONNECTOR_TOKEN_REQUIRED", "Connector token is required", 401)
    parts, connection = await service.authenticate_one_c_connector(credentials.credentials)
    branch_code_map = await service.one_c_connector_branch_code_map(
        parts.tenant_id, connection.id
    )
    return await reports_service.ingest_connector_snapshot(
        tenant_id=parts.tenant_id,
        connection_id=connection.id,
        branch_code_map=branch_code_map,
        payload=payload,
    )


@router.post("/1c/metadata", response_model=OneCMetadataResponse)
async def push_one_c_metadata(
    payload: OneCMetadataRequest,
    service: IntegrationServiceDependency,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(connector_bearer)
    ],
) -> OneCMetadataResponse:
    if credentials is None:
        raise AppError("CONNECTOR_TOKEN_REQUIRED", "Connector token is required", 401)
    return await service.ingest_one_c_metadata(credentials.credentials, payload)


@router.post("/1c/sync-manifest", response_model=OneCSyncManifestResponse)
async def push_one_c_sync_manifest(
    payload: OneCSyncManifestRequest,
    service: IntegrationServiceDependency,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(connector_bearer)
    ],
) -> OneCSyncManifestResponse:
    if credentials is None:
        raise AppError("CONNECTOR_TOKEN_REQUIRED", "Connector token is required", 401)
    return await service.ingest_one_c_sync_manifest(credentials.credentials, payload)


@router.get(
    "/connections/{connection_id}/1c-metadata", response_model=OneCMetadataRequest
)
async def get_one_c_metadata(
    connection_id: UUID,
    user: CurrentUser,
    service: IntegrationServiceDependency,
) -> OneCMetadataRequest:
    return await service.get_one_c_metadata(user, connection_id)


@router.get(
    "/connections/{connection_id}/mappings", response_model=MappingProfileListResponse
)
async def list_mapping_profiles(
    connection_id: UUID,
    user: CurrentUser,
    service: IntegrationServiceDependency,
) -> MappingProfileListResponse:
    return await service.list_mapping_profiles(user, connection_id)


@router.get("/connections", response_model=ConnectionListResponse)
async def list_connections(
    user: CurrentUser, service: IntegrationServiceDependency
) -> ConnectionListResponse:
    return await service.list_connections(user)


@router.post(
    "/connections", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED
)
async def create_connection(
    payload: ConnectionCreateRequest,
    user: CurrentUser,
    service: IntegrationServiceDependency,
) -> ConnectionResponse:
    return await service.create_connection(user, payload)


@router.post(
    "/connections/{connection_id}/connector-token",
    response_model=OneCConnectorTokenResponse,
)
async def rotate_one_c_connector_token(
    connection_id: UUID,
    user: CurrentUser,
    service: IntegrationServiceDependency,
) -> OneCConnectorTokenResponse:
    return await service.rotate_one_c_connector_token(user, connection_id)


@router.get(
    "/connections/{connection_id}/sync-status",
    response_model=ConnectionSyncStatusResponse,
)
async def one_c_sync_status(
    connection_id: UUID,
    user: CurrentUser,
    service: IntegrationServiceDependency,
) -> ConnectionSyncStatusResponse:
    return await service.one_c_sync_status(user, connection_id)


@router.post(
    "/connections/{connection_id}/normalize-1c",
    response_model=OneCNormalizeResponse,
)
async def normalize_existing_one_c_records(
    connection_id: UUID,
    payload: OneCNormalizeRequest,
    user: CurrentUser,
    service: IntegrationServiceDependency,
) -> OneCNormalizeResponse:
    return await service.normalize_existing_one_c_records(user, connection_id, payload)


@router.post(
    "/connections/{connection_id}/mappings",
    response_model=MappingProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mapping_profile(
    connection_id: UUID,
    payload: MappingProfileCreateRequest,
    user: CurrentUser,
    service: IntegrationServiceDependency,
) -> MappingProfileResponse:
    return await service.create_mapping_profile(user, connection_id, payload)


@router.delete(
    "/connections/{connection_id}/mappings/{mapping_profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mapping_profile(
    connection_id: UUID,
    mapping_profile_id: UUID,
    user: CurrentUser,
    service: IntegrationServiceDependency,
) -> None:
    await service.delete_mapping_profile(user, connection_id, mapping_profile_id)


@router.post(
    "/connections/{connection_id}/ingest",
    response_model=IngestionSummaryResponse,
)
async def ingest_tabular_file(
    connection_id: UUID,
    mapping_profile_id: Annotated[UUID, Query()],
    filename: Annotated[str, Query(min_length=5, max_length=255)],
    source_entity: Annotated[str, Query(min_length=1, max_length=100)],
    user: CurrentUser,
    service: IntegrationServiceDependency,
    content: Annotated[bytes, Body(media_type="application/octet-stream")],
    sheet_name: Annotated[str | None, Query(max_length=100)] = None,
) -> IngestionSummaryResponse:
    if not content:
        raise AppError("EMPTY_UPLOAD", "Uploaded file is empty", 422)
    if len(content) > MAX_UPLOAD_BYTES:
        raise AppError("UPLOAD_TOO_LARGE", "Uploaded file exceeds 50 MB", 413)
    adapter = TabularFileAdapter(
        filename=filename,
        content=content,
        source_entity=source_entity,
        sheet_name=sheet_name,
    )
    return await service.ingest(
        user,
        connection_id=connection_id,
        mapping_profile_id=mapping_profile_id,
        adapter=adapter,
    )
