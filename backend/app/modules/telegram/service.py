"""Authorization and business rules for the Telegram staff channel."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import secrets
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.telegram.models import TelegramTaskStatus
from app.modules.telegram.repository import TelegramRepository
from app.modules.telegram.schemas import (
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeUpdateRequest,
    InvitationCreateRequest,
    InvitationResponse,
    ReportSubscriptionRequest,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
)


class TelegramService:
    def __init__(self, repository: TelegramRepository) -> None:
        self.repository = repository

    async def create_invitation(
        self, actor: User, payload: InvitationCreateRequest
    ) -> InvitationResponse:
        self._require_owner(actor)
        self._validate_role_branch(payload.role, payload.branch_id)
        if payload.branch_id and not await self.repository.branch_exists(actor.tenant_id, payload.branch_id):
            raise AppError("BRANCH_NOT_FOUND", "Branch not found", 404)
        await self._validate_linked_user(
            actor.tenant_id, payload.role, payload.linked_user_id, payload.branch_id,
            required_for_leader=True
        )
        if payload.linked_user_id and payload.max_uses != 1:
            raise AppError(
                "LINKED_INVITATION_SINGLE_USE",
                "An invitation linked to a Revora user must be single-use",
                422,
            )

        code = f"RV-{secrets.token_urlsafe(18)}"
        code_hash = sha256(code.encode("utf-8")).hexdigest()
        invitation = await self.repository.create_invitation(
            tenant_id=actor.tenant_id,
            code_hash=code_hash,
            code_hint=code[-6:],
            role=payload.role,
            branch_id=payload.branch_id,
            linked_user_id=payload.linked_user_id,
            created_by_user_id=actor.id,
            expires_at=datetime.now(UTC) + timedelta(hours=payload.expires_in_hours),
            max_uses=payload.max_uses,
        )
        await self.repository.add_audit(
            tenant_id=actor.tenant_id,
            actor_user_id=actor.id,
            action="telegram.invitation.created",
            entity_type="telegram_invitation",
            entity_id=invitation.id,
            changes={
                "role": payload.role.value,
                "branch_id": str(payload.branch_id) if payload.branch_id else None,
                "linked_user_id": str(payload.linked_user_id) if payload.linked_user_id else None,
            },
        )
        return InvitationResponse(
            id=invitation.id,
            code=code,
            code_hint=invitation.code_hint,
            role=invitation.role,
            branch_id=invitation.branch_id,
            linked_user_id=invitation.linked_user_id,
            expires_at=invitation.expires_at,
            max_uses=invitation.max_uses,
        )

    async def revoke_invitation(self, actor: User, invitation_id: UUID) -> None:
        self._require_owner(actor)
        invitation = await self.repository.get_invitation(actor.tenant_id, invitation_id)
        if invitation is None:
            raise AppError("INVITATION_NOT_FOUND", "Invitation not found", 404)
        invitation.revoked_at = datetime.now(UTC)
        await self.repository.add_audit(
            tenant_id=actor.tenant_id,
            actor_user_id=actor.id,
            action="telegram.invitation.revoked",
            entity_type="telegram_invitation",
            entity_id=invitation.id,
        )

    async def list_employees(self, actor: User) -> EmployeeListResponse:
        self._require_leader(actor)
        employees = await self.repository.list_employees(actor.tenant_id)
        items = [EmployeeResponse.model_validate(employee) for employee in employees]
        return EmployeeListResponse(items=items, total=len(items))

    async def update_employee(
        self, actor: User, employee_id: UUID, payload: EmployeeUpdateRequest
    ) -> EmployeeResponse:
        self._require_owner(actor)
        employee = await self.repository.get_employee(actor.tenant_id, employee_id)
        if employee is None:
            raise AppError("TELEGRAM_EMPLOYEE_NOT_FOUND", "Telegram employee not found", 404)
        next_role = payload.role or employee.role
        next_branch = payload.branch_id if "branch_id" in payload.model_fields_set else employee.branch_id
        next_linked_user = (
            payload.linked_user_id
            if "linked_user_id" in payload.model_fields_set
            else employee.linked_user_id
        )
        self._validate_role_branch(next_role, next_branch)
        if next_branch and not await self.repository.branch_exists(actor.tenant_id, next_branch):
            raise AppError("BRANCH_NOT_FOUND", "Branch not found", 404)
        await self._validate_linked_user(
            actor.tenant_id, next_role, next_linked_user, next_branch,
            required_for_leader=False,
            current_employee_id=employee.id,
        )
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(employee, field, value)
        await self.repository.add_audit(
            tenant_id=actor.tenant_id,
            actor_user_id=actor.id,
            action="telegram.employee.updated",
            entity_type="telegram_employee",
            entity_id=employee.id,
            changes=payload.model_dump(mode="json", exclude_unset=True),
        )
        return EmployeeResponse.model_validate(employee)

    async def create_task(self, actor: User, payload: TaskCreateRequest) -> TaskResponse:
        self._require_leader(actor)
        employee = await self.repository.get_employee(actor.tenant_id, payload.employee_id)
        if employee is None or not employee.is_active:
            raise AppError("TELEGRAM_EMPLOYEE_NOT_FOUND", "Active Telegram employee not found", 404)
        allowed_branches = {link.branch_id for link in actor.branch_links}
        if actor.role == UserRole.MANAGER and allowed_branches and employee.branch_id not in allowed_branches:
            raise AppError("BRANCH_FORBIDDEN", "Employee is outside your branch scope", 403)
        if payload.due_at and payload.due_at <= datetime.now(UTC):
            raise AppError("TASK_DUE_AT_INVALID", "due_at must be in the future", 422)
        task = await self.repository.create_task(
            tenant_id=actor.tenant_id,
            employee_id=employee.id,
            assigned_by_user_id=actor.id,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            due_at=payload.due_at,
        )
        await self.repository.add_audit(
            tenant_id=actor.tenant_id,
            actor_user_id=actor.id,
            action="telegram.task.created",
            entity_type="telegram_task",
            entity_id=task.id,
            changes={"employee_id": str(employee.id), "priority": payload.priority.value},
        )
        return TaskResponse.model_validate(task)

    async def list_tasks(self, actor: User) -> TaskListResponse:
        self._require_leader(actor)
        tasks = await self.repository.list_tasks(actor.tenant_id)
        items = [TaskResponse.model_validate(task) for task in tasks]
        return TaskListResponse(items=items, total=len(items))

    async def cancel_task(self, actor: User, task_id: UUID) -> TaskResponse:
        self._require_leader(actor)
        task = await self.repository.get_task(actor.tenant_id, task_id)
        if task is None:
            raise AppError("TELEGRAM_TASK_NOT_FOUND", "Telegram task not found", 404)
        if task.status == TelegramTaskStatus.COMPLETED:
            raise AppError("TASK_ALREADY_COMPLETED", "Completed task cannot be cancelled", 409)
        task.status = TelegramTaskStatus.CANCELLED
        await self.repository.add_audit(
            tenant_id=actor.tenant_id,
            actor_user_id=actor.id,
            action="telegram.task.cancelled",
            entity_type="telegram_task",
            entity_id=task.id,
        )
        return TaskResponse.model_validate(task)

    async def configure_report(
        self,
        actor: User,
        employee_id: UUID,
        payload: ReportSubscriptionRequest,
    ) -> None:
        self._require_owner(actor)
        employee = await self.repository.get_employee(actor.tenant_id, employee_id)
        if employee is None or employee.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("REPORT_RECIPIENT_INVALID", "Reports can be sent only to a leader", 422)
        await self.repository.upsert_subscription(
            tenant_id=actor.tenant_id,
            employee_id=employee_id,
            cadence=payload.cadence,
            local_time=payload.local_time,
            weekday=payload.weekday,
            is_active=payload.is_active,
        )
        await self.repository.add_audit(
            tenant_id=actor.tenant_id,
            actor_user_id=actor.id,
            action="telegram.report.configured",
            entity_type="telegram_employee",
            entity_id=employee.id,
            changes=payload.model_dump(mode="json"),
        )

    @staticmethod
    def _require_owner(actor: User) -> None:
        if actor.role != UserRole.OWNER:
            raise AppError("FORBIDDEN", "Only the owner can perform this action", 403)

    @staticmethod
    def _require_leader(actor: User) -> None:
        if actor.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("FORBIDDEN", "Only a clinic leader can perform this action", 403)

    @staticmethod
    def _validate_role_branch(role: UserRole, branch_id: UUID | None) -> None:
        if role in {UserRole.ADMINISTRATOR, UserRole.SALES_MANAGER} and branch_id is None:
            raise AppError("BRANCH_REQUIRED", "This role requires a branch", 422)

    async def _validate_linked_user(
        self,
        tenant_id: UUID,
        role: UserRole,
        linked_user_id: UUID | None,
        branch_id: UUID | None,
        *,
        required_for_leader: bool,
        current_employee_id: UUID | None = None,
    ) -> None:
        if role in {UserRole.OWNER, UserRole.MANAGER} and linked_user_id is None:
            if required_for_leader:
                raise AppError(
                    "REVORA_USER_REQUIRED",
                    "A leader invitation must be linked to a Revora user",
                    422,
                )
            return
        if linked_user_id is None:
            return
        linked_user = await self.repository.get_user(tenant_id, linked_user_id)
        if linked_user is None or not linked_user.is_active:
            raise AppError("REVORA_USER_NOT_FOUND", "Active Revora user not found", 404)
        if linked_user.role != role:
            raise AppError(
                "REVORA_USER_ROLE_MISMATCH",
                "Telegram role must match the linked Revora user role",
                422,
            )
        linked_branches = {link.branch_id for link in linked_user.branch_links}
        if linked_branches and role != UserRole.OWNER and branch_id is not None and branch_id not in linked_branches:
            raise AppError(
                "BRANCH_FORBIDDEN",
                "Telegram branch is outside the linked Revora user scope",
                403,
            )
        existing = await self.repository.get_employee_by_linked_user(tenant_id, linked_user_id)
        if existing is not None and existing.id != current_employee_id:
            raise AppError(
                "REVORA_USER_ALREADY_LINKED",
                "This Revora user is already linked to Telegram",
                409,
            )
