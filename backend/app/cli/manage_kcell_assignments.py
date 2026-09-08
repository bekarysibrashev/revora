"""Admin CLI to manage the explicit Call.external_user (Kcell agent
extension) -> User mapping used to resolve a Lead's assigned_user_id.

That resolution itself lives in app.modules.sales.lead_assignment and is
shared by both consumers of this table: the live inbound path
(ContactRepository.sync_lead, reached from both the Kcell and WhatsApp
webhooks) for every new contact from here on, and app.cli.backfill_leads
for historical contacts that predate it. Configuring an extension here
takes effect for both -- there is only one mapping, read the same way by
both paths.

The kcell_extension_assignments table is otherwise unreachable: nothing in
Revora's product UI writes to it, and it has FORCE ROW LEVEL SECURITY, so
without this command there is genuinely no way to configure it -- an
unconfigured extension's calls simply keep resolving to assigned_user_id
None, live or backfilled, no matter how completely the rest of the sync
pipeline works.

Usage:
    # See both what's already configured and what still needs to be, before
    # touching anything. Run this first.
    python -m app.cli.manage_kcell_assignments list --tenant-slug san-dental

    # Map one extension to one Revora user (must already exist, same tenant).
    python -m app.cli.manage_kcell_assignments set --tenant-slug san-dental \\
        --external-user 101 --user-email doctor@example.com

    # Explicitly mark a shared/no-single-owner line (e.g. a front-desk
    # extension) so it reads as "ambiguous" rather than "never configured".
    python -m app.cli.manage_kcell_assignments mark-ambiguous \\
        --tenant-slug san-dental --external-user front-desk

    # Remove a mapping entirely (reverts to "unresolved").
    python -m app.cli.manage_kcell_assignments delete \\
        --tenant-slug san-dental --external-user 101

Run `list` again after any `set`/`mark-ambiguous`/`delete` -- and, in
particular, before ever running app.cli.backfill_leads -- so every extension
Kcell has actually sent calls from is either mapped or deliberately marked
ambiguous. See tools/revora_1c_extension/README-v18.1-complete-sync.md for
the exact setup sequence to follow before a production backfill.

Rules:
- Every subcommand resolves --tenant-slug to a tenant_id via
  AuthRepository.get_tenant_by_slug (the tenants table itself carries no
  tenant_id column and no RLS -- see tenancy/repository.py), then
  immediately calls AuthRepository.set_tenant_context(tenant_id) before any
  further, RLS-protected query -- the same requirement app.cli.backfill_leads
  documents and follows, and for the same reason: FORCE ROW LEVEL SECURITY
  on kcell_extension_assignments, calls and users means a query issued
  without app.tenant_id set would silently see zero rows instead of raising.
- `set` resolves --user-email through AuthRepository.get_user_by_email
  scoped to that same tenant_id. A user that exists but belongs to a
  different tenant is indistinguishable from "no such user" by this lookup
  -- this command can never point assigned_user_id at a user outside the
  extension's own tenant. There is no way to override this.
- No fuzzy matching anywhere: --external-user must match Call.external_user
  byte-for-byte; --user-email must match a real User row exactly (modulo the
  same lower/strip normalization create_initial_owner.py already applies at
  signup). Nothing here ever guesses a mapping from a name.
- Never prints a phone number or any other patient/contact PII. The only
  values ever printed are: Kcell's own raw extension identifiers (an
  internal operator/line label, not a contact's phone -- see
  kcell/models.py::KcellExtensionAssignment's docstring) and Revora user
  emails (internal staff, already visible to whoever is running this
  command).
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionFactory
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.kcell.models import KcellExtensionAssignment
from app.modules.sales.models import Call


async def _resolve_tenant_id(session: AsyncSession, tenant_slug: str) -> UUID:
    tenant = await AuthRepository(session).get_tenant_by_slug(tenant_slug)
    if tenant is None:
        raise SystemExit(f"Unknown or inactive tenant slug: {tenant_slug}")
    return tenant.id


async def cmd_list(session: AsyncSession, tenant_id: UUID) -> None:
    await AuthRepository(session).set_tenant_context(tenant_id)

    configured = (
        await session.execute(
            select(KcellExtensionAssignment.external_user, KcellExtensionAssignment.assigned_user_id)
            .where(KcellExtensionAssignment.tenant_id == tenant_id)
            .order_by(KcellExtensionAssignment.external_user)
        )
    ).all()

    assigned_ids = {assigned_user_id for _, assigned_user_id in configured if assigned_user_id is not None}
    user_emails: dict[UUID, str] = {}
    if assigned_ids:
        rows = (await session.execute(select(User.id, User.email).where(User.id.in_(assigned_ids)))).all()
        user_emails = dict(rows)

    print("Configured extensions:")
    if not configured:
        print("  (none)")
    for external_user, assigned_user_id in configured:
        if assigned_user_id is None:
            print(f"  {external_user}: ambiguous (explicitly marked, no single owner)")
        else:
            print(f"  {external_user}: {user_emails.get(assigned_user_id, '<user not found>')}")

    seen = (
        await session.execute(
            select(Call.external_user)
            .where(Call.tenant_id == tenant_id, Call.external_user.is_not(None))
            .distinct()
        )
    ).scalars().all()
    configured_externals = {external_user for external_user, _ in configured}
    unconfigured = sorted(set(seen) - configured_externals)

    print("Seen in calls but not yet configured (assignment_status=unresolved until set):")
    if not unconfigured:
        print("  (none)")
    for external_user in unconfigured:
        print(f"  {external_user}")


async def cmd_set(session: AsyncSession, tenant_id: UUID, external_user: str, user_email: str) -> None:
    await AuthRepository(session).set_tenant_context(tenant_id)
    user = await AuthRepository(session).get_user_by_email(tenant_id, user_email.lower().strip())
    if user is None:
        raise SystemExit(
            f"No user with email {user_email!r} found in this tenant -- "
            "refusing to assign a cross-tenant or nonexistent user."
        )
    statement = (
        pg_insert(KcellExtensionAssignment)
        .values(id=uuid4(), tenant_id=tenant_id, external_user=external_user, assigned_user_id=user.id)
        .on_conflict_do_update(
            index_elements=["tenant_id", "external_user"],
            set_={"assigned_user_id": user.id},
        )
    )
    await session.execute(statement)
    print(f"{external_user} -> {user.email}")


async def cmd_mark_ambiguous(session: AsyncSession, tenant_id: UUID, external_user: str) -> None:
    await AuthRepository(session).set_tenant_context(tenant_id)
    statement = (
        pg_insert(KcellExtensionAssignment)
        .values(id=uuid4(), tenant_id=tenant_id, external_user=external_user, assigned_user_id=None)
        .on_conflict_do_update(
            index_elements=["tenant_id", "external_user"],
            set_={"assigned_user_id": None},
        )
    )
    await session.execute(statement)
    print(f"{external_user} marked ambiguous (no single owner).")


async def cmd_delete(session: AsyncSession, tenant_id: UUID, external_user: str) -> None:
    await AuthRepository(session).set_tenant_context(tenant_id)
    result = await session.execute(
        delete(KcellExtensionAssignment).where(
            KcellExtensionAssignment.tenant_id == tenant_id,
            KcellExtensionAssignment.external_user == external_user,
        )
    )
    if result.rowcount:
        print(f"Deleted mapping for {external_user}.")
    else:
        print(f"No mapping existed for {external_user} -- nothing to delete.")


async def _run(args: argparse.Namespace) -> None:
    async with AsyncSessionFactory() as session, session.begin():
        tenant_id = await _resolve_tenant_id(session, args.tenant_slug)
        if args.command == "list":
            await cmd_list(session, tenant_id)
        elif args.command == "set":
            await cmd_set(session, tenant_id, args.external_user, args.user_email)
        elif args.command == "mark-ambiguous":
            await cmd_mark_ambiguous(session, tenant_id, args.external_user)
        elif args.command == "delete":
            await cmd_delete(session, tenant_id, args.external_user)
        else:  # pragma: no cover -- argparse's required=True subparsers enforce this
            raise SystemExit(f"Unknown command: {args.command}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def _add_tenant_and_external_user(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--tenant-slug", required=True)
        sub.add_argument("--external-user", required=True, help="Call.external_user's raw value, exact match")

    list_parser = subparsers.add_parser("list", help="Show configured and unconfigured extensions")
    list_parser.add_argument("--tenant-slug", required=True)

    set_parser = subparsers.add_parser("set", help="Map one extension to one existing user")
    _add_tenant_and_external_user(set_parser)
    set_parser.add_argument("--user-email", required=True)

    mark_parser = subparsers.add_parser("mark-ambiguous", help="Mark an extension as shared/no single owner")
    _add_tenant_and_external_user(mark_parser)

    delete_parser = subparsers.add_parser("delete", help="Remove a mapping (reverts to unresolved)")
    _add_tenant_and_external_user(delete_parser)

    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_run(parse_args()))
