"""HTTP endpoints for platform-level clinic provisioning.

Зарегистрирован под /platform, а не /tenancy: это осознанный выбор — эндпоинты
здесь работают ПОПЕРЁК тенантов (создают новые), а не внутри одного
конкретного тенанта, как остальной API. Защищены require_platform_admin
(см. dependencies.py), не обычной per-tenant JWT-аутентификацией.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.modules.tenancy.dependencies import get_tenancy_service, require_platform_admin
from app.modules.tenancy.schemas import (
    TenantCreateRequest,
    TenantCreateResponse,
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
