"""Timezone helpers for calendar periods selected in the clinic UI.

Timestamps remain ``TIMESTAMPTZ`` in PostgreSQL. A user-selected date such as
July 1, however, starts at midnight in the clinic rather than at midnight UTC.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


CLINIC_TIMEZONE = ZoneInfo("Asia/Almaty")


def clinic_day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=CLINIC_TIMEZONE)


def clinic_day_end_exclusive(value: date) -> datetime:
    return clinic_day_start(value + timedelta(days=1))
