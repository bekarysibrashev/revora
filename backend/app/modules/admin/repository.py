"""Database operations for clinic administration."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import User, UserBranch, UserRole
from app.modules.tenancy.models import Branch


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_branches(self, tenant_id: UUID) -> list[Branch]:
        statement = (
            select(Branch)
            .where(Branch.tenant_id == tenant_id)
            .order_by(Branch.is_active.desc(), Branch.name.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def get_branch(self, tenant_id: UUID, branch_id: UUID) -> Branch | None:
        return await self.session.scalar(
            select(Branch).where(Branch.tenant_id == tenant_id, Branch.id == branch_id)
        )

    async def get_branch_by_code(self, tenant_id: UUID, code: str) -> Branch | None:
        return await self.session.scalar(
            select(Branch).where(Branch.tenant_id == tenant_id, Branch.code == code)
        )

    async def create_branch(
        self, *, tenant_id: UUID, name: str, code: str, address: str | None
    ) -> Branch:
        branch = Branch(tenant_id=tenant_id, name=name, code=code, address=address)
        self.session.add(branch)
        await self.session.flush()
        return branch

    async def save_branch(self, branch: Branch) -> Branch:
        await self.session.flush()
        return branch

    async def list_users(self, tenant_id: UUID) -> list[User]:
        return list(
            (
                await self.session.scalars(
                    select(User)
                    .options(selectinload(User.branch_links))
                    .where(User.tenant_id == tenant_id)
                    .order_by(User.full_name)
                )
            ).all()
        )

    async def get_user(self, tenant_id: UUID, user_id: UUID) -> User | None:
        return await self.session.scalar(
            select(User)
            .options(selectinload(User.branch_links))
            .where(User.tenant_id == tenant_id, User.id == user_id)
        )

    async def get_user_by_email(self, tenant_id: UUID, email: str) -> User | None:
        return await self.session.scalar(
            select(User).where(User.tenant_id == tenant_id, User.email == email)
        )

    async def existing_branch_ids(
        self, tenant_id: UUID, branch_ids: list[UUID]
    ) -> set[UUID]:
        if not branch_ids:
            return set()
        return set(
            (
                await self.session.scalars(
                    select(Branch.id).where(
                        Branch.tenant_id == tenant_id, Branch.id.in_(branch_ids)
                    )
                )
            ).all()
        )

    async def create_user(
        self,
        *,
        tenant_id: UUID,
        email: str,
        full_name: str,
        password_hash: str,
        role: UserRole,
        branch_ids: list[UUID],
    ) -> User:
        user = User(
            tenant_id=tenant_id,
            email=email,
            full_name=full_name,
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        user.branch_links = [UserBranch(branch_id=branch_id) for branch_id in branch_ids]
        self.session.add(user)
        await self.session.flush()
        return user

    async def replace_user_branches(self, user: User, branch_ids: list[UUID]) -> None:
        user.branch_links = [UserBranch(branch_id=branch_id) for branch_id in branch_ids]
        await self.session.flush()

    async def save_user(self, user: User) -> User:
        await self.session.flush()
        return user
