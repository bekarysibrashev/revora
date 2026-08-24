from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.integrations.canonical_writer import CanonicalWriter


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
