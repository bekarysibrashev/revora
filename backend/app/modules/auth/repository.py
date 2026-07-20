"""Database operations for authentication; no policy decisions."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import RefreshToken, User
from app.modules.tenancy.models import Tenant


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        return await self.session.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True)))

    async def set_tenant_context(self, tenant_id: UUID) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    async def get_user_by_email(self, tenant_id: UUID, email: str) -> User | None:
        statement = (
            select(User)
            .options(selectinload(User.branch_links))
            .where(User.tenant_id == tenant_id, User.email == email)
        )
        return await self.session.scalar(statement)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return await self.session.scalar(
            select(User).options(selectinload(User.branch_links)).where(User.id == user_id)
        )

    async def create_refresh_token(
        self, *, tenant_id: UUID, user_id: UUID, token_hash: str, expires_at: datetime
    ) -> RefreshToken:
        token = RefreshToken(
            tenant_id=tenant_id, user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )

    async def revoke_token(self, token: RefreshToken, replacement_id: UUID | None = None) -> None:
        token.revoked_at = datetime.now(UTC)
        token.replaced_by_id = replacement_id
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
