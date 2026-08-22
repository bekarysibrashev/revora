from decimal import Decimal

from app.modules.integrations.one_c_finance import (
    EXPENSE_ENTITY,
    MONEY_ENTITY,
    REVENUE_ENTITY,
    SALES_ENTITY,
    PAYROLL_ENTITY,
    normalize_one_c_finance_record,
)


def test_revenue_register_becomes_payment() -> None:
    result = normalize_one_c_finance_record(
        source_entity=REVENUE_ENTITY,
        source_record_id="doc|2026-08-01|1",
        branch_code="main",
        payload={
            "Period": "2026-08-01T12:00:00",
            "Сумма": 140000,
            "ВидОперации": "ВзносНаЛицевойСчет",
            "Active": True,
        },
    )

    assert result is not None and result.is_valid
    assert result.target_entity == "revenue_fact"
    assert result.data["recognition_type"] == "payment"
    assert result.data["amount"] == Decimal("140000")
    assert result.data["branch_code"] == "main"


def test_non_patient_revenue_operation_is_zeroed_for_safe_reprocessing() -> None:
    result = normalize_one_c_finance_record(
        source_entity=REVENUE_ENTITY,
        source_record_id="insurance|1",
        branch_code="main",
        payload={
            "Period": "2026-07-10T12:00:00",
            "Сумма": 203895,
            "ВидОперации": "Оплата от страховой компании",
        },
    )

    assert result is not None and result.is_valid
    assert result.data["amount"] == Decimal("0")


def test_july_patient_payment_operations_match_verified_one_c_report() -> None:
    rows = (
        ("Оплата от пациента", "54797222.28"),
        ("Взнос на лицевой счет", "4057122.00"),
        ("Возврат оплаты пациенту", "-16500.00"),
        ("Оплата от страховой компании", "203895.00"),
    )
    mapped = [
        normalize_one_c_finance_record(
            source_entity=REVENUE_ENTITY,
            source_record_id=f"july|{index}",
            branch_code="main",
            payload={
                "Period": "2026-07-31T12:00:00",
                "Сумма": amount,
                "ВидОперации": operation,
            },
        )
        for index, (operation, amount) in enumerate(rows)
    ]

    assert all(item is not None and item.is_valid for item in mapped)
    assert sum((item.data["amount"] for item in mapped if item), Decimal("0")) == Decimal(
        "58837844.28"
    )


def test_sales_register_becomes_accrual_without_double_cashflow() -> None:
    result = normalize_one_c_finance_record(
        source_entity=SALES_ENTITY,
        source_record_id="sale|1",
        branch_code="main",
        payload={"Period": "2026-07-01T09:00:00", "СуммаПродажи": "25 500,50"},
    )

    assert result is not None and result.is_valid
    assert result.target_entity == "revenue_fact"
    assert result.data["recognition_type"] == "accrual"
    assert result.data["amount"] == Decimal("25500.50")


def test_expense_register_becomes_expense() -> None:
    result = normalize_one_c_finance_record(
        source_entity=EXPENSE_ENTITY,
        source_record_id="expense|1",
        branch_code="main",
        payload={
            "Period": "2026-07-15T00:00:00",
            "СуммаЗатрат": 50000,
            "ВидОперации": "Списание материалов",
        },
    )

    assert result is not None and result.is_valid
    assert result.target_entity == "expense_fact"
    assert result.data["amount"] == Decimal("50000")


def test_expense_behavior_is_inferred_only_for_known_categories() -> None:
    laboratory = normalize_one_c_finance_record(
        source_entity=EXPENSE_ENTITY,
        source_record_id="expense|lab",
        branch_code="main",
        payload={"Period": "2026-07-15T00:00:00", "Сумма": 50000, "СтатьяЗатрат": "Лаборатория"},
    )
    rent = normalize_one_c_finance_record(
        source_entity=EXPENSE_ENTITY,
        source_record_id="expense|rent",
        branch_code="main",
        payload={"Period": "2026-07-15T00:00:00", "Сумма": 100000, "СтатьяЗатрат": "Аренда помещений (офис)"},
    )

    assert laboratory is not None and laboratory.data["cost_behavior"] == "variable"
    assert rent is not None and rent.data["cost_behavior"] == "fixed"


def test_payroll_document_uses_accounting_month_not_posting_date() -> None:
    result = normalize_one_c_finance_record(
        source_entity=PAYROLL_ENTITY,
        source_record_id="payroll-july",
        branch_code="main",
        payload={
            "Ref_Key": "payroll-july",
            "Date": "2026-08-05T10:00:00",
            "ДатаОкончанияПериода": "2026-07-31T23:59:59",
            "СуммаДокумента": "24549806.17",
        },
    )

    assert result is not None and result.is_valid
    assert result.target_entity == "payroll_fact"
    assert result.data["occurred_on"].isoformat() == "2026-07-31"
    assert result.data["amount"] == Decimal("24549806.17")


def test_money_register_infers_cash_direction() -> None:
    incoming = normalize_one_c_finance_record(
        source_entity=MONEY_ENTITY,
        source_record_id="money|1",
        branch_code="main",
        payload={
            "Period": "2026-07-16T00:00:00",
            "Сумма": 75000,
            "ВидОперации": "Поступление оплаты",
        },
    )
    outgoing = normalize_one_c_finance_record(
        source_entity=MONEY_ENTITY,
        source_record_id="money|2",
        branch_code="main",
        payload={
            "Period": "2026-07-16T00:00:00",
            "Сумма": -12000,
        },
    )

    assert incoming is not None and incoming.is_valid
    assert incoming.data["direction"] == "in"
    assert outgoing is not None and outgoing.is_valid
    assert outgoing.data["direction"] == "out"
    assert outgoing.data["amount"] == Decimal("12000")


def test_ambiguous_amount_is_quarantined_instead_of_guessed() -> None:
    result = normalize_one_c_finance_record(
        source_entity=EXPENSE_ENTITY,
        source_record_id="expense|ambiguous",
        branch_code="main",
        payload={
            "Period": "2026-07-15T00:00:00",
            "СуммаБезНДС": 100,
            "СуммаСНДС": 112,
        },
    )

    assert result is not None and not result.is_valid
    assert {issue.code for issue in result.issues} == {"ONE_C_AMOUNT_AMBIGUOUS"}


def test_supporting_register_is_excluded_from_totals() -> None:
    assert (
        normalize_one_c_finance_record(
            source_entity="AccumulationRegister_НарядЗаказы_RecordType",
            source_record_id="order|1",
            branch_code="main",
            payload={"Period": "2026-07-01T00:00:00", "Сумма": 100},
        )
        is None
    )
