"""Run integration coverage only against an explicitly disposable empty DB."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import migration_schema


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = json.loads((ROOT / "migration_schema/legacy_tables.json").read_text())


def test_legacy_migrations_do_not_import_live_models():
    for path in (ROOT / "alembic/versions").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "Base.metadata" not in source, path.name
        assert "import app.models" not in source, path.name


@pytest.mark.parametrize("revision,table,fields", [
    ("20260718_0003", "patients", ["branch_id", "first_visit_at", "last_visit_at", "visit_count", "is_active"]),
    ("20260718_0003", "leads", ["last_contact_at", "attribution_data"]),
    ("20260718_0003", "attribution_facts", ["attribution_data"]),
    ("20260729_0014", "whatsapp_messages", ["delivery_attempts", "next_delivery_at", "media_ciphertext", "transcription_status"]),
])
def test_later_columns_are_not_created_early(revision, table, fields):
    ddl = "\n".join(SNAPSHOTS[revision][table])
    for field in fields:
        assert field not in ddl


def test_frozen_ddl_executes_without_live_models(monkeypatch):
    statements = []
    monkeypatch.setattr(migration_schema.op, "execute", lambda sql: statements.append(str(sql)))
    migration_schema.create_table("20260718_0003", "patients")
    assert statements == SNAPSHOTS["20260718_0003"]["patients"]
    assert "FOREIGN KEY" in statements[0]
    assert any("ix_patients_phone_hash" in sql for sql in statements)


def test_unknown_snapshot_fails_closed():
    with pytest.raises(KeyError):
        migration_schema.create_table("unknown", "patients")


@pytest.mark.skipif(not os.environ.get("TEST_MIGRATION_DATABASE_URL"), reason="requires disposable PostgreSQL")
def test_empty_database_incremental_upgrade_and_retry():
    url = os.environ["TEST_MIGRATION_DATABASE_URL"]
    parsed = sa.engine.make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"}, "test must run locally"
    assert parsed.database.endswith("_migration_test"), "use an explicitly named disposable database"

    async def inspect_empty():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                tables = await conn.run_sync(lambda sync: sa.inspect(sync).get_table_names())
                assert not tables, "refusing to migrate a non-empty database"
        finally:
            await engine.dispose()
    asyncio.run(inspect_empty())

    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test"}
    def migrate(target):
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", target],
                                cwd=ROOT, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    migrate("20260903_0034")
    tenant_id, patient_id = uuid.uuid4(), uuid.uuid4()
    async def insert_old_patient():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                columns = await conn.run_sync(lambda sync: {col["name"] for col in sa.inspect(sync).get_columns("patients")})
                assert "branch_id" not in columns
                await conn.execute(sa.text("INSERT INTO tenants(id,name,slug) VALUES(:id,'Synthetic test','migration-test')"), {"id": tenant_id})
                await conn.execute(sa.text("SELECT set_config('app.tenant_id', :id, true)"), {"id": str(tenant_id)})
                await conn.execute(sa.text("INSERT INTO patients(id,tenant_id,external_id) VALUES(:id,:tenant,'synthetic-only')"), {"id": patient_id, "tenant": tenant_id})
        finally:
            await engine.dispose()
    asyncio.run(insert_old_patient())
    migrate("head")
    migrate("head")

    async def verify():
        from app.core.database import Base
        import app.models
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars().all() == ["20260911_0040"]
                row = (await conn.execute(sa.text("SELECT external_id, visit_count, is_active FROM patients WHERE id=:id"), {"id": patient_id})).one()
                assert tuple(row) == ("synthetic-only", 0, True)
                def schema_check(sync):
                    inspector = sa.inspect(sync)
                    for name, table in Base.metadata.tables.items():
                        actual = {col["name"] for col in inspector.get_columns(name)}
                        assert {col.name for col in table.columns} <= actual, name
                    indexes = {index["name"] for index in inspector.get_indexes("patients")}
                    assert {"ix_patients_branch_id", "ix_patients_last_visit_at"} <= indexes
                    assert any(fk["constrained_columns"] == ["branch_id"] and fk["referred_table"] == "branches" for fk in inspector.get_foreign_keys("patients"))
                await conn.run_sync(schema_check)
                for table in ("patients", "leads", "whatsapp_messages", "whatsapp_qr_sessions", "whatsapp_gateway_health"):
                    flags = (await conn.execute(sa.text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:name)"), {"name": table})).one()
                    assert tuple(flags) == (True, True), table
                    assert (await conn.execute(sa.text("SELECT count(*) FROM pg_policies WHERE tablename=:name AND policyname='tenant_isolation'"), {"name": table})).scalar_one() == 1
        finally:
            await engine.dispose()
    asyncio.run(verify())
