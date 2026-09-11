from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.integrations.canonical_writer import CanonicalWriteError, CanonicalWriter


def test_nearest_appointment_selects_branch_for_unmapped_revenue() -> None:
    branch_a = uuid4()
    branch_b = uuid4()
    occurred_at = datetime(2026, 7, 20, 12, tzinfo=UTC)

    result = CanonicalWriter._select_nearest_branch(
        [
            (branch_a, occurred_at - timedelta(days=10)),
            (branch_b, occurred_at - timedelta(hours=2)),
        ],
        occurred_at,
    )

    assert result == branch_b


def test_equal_distance_between_branches_is_not_guessed() -> None:
    branch_a = uuid4()
    branch_b = uuid4()
    occurred_at = datetime(2026, 7, 20, 12, tzinfo=UTC)

    result = CanonicalWriter._select_nearest_branch(
        [
            (branch_a, occurred_at - timedelta(hours=1)),
            (branch_b, occurred_at + timedelta(hours=1)),
        ],
        occurred_at,
    )

    assert result is None


def test_integer_accepts_integral_1c_json_numbers() -> None:
    assert CanonicalWriter._integer({"visit_count": 12}, "visit_count") == 12
    assert CanonicalWriter._integer({"visit_count": "12.0"}, "visit_count") == 12


def test_integer_rejects_fractional_values() -> None:
    with pytest.raises(CanonicalWriteError, match="must be an integer"):
        CanonicalWriter._integer({"visit_count": "12.5"}, "visit_count")


@pytest.mark.asyncio
async def test_patient_phone_hash_converts_matching_lead_to_won() -> None:
    session = AsyncMock()
    writer = CanonicalWriter(session)
    patient_id = uuid4()
    branch_id = uuid4()
    writer._upsert = AsyncMock(return_value=patient_id)
    writer._optional_branch_id = AsyncMock(return_value=branch_id)

    result = await writer._write_patient(
        uuid4(),
        {
            "external_id": "patient-guid",
            "phone_hash": "a" * 64,
            "is_active": True,
        },
    )

    assert result == patient_id
    statement = session.execute.await_args.args[0]
    assert "UPDATE leads" in str(statement)


@pytest.mark.asyncio
async def test_salary_cannot_be_duplicated_through_expense_import() -> None:
    writer = CanonicalWriter(AsyncMock())

    with pytest.raises(CanonicalWriteError, match="payroll_fact"):
        await writer._write_expense_fact(
            uuid4(),
            {
                "external_id": "salary-2026-08",
                "occurred_on": "2026-08-31",
                "amount": "100000",
                "category_name": "Начисление зарплаты",
            },
        )
