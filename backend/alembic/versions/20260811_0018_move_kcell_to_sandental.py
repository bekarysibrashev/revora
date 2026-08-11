"""Move confirmed Kcell history from test1 to sandental once.

Revision ID: 20260811_0018
Revises: 20260811_0017
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260811_0018"
down_revision: str | None = "20260811_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This data migration was explicitly approved for the production clinic.
    # Alembic records the revision, so it executes only once. Only calls with
    # accepted Kcell history receipts are selected; demo calls remain in test1.
    op.execute("SET LOCAL row_security = off")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM tenants WHERE slug = 'test1' AND is_active IS TRUE)
               AND NOT EXISTS (SELECT 1 FROM tenants WHERE slug = 'sandental' AND is_active IS TRUE)
            THEN
                RAISE EXCEPTION 'Kcell target tenant sandental does not exist or is inactive';
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE revora_kcell_calls_to_move ON COMMIT DROP AS
        SELECT DISTINCT calls.id, calls.external_id
        FROM calls
        JOIN kcell_webhook_receipts receipts
          ON receipts.tenant_id = calls.tenant_id
         AND receipts.call_id = calls.external_id
         AND receipts.command = 'history'
        JOIN tenants source_tenant ON source_tenant.id = calls.tenant_id
        WHERE source_tenant.slug = 'test1'
        """
    )
    op.execute(
        """
        DELETE FROM kcell_webhook_receipts source_receipts
        USING tenants source_tenant, tenants target_tenant
        WHERE source_tenant.slug = 'test1'
          AND target_tenant.slug = 'sandental'
          AND source_receipts.tenant_id = source_tenant.id
          AND EXISTS (
            SELECT 1
            FROM kcell_webhook_receipts target_receipts
            WHERE target_receipts.tenant_id = target_tenant.id
              AND target_receipts.call_id = source_receipts.call_id
              AND target_receipts.command = source_receipts.command
          )
        """
    )
    op.execute(
        """
        UPDATE kcell_webhook_receipts receipts
        SET tenant_id = target_tenant.id, updated_at = now()
        FROM tenants source_tenant, tenants target_tenant
        WHERE source_tenant.slug = 'test1'
          AND target_tenant.slug = 'sandental'
          AND receipts.tenant_id = source_tenant.id
          AND receipts.command = 'history'
        """
    )
    op.execute(
        """
        DELETE FROM calls source_calls
        USING revora_kcell_calls_to_move selected, tenants target_tenant
        WHERE source_calls.id = selected.id
          AND target_tenant.slug = 'sandental'
          AND EXISTS (
            SELECT 1 FROM calls target_calls
            WHERE target_calls.tenant_id = target_tenant.id
              AND target_calls.external_id = selected.external_id
          )
        """
    )
    op.execute(
        """
        UPDATE calls source_calls
        SET tenant_id = target_tenant.id, updated_at = now()
        FROM revora_kcell_calls_to_move selected, tenants source_tenant, tenants target_tenant
        WHERE source_calls.id = selected.id
          AND source_calls.tenant_id = source_tenant.id
          AND source_tenant.slug = 'test1'
          AND target_tenant.slug = 'sandental'
        """
    )
    op.execute(
        """
        UPDATE call_quality_analyses analyses
        SET tenant_id = target_tenant.id,
            rule_set_id = COALESCE(
                (
                    SELECT rules.id
                    FROM call_quality_rule_sets rules
                    WHERE rules.tenant_id = target_tenant.id AND rules.is_active IS TRUE
                    ORDER BY rules.version DESC
                    LIMIT 1
                ),
                analyses.rule_set_id
            ),
            updated_at = now()
        FROM revora_kcell_calls_to_move selected, tenants target_tenant
        WHERE analyses.call_id = selected.id
          AND target_tenant.slug = 'sandental'
        """
    )


def downgrade() -> None:
    # Irreversible by design: after the migration, new Kcell callbacks and the
    # confirmed history belong to one tenant and must not be split again.
    pass
