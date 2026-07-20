"""Bootstrap the first tenant, branch and owner on an empty database."""

import argparse
import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.core.security import hash_password
from app.modules.auth.models import User, UserBranch, UserRole
from app.modules.auth.repository import AuthRepository
from app.modules.tenancy.models import Branch, Tenant


async def create_initial_owner(args: argparse.Namespace) -> None:
    async with AsyncSessionFactory() as session, session.begin():
        if await session.scalar(select(Tenant.id).where(Tenant.slug == args.tenant_slug)):
            raise SystemExit(f"Tenant slug already exists: {args.tenant_slug}")

        tenant = Tenant(name=args.tenant_name, slug=args.tenant_slug)
        session.add(tenant)
        await session.flush()
        await AuthRepository(session).set_tenant_context(tenant.id)

        branch = Branch(tenant_id=tenant.id, name=args.branch_name, code=args.branch_code)
        session.add(branch)
        await session.flush()

        owner = User(
            tenant_id=tenant.id,
            email=args.email.lower().strip(),
            full_name=args.full_name.strip(),
            password_hash=hash_password(args.password),
            role=UserRole.OWNER,
            is_active=True,
        )
        session.add(owner)
        await session.flush()
        session.add(UserBranch(user_id=owner.id, branch_id=branch.id))

    print(f"Created tenant '{tenant.slug}' and owner '{owner.email}'.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--branch-name", required=True)
    parser.add_argument("--branch-code", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    if len(args.password) < 8:
        parser.error("--password must contain at least 8 characters")
    return args


if __name__ == "__main__":
    asyncio.run(create_initial_owner(parse_args()))
