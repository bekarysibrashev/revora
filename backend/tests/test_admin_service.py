from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.admin.schemas import BranchCreateRequest, BranchUpdateRequest
from app.modules.admin.service import AdminService
from app.modules.auth.models import User, UserRole
from app.modules.tenancy.models import Branch


class FakeAdminRepository:
    def __init__(self, branches: list[Branch]) -> None:
        self.branches = branches
        self.requested_tenant_id = None

    async def list_branches(self, tenant_id):
        self.requested_tenant_id = tenant_id
        return self.branches

    async def get_branch(self, tenant_id, branch_id):
        return next(
            (
                branch
                for branch in self.branches
                if branch.tenant_id == tenant_id and branch.id == branch_id
            ),
            None,
        )

    async def get_branch_by_code(self, tenant_id, code):
        return next(
            (
                branch
                for branch in self.branches
                if branch.tenant_id == tenant_id and branch.code == code
            ),
            None,
        )

    async def create_branch(self, *, tenant_id, name, code, address):
        now = datetime.now(UTC)
        branch = Branch(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            code=code,
            address=address,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.branches.append(branch)
        return branch

    async def save_branch(self, branch):
        branch.updated_at = datetime.now(UTC)
        return branch


def make_user(role: UserRole) -> User:
    return User(
        id=uuid4(),
        tenant_id=uuid4(),
        email=f"{role.value}@example.test",
        full_name="Test User",
        password_hash="unused",
        role=role,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_owner_can_list_tenant_branches() -> None:
    user = make_user(UserRole.OWNER)
    now = datetime.now(UTC)
    branch = Branch(
        id=uuid4(),
        tenant_id=user.tenant_id,
        name="SAN Seifullina",
        code="seifullina",
        address="Seifullina 1",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    repository = FakeAdminRepository([branch])

    response = await AdminService(repository).list_branches(user)

    assert repository.requested_tenant_id == user.tenant_id
    assert response.total == 1
    assert response.items[0].code == "seifullina"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.ADMINISTRATOR, UserRole.SALES_MANAGER])
async def test_branch_list_rejects_roles_without_admin_access(role: UserRole) -> None:
    service = AdminService(FakeAdminRepository([]))

    with pytest.raises(AppError) as error:
        await service.list_branches(make_user(role))

    assert error.value.code == "FORBIDDEN"
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_create_branch() -> None:
    user = make_user(UserRole.OWNER)
    service = AdminService(FakeAdminRepository([]))

    response = await service.create_branch(
        user,
        BranchCreateRequest(name="SAN Abaya", code="abaya", address="Abaya 10"),
    )

    assert response.name == "SAN Abaya"
    assert response.code == "abaya"
    assert response.is_active is True


@pytest.mark.asyncio
async def test_duplicate_branch_code_is_rejected() -> None:
    user = make_user(UserRole.OWNER)
    now = datetime.now(UTC)
    existing = Branch(
        id=uuid4(),
        tenant_id=user.tenant_id,
        name="SAN Abaya",
        code="abaya",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    service = AdminService(FakeAdminRepository([existing]))

    with pytest.raises(AppError) as error:
        await service.create_branch(
            user, BranchCreateRequest(name="Another", code="abaya")
        )

    assert error.value.code == "BRANCH_CODE_EXISTS"
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_owner_can_deactivate_branch() -> None:
    user = make_user(UserRole.OWNER)
    now = datetime.now(UTC)
    branch = Branch(
        id=uuid4(),
        tenant_id=user.tenant_id,
        name="SAN Seifullina",
        code="seifullina",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    service = AdminService(FakeAdminRepository([branch]))

    response = await service.update_branch(
        user, branch.id, BranchUpdateRequest(is_active=False)
    )

    assert response.is_active is False


@pytest.mark.asyncio
async def test_manager_cannot_change_branches() -> None:
    service = AdminService(FakeAdminRepository([]))

    with pytest.raises(AppError) as error:
        await service.create_branch(
            make_user(UserRole.MANAGER),
            BranchCreateRequest(name="SAN Abaya", code="abaya"),
        )

    assert error.value.code == "FORBIDDEN"
    assert error.value.status_code == 403
