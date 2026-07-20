from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook

from app.modules.finance.schemas import AnalyticsMeta, CashFlowResponse, PnlResponse
from app.modules.reports.exporter import export_cashflow, export_pnl


def meta():
    return AnalyticsMeta(
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 31),
        branch_id=None,
        data_as_of=datetime(2026, 7, 20, 12, tzinfo=UTC),
    )


def pnl():
    return PnlResponse(
        revenue_accrual=Decimal("1000000"),
        revenue_payment=Decimal("900000"),
        variable_expenses=Decimal("200000"),
        fixed_expenses=Decimal("300000"),
        uncategorized_expenses=Decimal("50000"),
        total_expenses=Decimal("550000"),
        gross_profit=Decimal("800000"),
        ebitda=Decimal("450000"),
        net_profit=Decimal("450000"),
        meta=meta(),
    )


def test_pnl_xlsx_contains_typed_financial_values() -> None:
    content = export_pnl(pnl(), "xlsx")
    workbook = load_workbook(BytesIO(content), data_only=True)
    sheet = workbook["Report"]

    assert sheet["A1"].value == "Profit and Loss"
    assert sheet["A8"].value == "Revenue (accrual)"
    assert sheet["B8"].value == 1000000
    assert sheet["B8"].number_format != "General"


def test_cashflow_pdf_is_a_nonempty_pdf() -> None:
    report = CashFlowResponse(
        inflow=Decimal("950000"),
        outflow=Decimal("650000"),
        net_cash_flow=Decimal("300000"),
        closing_balance=Decimal("1200000"),
        meta=meta(),
    )

    content = export_cashflow(report, "pdf")

    assert content.startswith(b"%PDF")
    assert len(content) > 1500
