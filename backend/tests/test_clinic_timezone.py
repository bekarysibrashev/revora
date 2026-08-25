from datetime import date, timezone

from app.modules.finance.repository import FinanceRepository
from app.modules.sales.repository import SalesRepository


def test_finance_calendar_month_uses_clinic_timezone() -> None:
    start = FinanceRepository._start(date(2026, 7, 1))
    end = FinanceRepository._end_exclusive(date(2026, 7, 31))

    assert start.isoformat() == "2026-07-01T00:00:00+05:00"
    assert end.isoformat() == "2026-08-01T00:00:00+05:00"
    assert start.astimezone(timezone.utc).isoformat() == "2026-06-30T19:00:00+00:00"


def test_sales_uses_the_same_clinic_calendar_boundaries() -> None:
    assert SalesRepository._start(date(2026, 7, 1)) == FinanceRepository._start(
        date(2026, 7, 1)
    )
    assert SalesRepository._end(date(2026, 7, 31)) == FinanceRepository._end_exclusive(
        date(2026, 7, 31)
    )
