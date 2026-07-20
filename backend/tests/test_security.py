from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.security import (
    InvalidAccessToken,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_access_token_contains_tenant_role_and_branches() -> None:
    settings = Settings(_env_file=None, jwt_secret_key="test-secret-with-enough-entropy")
    user_id, tenant_id, branch_id = uuid4(), uuid4(), uuid4()
    token, _ = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="manager",
        branch_ids=[branch_id],
        settings=settings,
    )

    payload = decode_access_token(token, settings)

    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "manager"
    assert payload["branch_ids"] == [str(branch_id)]


def test_access_token_cannot_be_verified_with_another_secret() -> None:
    issuer = Settings(_env_file=None, jwt_secret_key="issuer-secret")
    verifier = Settings(_env_file=None, jwt_secret_key="different-secret")
    token, _ = create_access_token(
        user_id=uuid4(), tenant_id=uuid4(), role="owner", branch_ids=[], settings=issuer
    )

    with pytest.raises(InvalidAccessToken):
        decode_access_token(token, verifier)


def test_refresh_tokens_are_random_and_only_hash_is_stable() -> None:
    first, second = generate_refresh_token(), generate_refresh_token()

    assert first != second
    assert hash_token(first) == hash_token(first)
    assert first not in hash_token(first)
