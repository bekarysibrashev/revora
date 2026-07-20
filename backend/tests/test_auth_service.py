from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password, hash_token
from app.modules.auth.models import RefreshToken, User, UserBranch, UserRole
from app.modules.auth.service import AuthService
from app.modules.tenancy.models import Tenant


class FakeAuthRepository:
    def __init__(self, user: User) -> None:
        self.user = user
        self.tenant = Tenant(id=user.tenant_id, slug="san-dental", name="SAN Dental")
        self.tokens: dict[str, RefreshToken] = {}
        self.context = None

    async def get_tenant_by_slug(self, slug: str):
        return self.tenant if slug == self.tenant.slug else None

    async def set_tenant_context(self, tenant_id):
        self.context = tenant_id

    async def get_user_by_email(self, tenant_id, email):
        return self.user if tenant_id == self.user.tenant_id and email == self.user.email else None

    async def get_user_by_id(self, user_id):
        return self.user if user_id == self.user.id else None

    async def create_refresh_token(self, *, tenant_id, user_id, token_hash, expires_at):
        record = RefreshToken(
            id=uuid4(), tenant_id=tenant_id, user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
        self.tokens[token_hash] = record
        return record

    async def get_refresh_token(self, token_hash):
        return self.tokens.get(token_hash)

    async def revoke_token(self, token, replacement_id=None):
        token.revoked_at = datetime.now(UTC)
        token.replaced_by_id = replacement_id


@pytest.fixture
def auth_service():
    branch_id = uuid4()
    user = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="owner@example.test",
        full_name="Clinic Owner",
        password_hash=hash_password("secure-password"),
        role=UserRole.OWNER,
        is_active=True,
    )
    user.branch_links = [UserBranch(user_id=user.id, branch_id=branch_id)]
    repository = FakeAuthRepository(user)
    settings = Settings(_env_file=None, jwt_secret_key="test-auth-secret")
    return AuthService(repository, settings), repository


@pytest.mark.asyncio
async def test_login_issues_pair_and_stores_only_refresh_hash(auth_service) -> None:
    service, repository = auth_service

    response = await service.login("san-dental", "owner@example.test", "secure-password")

    assert response.user.role == UserRole.OWNER
    assert response.refresh_token not in repository.tokens
    assert hash_token(response.refresh_token) in repository.tokens


@pytest.mark.asyncio
async def test_refresh_rotates_and_revokes_previous_token(auth_service) -> None:
    service, repository = auth_service
    first = await service.login("san-dental", "owner@example.test", "secure-password")
    old_record = repository.tokens[hash_token(first.refresh_token)]

    second = await service.refresh(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    assert old_record.revoked_at is not None
    assert old_record.replaced_by_id == repository.tokens[hash_token(second.refresh_token)].id


@pytest.mark.asyncio
async def test_invalid_credentials_do_not_reveal_which_field_failed(auth_service) -> None:
    service, _ = auth_service

    with pytest.raises(AppError) as error:
        await service.login("san-dental", "owner@example.test", "wrong-password")

    assert error.value.code == "INVALID_CREDENTIALS"
    assert error.value.status_code == 401
