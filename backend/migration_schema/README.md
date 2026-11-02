# Frozen legacy migration tables

The Render clean deployment on 2026-11-02 failed in revision 0035 because
revision 0003 imported current ORM models and had already created `patients.branch_id`.
The same drift affected lead fields, attribution metadata and WhatsApp delivery columns.

`legacy_tables.json` freezes the DDL that the nine ORM-backed revisions otherwise
generated at commit `ee9071b4e7aecce95a4d8d113d70c54b32bbce45`. Fields owned by the
unconditional later revisions 0035, lead-funnel 0036, 0039 and 0040 are excluded
from the earlier table definitions. The original additive revisions now run normally.
Foreign keys, indexes and all existing RLS policy statements are retained.

This is a compatibility baseline, not a claim to reconstruct every historical
schema exactly. Already-applied revisions are not rerun. No stamping, truncation,
schema reset, disabled RLS or duplicate-column exception suppression is used.
Do not regenerate these snapshots when application models change. Add a migration.

Test with an **empty local disposable database**, whose name ends in `_migration_test`:

```
TEST_MIGRATION_DATABASE_URL=postgresql+asyncpg://.../revora_migration_test
python -m pytest tests/test_frozen_migrations.py -q
```

The integration test refuses non-local/non-empty databases, upgrades to 0034,
inserts a synthetic patient, upgrades to head twice, verifies preservation,
all ORM table/column availability, patient foreign key/indexes, and forced RLS.
The known pre-existing `alembic check` drift consists of ten missing indexes in
the handwritten AI-chat/call-quality migrations, not missing columns or tables.
