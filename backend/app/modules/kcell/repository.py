"""Data access for Kcell extension assignments and their backfill.

Every statement here is filtered on tenant_id explicitly, on top of the
FORCE ROW LEVEL SECURITY the database already applies -- one clinic can
never read or write another clinic's extension mapping, and a backfill can
never reach across tenants.

The resolution rule this module enforces is the same one
app.modules.sales.lead_assignment applies to live traffic: a lead is given
an owner only when its Kcell history points at exactly one mapped
employee. Two extensions owned by two different people leave the lead
alone rather than picking one.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.kcell.models import KcellAssignmentAudit, KcellExtensionAssignment
from app.modules.sales.models import Call, Lead


class KcellAssignmentsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- reads -----------------------------------------------------------

    async def configured(self, tenant_id: UUID) -> list[KcellExtensionAssignment]:
        return list(
            (
                await self.session.scalars(
                    select(KcellExtensionAssignment)
                    .where(KcellExtensionAssignment.tenant_id == tenant_id)
                    .order_by(KcellExtensionAssignment.external_user)
                )
            ).all()
        )

    async def extensions_seen_in_calls(self, tenant_id: UUID) -> dict[str, int]:
        """Every extension Kcell has actually sent, with its call count.

        This is what makes an unconfigured extension visible at all: until
        someone maps it, its calls produce leads with no responsible
        employee and nothing in the UI would otherwise mention it.
        """
        rows = (
            await self.session.execute(
                select(Call.external_user, func.count(Call.id))
                .where(
                    Call.tenant_id == tenant_id,
                    Call.external_user.is_not(None),
                    Call.external_user != "",
                )
                .group_by(Call.external_user)
            )
        ).all()
        return {str(external_user): int(total) for external_user, total in rows}

    async def lead_counts_by_extension(
        self, tenant_id: UUID
    ) -> dict[str, tuple[int, int]]:
        """Per extension: (leads touched by it, of which have no owner).

        A lead is "touched by" an extension when some Kcell call from that
        extension shares the lead's phone_hash. One lead can be touched by
        several extensions, so these counts overlap by design -- they
        describe reach, not a partition.
        """

        async def counted(*extra_conditions) -> dict[str, int]:
            rows = (
                await self.session.execute(
                    select(Call.external_user, func.count(func.distinct(Lead.id)))
                    .select_from(Lead)
                    .join(
                        Call,
                        (Call.tenant_id == Lead.tenant_id)
                        & (Call.phone_hash == Lead.external_id),
                    )
                    .where(
                        Lead.tenant_id == tenant_id,
                        Call.external_user.is_not(None),
                        Call.external_user != "",
                        *extra_conditions,
                    )
                    .group_by(Call.external_user)
                )
            ).all()
            return {str(external_user): int(total) for external_user, total in rows}

        total_by_extension = await counted()
        ownerless_by_extension = await counted(Lead.assigned_user_id.is_(None))
        return {
            external_user: (total, ownerless_by_extension.get(external_user, 0))
            for external_user, total in total_by_extension.items()
        }

    async def users_by_id(self, tenant_id: UUID, ids: set[UUID]) -> dict[UUID, User]:
        if not ids:
            return {}
        rows = (
            await self.session.scalars(
                select(User).where(User.tenant_id == tenant_id, User.id.in_(ids))
            )
        ).all()
        return {user.id: user for user in rows}

    async def get_user(self, tenant_id: UUID, user_id: UUID) -> User | None:
        return await self.session.scalar(
            select(User).where(User.tenant_id == tenant_id, User.id == user_id)
        )

    async def get(
        self, tenant_id: UUID, external_user: str
    ) -> KcellExtensionAssignment | None:
        return await self.session.scalar(
            select(KcellExtensionAssignment).where(
                KcellExtensionAssignment.tenant_id == tenant_id,
                KcellExtensionAssignment.external_user == external_user,
            )
        )

    # --- writes ----------------------------------------------------------

    async def upsert(
        self, tenant_id: UUID, external_user: str, assigned_user_id: UUID | None
    ) -> tuple[KcellExtensionAssignment, UUID | None]:
        """Set or clear the owner of one extension. Returns the row and the
        owner it had before, so the caller can record an honest audit
        entry without querying twice."""
        existing = await self.get(tenant_id, external_user)
        if existing is not None:
            previous = existing.assigned_user_id
            existing.assigned_user_id = assigned_user_id
            await self.session.flush()
            return existing, previous

        row = KcellExtensionAssignment(
            tenant_id=tenant_id,
            external_user=external_user,
            assigned_user_id=assigned_user_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row, None

    async def remove(self, tenant_id: UUID, external_user: str) -> bool:
        result = await self.session.execute(
            delete(KcellExtensionAssignment).where(
                KcellExtensionAssignment.tenant_id == tenant_id,
                KcellExtensionAssignment.external_user == external_user,
            )
        )
        return bool(result.rowcount)

    async def record_audit(
        self,
        *,
        tenant_id: UUID,
        external_user: str,
        action: str,
        previous_assigned_user_id: UUID | None,
        new_assigned_user_id: UUID | None,
        changed_by_user_id: UUID | None,
        details: dict | None = None,
    ) -> None:
        self.session.add(
            KcellAssignmentAudit(
                tenant_id=tenant_id,
                external_user=external_user,
                action=action,
                previous_assigned_user_id=previous_assigned_user_id,
                new_assigned_user_id=new_assigned_user_id,
                changed_by_user_id=changed_by_user_id,
                details=details,
            )
        )

    async def audit_trail(
        self, tenant_id: UUID, limit: int = 100
    ) -> list[KcellAssignmentAudit]:
        return list(
            (
                await self.session.scalars(
                    select(KcellAssignmentAudit)
                    .where(KcellAssignmentAudit.tenant_id == tenant_id)
                    .order_by(KcellAssignmentAudit.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    # --- backfill --------------------------------------------------------

    def _ownerless_lead_candidates(self, tenant_id: UUID) -> Select:
        """Leads that could still gain a responsible employee, paired with
        every mapped extension that called them.

        A "won" lead is excluded for the same reason
        ContactRepository.sync_lead leaves one alone: it is already a
        patient, and retroactively assigning an owner to closed business is
        a separate decision this does not make.
        """
        return (
            select(Lead.id, KcellExtensionAssignment.assigned_user_id)
            .select_from(Lead)
            .join(
                Call,
                (Call.tenant_id == Lead.tenant_id)
                & (Call.phone_hash == Lead.external_id),
            )
            .join(
                KcellExtensionAssignment,
                (KcellExtensionAssignment.tenant_id == Lead.tenant_id)
                & (KcellExtensionAssignment.external_user == Call.external_user),
            )
            .where(
                Lead.tenant_id == tenant_id,
                Lead.assigned_user_id.is_(None),
                Lead.status != "won",
                KcellExtensionAssignment.assigned_user_id.is_not(None),
            )
            .distinct()
        )

    async def resolve_backfill_candidates(
        self, tenant_id: UUID
    ) -> tuple[dict[UUID, UUID], int]:
        """Split owner-less leads into (lead_id -> owner) and ambiguous.

        A lead reached by two mapped extensions belonging to two different
        employees is ambiguous and is returned only as a count: guessing
        which of them owns it is exactly the fuzzy matching this feature is
        forbidden from doing.
        """
        rows = (
            await self.session.execute(self._ownerless_lead_candidates(tenant_id))
        ).all()

        owners_by_lead: dict[UUID, set[UUID]] = {}
        for lead_id, assigned_user_id in rows:
            owners_by_lead.setdefault(lead_id, set()).add(assigned_user_id)

        resolvable: dict[UUID, UUID] = {}
        ambiguous = 0
        for lead_id, owners in owners_by_lead.items():
            if len(owners) == 1:
                resolvable[lead_id] = next(iter(owners))
            else:
                ambiguous += 1
        return resolvable, ambiguous

    async def count_ownerless_leads(self, tenant_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.tenant_id == tenant_id,
                    Lead.assigned_user_id.is_(None),
                    Lead.status != "won",
                )
            )
            or 0
        )

    async def apply_backfill(
        self, tenant_id: UUID, resolvable: dict[UUID, UUID]
    ) -> int:
        """Fill in owners, one lead at a time, never overwriting.

        The re-read of each Lead is deliberate: it re-checks
        assigned_user_id inside this transaction, so a live webhook that
        assigned an owner between the preview and the apply wins and is not
        clobbered by a stale plan.
        """
        if not resolvable:
            return 0
        updated = 0
        leads = (
            await self.session.scalars(
                select(Lead).where(
                    Lead.tenant_id == tenant_id, Lead.id.in_(list(resolvable))
                )
            )
        ).all()
        for lead in leads:
            if lead.assigned_user_id is not None or lead.status == "won":
                continue
            lead.assigned_user_id = resolvable[lead.id]
            updated += 1
        await self.session.flush()
        return updated

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)
