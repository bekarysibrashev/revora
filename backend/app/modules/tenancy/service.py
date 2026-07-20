"""Business rules for platform-level clinic provisioning (cross-tenant, not
scoped to any single tenant — this is what lets an operator create the very
first tenant a clinic has)."""

from app.core.errors import AppError
from app.core.security import hash_password
from app.modules.tenancy.repository import TenancyRepository
from app.modules.tenancy.schemas import (
    TenantCreateRequest,
    TenantCreateResponse,
    TenantListResponse,
    TenantResponse,
)


class TenancyService:
    def __init__(self, repository: TenancyRepository) -> None:
        self.repository = repository

    async def list_tenants(self) -> TenantListResponse:
        tenants = await self.repository.list_tenants()
        items = [TenantResponse.model_validate(tenant) for tenant in tenants]
        return TenantListResponse(items=items, total=len(items))

    async def create_tenant(self, payload: TenantCreateRequest) -> TenantCreateResponse:
        if await self.repository.slug_exists(payload.tenant_slug):
            raise AppError(
                "TENANT_SLUG_EXISTS", "A clinic with this code already exists", 409
            )

        tenant = await self.repository.create_tenant_with_owner(
            tenant_name=payload.tenant_name,
            tenant_slug=payload.tenant_slug,
            branch_name=payload.branch_name,
            branch_code=payload.branch_code,
            owner_email=payload.owner_email,
            owner_full_name=payload.owner_full_name,
            owner_password_hash=hash_password(payload.owner_password),
        )
        return TenantCreateResponse(
            tenant=TenantResponse.model_validate(tenant),
            branch_code=payload.branch_code,
            owner_email=payload.owner_email,
        )
