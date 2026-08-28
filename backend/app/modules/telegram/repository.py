"""Tenant-filtered persistence for Telegram administration."""

from datetime import UTC, datetime, time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import AuditLog
from app.modules.auth.models import UserRole
from app.modules.telegram.models import (
    TelegramEmployee,
    TelegramInvitation,
    TelegramInviteRoute,
    TelegramReportCadence,
    TelegramReportSubscription,
    TelegramTask,
    TelegramTaskPriority,
    TelegramTaskStatus,
)
from app.modules.tenancy.models import Branch


class TelegramRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_audit(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        action: str,
        entity_type: str,
        entity_id: UUID,
        changes: dict | None = None,
    ) -> None:
        self.session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                occurred_at=datetime.now(UTC),
                changes=changes,
            )
        )
        await self.session.flush()

    async def branch_exists(self, tenant_id: UUID, branch_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(Branch.id).where(
                    Branch.tenant_id == tenant_id,
                    Branch.id == branch_id,
                    Branch.is_active.is_(True),
                )
            )
        ) is not None

    async def create_invitation(
        self,
        *,
        tenant_id: UUID,
        code_hash: str,
        code_hint: str,
        role: UserRole,
        branch_id: UUID | None,
        created_by_user_id: UUID,
        expires_at: datetime,
        max_uses: int,
    ) -> TelegramInvitation:
        invitation = TelegramInvitation(
            tenant_id=tenant_id,
            code_hash=code_hash,
            code_hint=code_hint,
            role=role,
            branch_id=branch_id,
            created_by_user_id=created_by_user_id,
            expires_at=expires_at,
            max_uses=max_uses,
            uses=0,
        )
        self.session.add(invitation)
        await self.session.flush()
        self.session.add(
            TelegramInviteRoute(
                code_hash=code_hash,
                tenant_id=tenant_id,
                invitation_id=invitation.id,
            )
        )
        await self.session.flush()
        return invitation

    async def get_invitation(self, tenant_id: UUID, invitation_id: UUID) -> TelegramInvitation | None:
        return await self.session.scalar(
            select(TelegramInvitation).where(
                TelegramInvitation.tenant_id == tenant_id,
                TelegramInvitation.id == invitation_id,
            )
        )

    async def list_employees(self, tenant_id: UUID) -> list[TelegramEmployee]:
        return list(
            (
                await self.session.scalars(
                    select(TelegramEmployee)
                    .where(TelegramEmployee.tenant_id == tenant_id)
                    .order_by(TelegramEmployee.is_active.desc(), TelegramEmployee.full_name)
                )
            ).all()
        )

    async def get_employee(self, tenant_id: UUID, employee_id: UUID) -> TelegramEmployee | None:
        return await self.session.scalar(
            select(TelegramEmployee).where(
                TelegramEmployee.tenant_id == tenant_id,
                TelegramEmployee.id == employee_id,
            )
        )

    async def create_task(
        self,
        *,
        tenant_id: UUID,
        employee_id: UUID,
        assigned_by_user_id: UUID,
        title: str,
        description: str,
        priority: TelegramTaskPriority,
        due_at: datetime | None,
    ) -> TelegramTask:
        task = TelegramTask(
            tenant_id=tenant_id,
            employee_id=employee_id,
            assigned_by_user_id=assigned_by_user_id,
            title=title,
            description=description,
            priority=priority,
            status=TelegramTaskStatus.PENDING,
            due_at=due_at,
            delivery_attempts=0,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def list_tasks(self, tenant_id: UUID, limit: int = 100) -> list[TelegramTask]:
        return list(
            (
                await self.session.scalars(
                    select(TelegramTask)
                    .where(TelegramTask.tenant_id == tenant_id)
                    .order_by(TelegramTask.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def get_task(self, tenant_id: UUID, task_id: UUID) -> TelegramTask | None:
        return await self.session.scalar(
            select(TelegramTask).where(
                TelegramTask.tenant_id == tenant_id,
                TelegramTask.id == task_id,
            )
        )

    async def upsert_subscription(
        self,
        *,
        tenant_id: UUID,
        employee_id: UUID,
        cadence: TelegramReportCadence,
        local_time: time,
        weekday: int | None,
        is_active: bool,
    ) -> TelegramReportSubscription:
        subscription = await self.session.scalar(
            select(TelegramReportSubscription).where(
                TelegramReportSubscription.tenant_id == tenant_id,
                TelegramReportSubscription.employee_id == employee_id,
                TelegramReportSubscription.cadence == cadence,
            )
        )
        if subscription is None:
            subscription = TelegramReportSubscription(
                tenant_id=tenant_id,
                employee_id=employee_id,
                cadence=cadence,
                local_time=local_time,
                weekday=weekday,
                is_active=is_active,
            )
            self.session.add(subscription)
        else:
            subscription.local_time = local_time
            subscription.weekday = weekday
            subscription.is_active = is_active
        await self.session.flush()
        return subscription
