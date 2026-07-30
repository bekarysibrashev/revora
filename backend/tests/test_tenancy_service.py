from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.tenancy.service import TenancyService


class FakeTenancyRepository:
    def __init__(self):
        self.tenant = SimpleNamespace(
            id=uuid4(),
            slug="san-dental-test",
            name="SAN Dental Test",
        )
        self.deleted = None

    async def get_tenant(self, tenant_id):
        return self.tenant if tenant_id == self.tenant.id else None

    async def delete_tenant(self, tenant):
        self.deleted = tenant


@pytest.mark.asyncio
async def test_delete_tenant_requires_exact_slug_confirmation() -> None:
    repository = FakeTenancyRepository()
    service = TenancyService(repository)

    with pytest.raises(AppError) as error:
        await service.delete_tenant(repository.tenant.id, "wrong-slug")

    assert error.value.code == "TENANT_DELETE_CONFIRMATION_MISMATCH"
    assert repository.deleted is None


@pytest.mark.asyncio
async def test_delete_tenant_returns_deleted_identity() -> None:
    repository = FakeTenancyRepository()
    service = TenancyService(repository)

    response = await service.delete_tenant(
        repository.tenant.id,
        repository.tenant.slug,
    )

    assert response.deleted is True
    assert response.tenant_slug == "san-dental-test"
    assert repository.deleted is repository.tenant
