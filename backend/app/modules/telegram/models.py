"""Persistent Telegram staff identities, invitations, tasks and report schedules."""

from datetime import datetime, time
from enum import StrEnum
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.auth.models import UserRole


class TelegramTaskStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TelegramTaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TelegramReportCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class TelegramInvitation(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "telegram_invitations"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code_hint: Mapped[str] = mapped_column(String(12), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(30), nullable=False)
    branch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    linked_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramInviteRoute(TenantScopedMixin, Base):
    """Minimal global lookup. Full invitation remains protected by tenant RLS."""

    __tablename__ = "telegram_invite_routes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    invitation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("telegram_invitations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )


class TelegramEmployee(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "telegram_employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "linked_user_id", name="uq_telegram_employee_linked_user"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), index=True
    )
    linked_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    agent_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_chat_sessions.id", ondelete="SET NULL"), index=True
    )
    role: Mapped[UserRole] = mapped_column(String(30), nullable=False, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelegramEmployeeRoute(TenantScopedMixin, Base):
    """Global Telegram-id routing without exposing employee profile data."""

    __tablename__ = "telegram_employee_routes"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("telegram_employees.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )


class TelegramTask(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "telegram_tasks"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("telegram_employees.id", ondelete="CASCADE"), index=True
    )
    assigned_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[TelegramTaskPriority] = mapped_column(String(20), nullable=False)
    status: Mapped[TelegramTaskStatus] = mapped_column(String(20), nullable=False, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_note: Mapped[str | None] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_delivery_error: Mapped[str | None] = mapped_column(String(500))


class TelegramReportSubscription(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "telegram_report_subscriptions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", "cadence", name="uq_telegram_report_subscription"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("telegram_employees.id", ondelete="CASCADE"), index=True
    )
    cadence: Mapped[TelegramReportCadence] = mapped_column(String(20), nullable=False)
    local_time: Mapped[time] = mapped_column(Time(), nullable=False)
    weekday: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_period_key: Mapped[str | None] = mapped_column(String(20))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramAgentDraftStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TelegramAgentTaskDraft(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A write action proposed by AI but not executed until a leader confirms it."""

    __tablename__ = "telegram_agent_task_drafts"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    requested_by_employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("telegram_employees.id", ondelete="CASCADE"), index=True
    )
    assignee_employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("telegram_employees.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[TelegramTaskPriority] = mapped_column(String(20), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[TelegramAgentDraftStatus] = mapped_column(String(20), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("telegram_tasks.id", ondelete="SET NULL"), index=True
    )
