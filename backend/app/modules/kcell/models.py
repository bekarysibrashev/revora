"""Audit record of every accepted Kcell callback (without storing its secret token)."""
from uuid import UUID
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

class KcellWebhookReceipt(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "kcell_webhook_receipts"
    __table_args__ = (UniqueConstraint("tenant_id", "call_id", "command"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    call_id: Mapped[str] = mapped_column(String(200), index=True)
    command: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB)


class KcellExtensionAssignment(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Explicit, administrator-maintained mapping from a raw Kcell
    agent/extension identifier (Call.external_user -- exactly the string
    Kcell's own webhook sends, see kcell/router.py) to a real Revora User.
    Call.external_user is never resolved to a User anywhere else in the
    codebase (ai/call_quality/service.py uses it only as an opaque
    display/group-by label), so there is nothing to backfill a responsible
    employee from except this table.

    A missing row for a given (tenant_id, external_user) means the mapping
    has genuinely never been configured -- callers (see
    app.cli.backfill_leads) treat this as "unresolved", not as "no
    employee". A row that exists but has assigned_user_id = NULL is a
    deliberate, explicit marker that an administrator reviewed this
    extension and confirmed it has no single owner (e.g. a shared
    front-desk line) -- callers treat this as "ambiguous", a different and
    more informative case than "never configured".

    Never populated by approximate/fuzzy full-name matching -- only by an
    administrator (or a future explicit import) entering a real,
    unambiguous extension-to-user pairing.
    """

    __tablename__ = "kcell_extension_assignments"
    __table_args__ = (UniqueConstraint("tenant_id", "external_user"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    external_user: Mapped[str] = mapped_column(String(150), index=True)
    assigned_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)


class KcellAssignmentAudit(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Who changed a Kcell extension mapping, when, and what it was before.

    The mapping decides which employee a lead is attributed to, so it is
    exactly the kind of setting people later disagree about. Every write
    through the API leaves a row here, including the backfill runs that
    apply a mapping to leads created before it existed.

    Deliberately stores no phone number and no phone_hash: an audit trail
    of configuration changes never needs patient identifiers, and the
    counts in `details` are enough to reconstruct what a change did.
    """

    __tablename__ = "kcell_assignment_audits"
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    external_user: Mapped[str] = mapped_column(String(150), index=True)
    # set | mark_ambiguous | delete | backfill
    action: Mapped[str] = mapped_column(String(30))
    previous_assigned_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    new_assigned_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    details: Mapped[dict | None] = mapped_column(JSONB)
