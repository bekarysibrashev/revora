"""Exercise actual loss SQL on a local migrated test database. Never commit data."""
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.models
from app.modules.losses.models import LossOpportunity
from app.modules.losses.repository import LossRepository
from app.modules.sales.models import Call
from app.modules.tenancy.models import Branch, Tenant


@pytest.mark.asyncio
async def test_real_callback_status_missing_price_and_branch_isolation():
    url = os.getenv("TEST_LOSS_DATABASE_URL")
    if not url:
        pytest.skip("requires a local migrated test database")
    target = make_url(url)
    assert target.host in {"127.0.0.1", "localhost"} and target.database.endswith("_test")
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session:
            tenant = Tenant(id=uuid4(), name="Synthetic", slug=str(uuid4()))
            session.add(tenant)
            await session.flush()
            await session.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant.id)})
            branches = [Branch(id=uuid4(), tenant_id=tenant.id, code=n, name=n) for n in ("A", "B")]
            session.add_all(branches)
            await session.flush()
            when = datetime(2026, 1, 1, 12, tzinfo=UTC)
            def add(branch, direction, outcome, seconds, minutes=0):
                session.add(Call(tenant_id=tenant.id, branch_id=branch.id, external_id=str(uuid4()),
                                 phone_hash=branch.code, direction=direction, outcome=outcome,
                                 duration_seconds=seconds, started_at=when + timedelta(minutes=minutes)))
            for branch in branches:
                add(branch, "in", " MISSED ", 20)
                add(branch, "out", "busy", 10, 1)
                add(branch, "in", "Success", 2, 2)
            await session.flush()
            repo = LossRepository(session)
            day = when.date()
            found = await repo.detect(tenant.id, day, day, None)
            assert {c.branch_id for c in found} == {b.id for b in branches}
            assert len(found) == 2 and all(c.estimated_amount == 0 for c in found)
            await repo.upsert(tenant.id, found, day, day)
            add(branches[0], "out", "Success", 15, 3)
            await session.flush()
            assert not await repo.detect(tenant.id, day, day, branches[0].id)
            assert await repo.dismiss_absent(tenant.id, [], day, day, branches[0].id) == 1
            rows = dict((await session.execute(select(LossOpportunity.branch_id, LossOpportunity.status)
                                               .where(LossOpportunity.tenant_id == tenant.id))).all())
            assert rows == {branches[0].id: "dismissed", branches[1].id: "open"}
    finally:
        await engine.dispose()
