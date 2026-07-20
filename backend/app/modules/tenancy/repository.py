"""Database operations for platform (cross-tenant) clinic provisioning.

Только `tenants` не защищена RLS (нет своего tenant_id — это сам корень
мультитенантности, см. миграцию 20260718_0001_core_tenancy_auth.py: RLS
включена только на `branches` и `users`). Поэтому list_tenants/slug_exists
читают её напрямую, без какого-либо tenant-контекста. А вот вставка Branch и
User внутри create_tenant_with_owner требует `SET LOCAL app.tenant_id` ДО
самого INSERT — иначе WITH CHECK политики их отклонит. Та же
последовательность, что и в app/cli/create_initial_owner.py — этот
репозиторий её просто переиспользует за HTTP-слоем, не дублирует логику.
"""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User, UserBranch, UserRole
from app.modules.tenancy.models import Branch, Tenant


class TenancyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def slug_exists(self, slug: str) -> bool:
        return bool(await self.session.scalar(select(Tenant.id).where(Tenant.slug == slug)))

    async def list_tenants(self) -> list[Tenant]:
        result = await self.session.scalars(select(Tenant).order_by(Tenant.created_at.desc()))
        return list(result)

    async def _set_tenant_context(self, tenant_id: object) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    async def create_tenant_with_owner(
        self,
        *,
        tenant_name: str,
        tenant_slug: str,
        branch_name: str,
        branch_code: str,
        owner_email: str,
        owner_full_name: str,
        owner_password_hash: str,
    ) -> Tenant:
        tenant = Tenant(name=tenant_name, slug=tenant_slug)
        self.session.add(tenant)
        await self.session.flush()

        await self._set_tenant_context(tenant.id)

        branch = Branch(tenant_id=tenant.id, name=branch_name, code=branch_code)
        self.session.add(branch)
        await self.session.flush()

        owner = User(
            tenant_id=tenant.id,
            email=owner_email,
            full_name=owner_full_name,
            password_hash=owner_password_hash,
            role=UserRole.OWNER,
            is_active=True,
        )
        self.session.add(owner)
        await self.session.flush()

        self.session.add(UserBranch(user_id=owner.id, branch_id=branch.id))
        await self.session.flush()

        return tenant
