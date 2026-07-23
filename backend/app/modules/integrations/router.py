"""HTTP surface for integration setup, mapping and tabular ingestion."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status

from app.core.errors import AppError
from app.modules.auth.dependencies import CurrentUser
from app.modules.integrations.dependencies import get_integration_service
from app.modules.integrations.schemas import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionResponse,
    IngestionSummaryResponse,
    MappingProfileCreateRequest,
    MappingProfileListResponse,
    MappingProfileResponse,
)
from app.modules.integrations.service import IntegrationService
from app.modules.integrations.tabular_adapter import TabularFileAdapter

router = APIRouter(prefix="/integrations", tags=["integrations"])
IntegrationServiceDependency = Annotated[
    IntegrationService, Depends(get_integration_service)
]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


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
