"""Business rules for administering Kcell extension assignments.

This exists because the mapping used to be reachable only through
app.cli.manage_kcell_assignments, which needs a shell on the server. The
clinic's Render plan has no shell, so in practice the mapping could not be
configured at all -- and an unconfigured extension silently produces leads
with no responsible employee, live and historical alike.

The rules are deliberately narrow:

- Only an owner or manager may read or change the mapping. It decides who
  gets credited for revenue, so it is not an ordinary settings screen.
- An employee can only be chosen from this tenant's own users. A user id
  from another clinic is rejected as not found rather than 403, so this
  endpoint cannot be used to probe whether an id exists elsewhere.
- Nothing is ever inferred from a name. An extension is assigned, marked
  explicitly ambiguous, or left unconfigured -- and "unconfigured" and
  "ambiguous" stay different states, because only the first is a
  to-do item.
- The backfill only ever fills in a missing owner. It never overwrites an
  existing one, never touches a won lead, and never guesses when a lead's
  calls came from extensions belonging to different people.
"""

from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.kcell.repository import KcellAssignmentsRepository
from app.modules.kcell.schemas import (
    KcellAssignmentAuditItem,
    KcellAssignmentAuditResponse,
    KcellAssignmentItem,
    KcellAssignmentListResponse,
    KcellBackfillPreview,
    KcellBackfillResult,
)

ASSIGNED = "assigned"
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"


class KcellAssignmentsService:
    def __init__(self, repository: KcellAssignmentsRepository) -> None:
        self.repository = repository

    async def list_assignments(self, user: User) -> KcellAssignmentListResponse:
        self._require_manager(user)
        tenant_id = user.tenant_id

        configured = await self.repository.configured(tenant_id)
        calls_by_extension = await self.repository.extensions_seen_in_calls(tenant_id)
        leads_by_extension = await self.repository.lead_counts_by_extension(tenant_id)
        users = await self.repository.users_by_id(
            tenant_id,
            {row.assigned_user_id for row in configured if row.assigned_user_id},
        )

        items: list[KcellAssignmentItem] = []
        for row in configured:
            owner = users.get(row.assigned_user_id) if row.assigned_user_id else None
            leads_total, leads_without_owner = leads_by_extension.get(
                row.external_user, (0, 0)
            )
            items.append(
                KcellAssignmentItem(
                    external_user=row.external_user,
                    status=ASSIGNED if row.assigned_user_id else AMBIGUOUS,
                    assigned_user_id=row.assigned_user_id,
                    assigned_user_email=owner.email if owner else None,
                    assigned_user_name=owner.full_name if owner else None,
                    calls_total=calls_by_extension.get(row.external_user, 0),
                    leads_total=leads_total,
                    leads_without_owner=leads_without_owner,
                    updated_at=getattr(row, "updated_at", None),
                )
            )

        known = {row.external_user for row in configured}
        for external_user in sorted(set(calls_by_extension) - known):
            leads_total, leads_without_owner = leads_by_extension.get(
                external_user, (0, 0)
            )
            items.append(
                KcellAssignmentItem(
                    external_user=external_user,
                    status=UNRESOLVED,
                    calls_total=calls_by_extension[external_user],
                    leads_total=leads_total,
                    leads_without_owner=leads_without_owner,
                )
            )

        unresolved = sum(1 for item in items if item.status == UNRESOLVED)
        return KcellAssignmentListResponse(
            items=items,
            total=len(items),
            configured=len(configured),
            unresolved=unresolved,
        )

    async def set_assignment(
        self, user: User, external_user: str, assigned_user_id: UUID
    ) -> KcellAssignmentItem:
        self._require_manager(user)
        external_user = self._clean(external_user)

        owner = await self.repository.get_user(user.tenant_id, assigned_user_id)
        if owner is None:
            # Also the answer for a real user in another tenant: this
            # endpoint must not confirm that such an id exists.
            raise AppError("USER_NOT_FOUND", "Employee not found in this clinic", 404)
        if not owner.is_active:
            raise AppError(
                "USER_INACTIVE",
                "This employee is deactivated and cannot own an extension",
                422,
            )

        row, previous = await self.repository.upsert(
            user.tenant_id, external_user, owner.id
        )
        await self.repository.record_audit(
            tenant_id=user.tenant_id,
            external_user=external_user,
            action="set",
            previous_assigned_user_id=previous,
            new_assigned_user_id=owner.id,
            changed_by_user_id=user.id,
        )
        return KcellAssignmentItem(
            external_user=row.external_user,
            status=ASSIGNED,
            assigned_user_id=owner.id,
            assigned_user_email=owner.email,
            assigned_user_name=owner.full_name,
        )

    async def mark_ambiguous(self, user: User, external_user: str) -> KcellAssignmentItem:
        """Record that a human looked at this extension and it genuinely has
        no single owner -- a shared front-desk line, say. Different from
        never configuring it, which is an unfinished task."""
        self._require_manager(user)
        external_user = self._clean(external_user)

        row, previous = await self.repository.upsert(
            user.tenant_id, external_user, None
        )
        await self.repository.record_audit(
            tenant_id=user.tenant_id,
            external_user=external_user,
            action="mark_ambiguous",
            previous_assigned_user_id=previous,
            new_assigned_user_id=None,
            changed_by_user_id=user.id,
        )
        return KcellAssignmentItem(
            external_user=row.external_user, status=AMBIGUOUS
        )

    async def delete_assignment(self, user: User, external_user: str) -> None:
        self._require_manager(user)
        external_user = self._clean(external_user)

        existing = await self.repository.get(user.tenant_id, external_user)
        if existing is None:
            raise AppError("ASSIGNMENT_NOT_FOUND", "Extension is not configured", 404)
        previous = existing.assigned_user_id

        await self.repository.remove(user.tenant_id, external_user)
        await self.repository.record_audit(
            tenant_id=user.tenant_id,
            external_user=external_user,
            action="delete",
            previous_assigned_user_id=previous,
            new_assigned_user_id=None,
            changed_by_user_id=user.id,
        )

    async def preview_backfill(self, user: User) -> KcellBackfillPreview:
        """What applying the current mapping to old leads would change.

        Read-only on purpose: an administrator should be able to see the
        blast radius before pressing anything, especially since the
        alternative used to be a CLI they could not reach.
        """
        self._require_manager(user)
        resolvable, ambiguous = await self.repository.resolve_backfill_candidates(
            user.tenant_id
        )
        ownerless = await self.repository.count_ownerless_leads(user.tenant_id)
        configured = await self.repository.configured(user.tenant_id)
        calls_by_extension = await self.repository.extensions_seen_in_calls(
            user.tenant_id
        )
        known = {row.external_user for row in configured}
        return KcellBackfillPreview(
            leads_without_owner=ownerless,
            leads_resolvable=len(resolvable),
            leads_ambiguous=ambiguous,
            extensions_configured=len(configured),
            extensions_unresolved=len(set(calls_by_extension) - known),
        )

    async def run_backfill(self, user: User) -> KcellBackfillResult:
        self._require_manager(user)
        resolvable, ambiguous = await self.repository.resolve_backfill_candidates(
            user.tenant_id
        )
        ownerless_before = await self.repository.count_ownerless_leads(user.tenant_id)

        updated = await self.repository.apply_backfill(user.tenant_id, resolvable)
        await self.repository.record_audit(
            tenant_id=user.tenant_id,
            external_user="*",
            action="backfill",
            previous_assigned_user_id=None,
            new_assigned_user_id=None,
            changed_by_user_id=user.id,
            details={
                "leads_updated": updated,
                "leads_ambiguous": ambiguous,
                "leads_without_owner_before": ownerless_before,
            },
        )
        return KcellBackfillResult(
            leads_updated=updated,
            leads_ambiguous=ambiguous,
            leads_untouched=max(ownerless_before - updated, 0),
            extensions_applied=len(
                [row for row in await self.repository.configured(user.tenant_id)
                 if row.assigned_user_id is not None]
            ),
            finished_at=self.repository.now(),
        )

    async def audit_trail(self, user: User, limit: int = 100) -> KcellAssignmentAuditResponse:
        self._require_manager(user)
        rows = await self.repository.audit_trail(user.tenant_id, limit)
        actors = await self.repository.users_by_id(
            user.tenant_id,
            {row.changed_by_user_id for row in rows if row.changed_by_user_id},
        )
        items = [
            KcellAssignmentAuditItem(
                external_user=row.external_user,
                action=row.action,
                previous_assigned_user_id=row.previous_assigned_user_id,
                new_assigned_user_id=row.new_assigned_user_id,
                changed_by_user_id=row.changed_by_user_id,
                changed_by_email=(
                    actors[row.changed_by_user_id].email
                    if row.changed_by_user_id in actors
                    else None
                ),
                details=row.details,
                created_at=row.created_at,
            )
            for row in rows
        ]
        return KcellAssignmentAuditResponse(items=items, total=len(items))

    @staticmethod
    def _require_manager(user: User) -> None:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError(
                "FORBIDDEN", "You do not have permission for this action", 403
            )

    @staticmethod
    def _clean(external_user: str) -> str:
        value = (external_user or "").strip()
        if not value:
            raise AppError("INVALID_EXTENSION", "Extension must not be empty", 422)
        if len(value) > 150:
            raise AppError("INVALID_EXTENSION", "Extension is too long", 422)
        return value
