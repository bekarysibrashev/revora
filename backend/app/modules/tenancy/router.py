"""HTTP endpoints for platform-level clinic provisioning.

Зарегистрирован под /platform, а не /tenancy: это осознанный выбор — эндпоинты
здесь работают ПОПЕРЁК тенантов (создают новые), а не внутри одного
конкретного тенанта, как остальной API. Защищены require_platform_admin
(см. dependencies.py), не обычной per-tenant JWT-аутентификацией.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from uuid import UUID

from app.modules.tenancy.dependencies import get_tenancy_service, require_platform_admin
from app.modules.tenancy.schemas import (
    TenantCreateRequest,
    TenantCreateResponse,
    TenantDeleteRequest,
    TenantDeleteResponse,
    TenantListResponse,
)
from app.modules.tenancy.service import TenancyService

router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    dependencies=[Depends(require_platform_admin)],
)
TenancyServiceDependency = Annotated[TenancyService, Depends(get_tenancy_service)]


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(service: TenancyServiceDependency) -> TenantListResponse:
    return await service.list_tenants()


@router.post("/tenants", response_model=TenantCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreateRequest, service: TenancyServiceDependency
) -> TenantCreateResponse:
    return await service.create_tenant(payload)


@router.delete("/tenants/{tenant_id}", response_model=TenantDeleteResponse)
async def delete_tenant(
    tenant_id: UUID,
    service: TenancyServiceDependency,
    confirm_slug: str = Query(min_length=2, max_length=100),
) -> TenantDeleteResponse:
    return await service.delete_tenant(tenant_id, confirm_slug)


@router.post("/tenants/{tenant_id}/delete", response_model=TenantDeleteResponse)
async def delete_tenant_command(
    tenant_id: UUID,
    payload: TenantDeleteRequest,
    service: TenancyServiceDependency,
) -> TenantDeleteResponse:
    """Browser/proxy-compatible destructive command with body confirmation."""
    return await service.delete_tenant(tenant_id, payload.confirm_slug)
