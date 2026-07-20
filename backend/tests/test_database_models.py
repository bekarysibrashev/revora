from app.core.database import Base
import app.models  # noqa: F401


def test_core_model_registry_contains_expected_tables() -> None:
    assert {
        "tenants",
        "branches",
        "users",
        "user_branches",
        "refresh_tokens",
    }.issubset(Base.metadata.tables)


def test_tenant_scoped_tables_have_tenant_id() -> None:
    for table_name in ("branches", "users"):
        assert "tenant_id" in Base.metadata.tables[table_name].columns


def test_money_never_uses_float_in_registered_models() -> None:
    from sqlalchemy import Float

    assert not any(isinstance(column.type, Float) for table in Base.metadata.tables.values() for column in table.columns)


def test_domain_schema_is_registered() -> None:
    expected = {
        "patients", "leads", "calls", "appointments", "treatment_plans",
        "doctors", "doctor_compensation_rules", "doctor_ratings",
        "revenue_facts", "expense_facts", "raw_bank_transactions", "cash_flow_facts",
        "marketing_spend_facts", "attribution_facts", "integration_connections",
        "sync_runs", "ai_insights", "ai_insight_reads", "audit_log",
    }
    assert expected.issubset(Base.metadata.tables)


def test_ingestion_pipeline_schema_is_registered() -> None:
    expected = {
        "raw_records",
        "mapping_profiles",
        "normalization_errors",
        "record_lineage",
    }
    assert expected.issubset(Base.metadata.tables)
    assert Base.metadata.tables["raw_records"].c.payload.type.__class__.__name__ == "JSONB"
    assert "record_hash" in Base.metadata.tables["raw_records"].columns
    assert "mapping_profile_id" in Base.metadata.tables["record_lineage"].columns


def test_every_domain_table_is_tenant_scoped_or_a_scoped_join() -> None:
    exceptions = {"tenants", "user_branches", "refresh_tokens", "ai_insight_reads"}
    for name, table in Base.metadata.tables.items():
        if name not in exceptions:
            assert "tenant_id" in table.columns, name
