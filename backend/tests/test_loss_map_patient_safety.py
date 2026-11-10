from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.data_protection import decrypt_sensitive_text, encrypt_sensitive_text
from app.modules.losses.repository import latest_event_per_episode


@dataclass
class Event:
    patient_id: str
    starts_at: datetime


def test_phone_is_reversible_only_with_the_configured_data_key() -> None:
    key = "patient-phone-test-key-with-sufficient-length"
    encrypted = encrypt_sensitive_text("+77013676707", key, setting_name="PATIENT_DATA_KEY")

    assert encrypted != "+77013676707"
    assert decrypt_sensitive_text(encrypted, key, setting_name="PATIENT_DATA_KEY") == "+77013676707"


def test_repeated_cancellations_become_one_latest_patient_case() -> None:
    older = Event("patient-1", datetime(2026, 9, 2, tzinfo=UTC))
    latest = Event("patient-1", datetime(2026, 9, 9, tzinfo=UTC))
    other = Event("patient-2", datetime(2026, 9, 3, tzinfo=UTC))

    result = latest_event_per_episode(
        [older, latest, other],
        episode_key=lambda event: event.patient_id,
        occurred_at=lambda event: event.starts_at,
    )

    assert result == [latest, other]
