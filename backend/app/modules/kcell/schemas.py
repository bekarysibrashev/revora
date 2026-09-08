"""Request/response models for Kcell extension assignments.

Nothing here carries a phone number or a phone_hash. An administrator
configuring "which employee owns extension 101" needs the extension, the
employee and how many records the change would touch -- never a patient
identifier.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# Configured with a real employee / configured as deliberately ownerless /
# seen in calls but never configured. The third is the state that silently
# leaves every lead from that extension without a responsible employee.
AssignmentStatus = str


class KcellAssignmentItem(BaseModel):
    external_user: str
    status: AssignmentStatus  # assigned | ambiguous | unresolved
    assigned_user_id: UUID | None = None
    assigned_user_email: str | None = None
    assigned_user_name: str | None = None
    # How much history this extension actually accounts for, so an
    # administrator can tell a busy line from a stale one before deciding.
    calls_total: int = 0
    leads_total: int = 0
    leads_without_owner: int = 0
    updated_at: datetime | None = None


class KcellAssignmentListResponse(BaseModel):
    items: list[KcellAssignmentItem]
    total: int
    configured: int
    unresolved: int


class KcellAssignmentSetRequest(BaseModel):
    assigned_user_id: UUID


class KcellAssignmentAuditItem(BaseModel):
    external_user: str
    action: str
    previous_assigned_user_id: UUID | None = None
    new_assigned_user_id: UUID | None = None
    changed_by_user_id: UUID | None = None
    changed_by_email: str | None = None
    details: dict | None = None
    created_at: datetime


class KcellAssignmentAuditResponse(BaseModel):
    items: list[KcellAssignmentAuditItem]
    total: int


class KcellBackfillPreview(BaseModel):
    """What a backfill run would do, without doing it."""

    leads_without_owner: int = Field(
        description="Leads currently missing a responsible employee that "
        "this mapping could fill in."
    )
    leads_resolvable: int = Field(
        description="Of those, the ones whose Kcell history points at "
        "exactly one mapped employee. The rest stay untouched."
    )
    leads_ambiguous: int = Field(
        description="Leads whose calls came from several extensions owned "
        "by different employees. Never guessed at."
    )
    extensions_configured: int
    extensions_unresolved: int


class KcellBackfillResult(BaseModel):
    leads_updated: int
    leads_ambiguous: int
    leads_untouched: int
    extensions_applied: int
    finished_at: datetime
