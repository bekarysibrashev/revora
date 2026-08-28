from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.telegram.models import TelegramEmployee, TelegramTask, TelegramTaskPriority, TelegramTaskStatus
from app.modules.telegram.schemas import InvitationCreateRequest, TaskCreateRequest
from app.modules.telegram.service import TelegramService


class FakeTelegramRepository:
    def __init__(self) -> None:
        self.employees: list[TelegramEmployee] = []
        self.invitation_args = None
        self.audits = []

    async def add_audit(self, **kwargs):
        self.audits.append(kwargs)

    async def branch_exists(self, tenant_id, branch_id):
        return True

    async def create_invitation(self, **kwargs):
        self.invitation_args = kwargs
        return type("Invitation", (), {"id": uuid4(), **kwargs})()

    async def get_employee(self, tenant_id, employee_id):
        return next((item for item in self.employees if item.id == employee_id), None)

    async def create_task(self, **kwargs):
        now = datetime.now(UTC)
        return TelegramTask(
            id=uuid4(),
            status=TelegramTaskStatus.PENDING,
            delivered_at=None,
            accepted_at=None,
            completed_at=None,
            completion_note=None,
            created_at=now,
            updated_at=now,
            **kwargs,
        )


def actor(role: UserRole) -> User:
    return User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="leader@example.test",
        full_name="Leader",
        password_hash="unused",
        role=role,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_invitation_code_is_random_and_only_hash_is_persisted() -> None:
    repository = FakeTelegramRepository()
    owner = actor(UserRole.OWNER)

    response = await TelegramService(repository).create_invitation(
        owner, InvitationCreateRequest(role=UserRole.MANAGER)
    )

    assert response.code.startswith("RV-")
    assert response.code not in repository.invitation_args.values()
    assert len(repository.invitation_args["code_hash"]) == 64
    assert repository.invitation_args["tenant_id"] == owner.tenant_id


@pytest.mark.asyncio
async def test_branch_role_requires_branch_in_invitation() -> None:
    with pytest.raises(AppError, match="requires a branch") as error:
        await TelegramService(FakeTelegramRepository()).create_invitation(
            actor(UserRole.OWNER),
            InvitationCreateRequest(role=UserRole.ADMINISTRATOR),
        )

    assert error.value.code == "BRANCH_REQUIRED"


@pytest.mark.asyncio
async def test_manager_can_assign_task_to_active_employee() -> None:
    repository = FakeTelegramRepository()
    manager = actor(UserRole.MANAGER)
    now = datetime.now(UTC)
    employee = TelegramEmployee(
        id=uuid4(), tenant_id=manager.tenant_id, branch_id=None, role=UserRole.MANAGER,
        telegram_user_id=10, telegram_chat_id=10, username=None, full_name="Worker",
        is_active=True, registered_at=now, last_seen_at=now, created_at=now, updated_at=now,
    )
    repository.employees.append(employee)

    response = await TelegramService(repository).create_task(
        manager,
        TaskCreateRequest(
            employee_id=employee.id,
            title="Проверить отчёт",
            description="Сверить показатели за день",
            priority=TelegramTaskPriority.HIGH,
            due_at=now + timedelta(hours=2),
        ),
    )

    assert response.employee_id == employee.id
    assert response.status == TelegramTaskStatus.PENDING


def test_task_deadline_must_include_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        TaskCreateRequest(
            employee_id=uuid4(),
            title="Проверка",
            description="Описание",
            due_at=datetime(2026, 8, 29, 10, 0),
        )
