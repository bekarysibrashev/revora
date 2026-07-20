"""Authentication policy: credentials, token issue, rotation and revocation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import create_access_token, generate_refresh_token, hash_token, verify_password
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import TokenResponse, UserResponse


class AuthService:
    def __init__(self, repository: AuthRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    @staticmethod
    def _user_response(user: User) -> UserResponse:
        return UserResponse(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            branch_ids=[link.branch_id for link in user.branch_links],
        )

    async def login(self, tenant_slug: str, email: str, password: str) -> TokenResponse:
        tenant = await self.repository.get_tenant_by_slug(tenant_slug)
        if tenant is None:
            raise AppError("INVALID_CREDENTIALS", "Invalid credentials", 401)

        await self.repository.set_tenant_context(tenant.id)
        user = await self.repository.get_user_by_email(tenant.id, email)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise AppError("INVALID_CREDENTIALS", "Invalid credentials", 401)
        return await self._issue_pair(user)

    async def refresh(self, raw_token: str) -> TokenResponse:
        stored = await self.repository.get_refresh_token(hash_token(raw_token))
        now = datetime.now(UTC)
        if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
            raise AppError("INVALID_REFRESH_TOKEN", "Invalid or expired refresh token", 401)

        await self.repository.set_tenant_context(stored.tenant_id)
        user = await self.repository.get_user_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise AppError("INVALID_REFRESH_TOKEN", "Invalid or expired refresh token", 401)

        response, replacement = await self._issue_pair_with_record(user)
        await self.repository.revoke_token(stored, replacement.id)
        return response

    async def logout(self, raw_token: str) -> None:
        stored = await self.repository.get_refresh_token(hash_token(raw_token))
        if stored is not None and stored.revoked_at is None:
            await self.repository.revoke_token(stored)

    async def _issue_pair(self, user: User) -> TokenResponse:
        response, _ = await self._issue_pair_with_record(user)
        return response

    async def _issue_pair_with_record(self, user: User) -> tuple[TokenResponse, RefreshToken]:
        branch_ids = [link.branch_id for link in user.branch_links]
        access_token, expires_at = create_access_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role=user.role.value,
            branch_ids=branch_ids,
            settings=self.settings,
        )
        raw_refresh = generate_refresh_token()
        refresh_record = await self.repository.create_refresh_token(
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(UTC) + timedelta(days=self.settings.refresh_token_expire_days),
        )
        return (
            TokenResponse(
                access_token=access_token,
                refresh_token=raw_refresh,
                expires_at=expires_at,
                user=self._user_response(user),
            ),
            refresh_record,
        )
