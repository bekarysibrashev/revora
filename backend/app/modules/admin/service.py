"""Business rules for clinic administration."""

from uuid import UUID

from app.core.errors import AppError
from app.modules.admin.repository import AdminRepository
from app.modules.admin.schemas import (
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
    BranchCreateRequest,
    BranchListResponse,
    BranchResponse,
    BranchUpdateRequest,
)
from app.modules.auth.models import User, UserRole
from app.core.security import hash_password


class AdminService:
    def __init__(self, repository: AdminRepository) -> None:
        self.repository = repository

    async def list_branches(self, user: User) -> BranchListResponse:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("FORBIDDEN", "You do not have permission for this action", 403)

        branches = await self.repository.list_branches(user.tenant_id)
        items = [BranchResponse.model_validate(branch) for branch in branches]
        return BranchListResponse(items=items, total=len(items))

    async def create_branch(
        self, user: User, payload: BranchCreateRequest
    ) -> BranchResponse:
        self._require_owner(user)
        if await self.repository.get_branch_by_code(user.tenant_id, payload.code):
            raise AppError("BRANCH_CODE_EXISTS", "A branch with this code already exists", 409)

        branch = await self.repository.create_branch(
            tenant_id=user.tenant_id,
            name=payload.name,
            code=payload.code,
            address=payload.address,
        )
        return BranchResponse.model_validate(branch)

    async def update_branch(
        self, user: User, branch_id: UUID, payload: BranchUpdateRequest
    ) -> BranchResponse:
        self._require_owner(user)
        branch = await self.repository.get_branch(user.tenant_id, branch_id)
        if branch is None:
            raise AppError("BRANCH_NOT_FOUND", "Branch not found", 404)

        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(branch, field, value)
        branch = await self.repository.save_branch(branch)
        return BranchResponse.model_validate(branch)

    @staticmethod
    def _require_owner(user: User) -> None:
        if user.role != UserRole.OWNER:
            raise AppError("FORBIDDEN", "Only the owner can perform this admin action", 403)

    async def list_users(self, actor: User) -> AdminUserListResponse:
        self._require_owner(actor)
        users = await self.repository.list_users(actor.tenant_id)
        items = [self._user_response(user) for user in users]
        return AdminUserListResponse(items=items, total=len(items))

    async def create_user(
        self, actor: User, payload: AdminUserCreateRequest
    ) -> AdminUserResponse:
        self._require_owner(actor)
        if await self.repository.get_user_by_email(actor.tenant_id, payload.email):
            raise AppError("USER_EMAIL_EXISTS", "A user with this email already exists", 409)
        await self._validate_branch_ids(actor.tenant_id, payload.role, payload.branch_ids)
        user = await self.repository.create_user(
            tenant_id=actor.tenant_id,
            email=payload.email,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
            role=payload.role,
            branch_ids=payload.branch_ids,
        )
        return self._user_response(user)

    async def update_user(
        self, actor: User, user_id: UUID, payload: AdminUserUpdateRequest
    ) -> AdminUserResponse:
        self._require_owner(actor)
        user = await self.repository.get_user(actor.tenant_id, user_id)
        if user is None:
            raise AppError("USER_NOT_FOUND", "User not found", 404)
        if user.id == actor.id and payload.is_active is False:
            raise AppError("CANNOT_DEACTIVATE_SELF", "You cannot deactivate your own account", 409)
        next_role = payload.role or user.role
        next_branch_ids = (
            payload.branch_ids
            if payload.branch_ids is not None
            else [link.branch_id for link in user.branch_links]
        )
        await self._validate_branch_ids(actor.tenant_id, next_role, next_branch_ids)
        if payload.full_name is not None:
            user.full_name = payload.full_name
        if payload.password is not None:
            user.password_hash = hash_password(payload.password)
        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active
        if payload.branch_ids is not None:
            await self.repository.replace_user_branches(user, payload.branch_ids)
        user = await self.repository.save_user(user)
        return self._user_response(user)

    async def _validate_branch_ids(
        self, tenant_id: UUID, role: UserRole, branch_ids: list[UUID]
    ) -> None:
        unique_ids = set(branch_ids)
        if len(unique_ids) != len(branch_ids):
            raise AppError("DUPLICATE_BRANCH", "branch_ids must be unique", 422)
        if role in {UserRole.ADMINISTRATOR, UserRole.SALES_MANAGER} and not branch_ids:
            raise AppError("BRANCH_REQUIRED", "This role requires at least one branch", 422)
        existing = await self.repository.existing_branch_ids(tenant_id, branch_ids)
        if existing != unique_ids:
            raise AppError("BRANCH_NOT_FOUND", "One or more branches do not exist", 422)

    @staticmethod
    def _user_response(user: User) -> AdminUserResponse:
        return AdminUserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            branch_ids=[link.branch_id for link in user.branch_links],
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
