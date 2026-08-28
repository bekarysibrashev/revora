from decimal import Decimal

from app.modules.integrations.one_c_finance import (
    EXPENSE_ENTITY,
    INCOMING_PAYMENT_LINE_ENTITY,
    MONEY_ENTITY,
    OUTGOING_PAYMENT_LINE_ENTITY,
    PAYROLL_ENTITY,
    PAYROLL_EXPENSE_LINE_ENTITY,
    PAYROLL_LINE_ENTITY,
    PAYROLL_REGISTER_ENTITY,
    PURCHASE_ENTITY,
    RECEPTION_SERVICE_ENTITY,
    REVENUE_ENTITY,
    RETAIL_SALE_SERVICE_ENTITY,
    SALES_ENTITY,
    OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY,
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


def test_patient_payment_enum_wording_variants_are_included() -> None:
    for operation in (
        "ОплатаПациентом",
        "ВозвратОплатыПациента",
        "ОплатаОтКлиента",
        "ВозвратОплатыКлиенту",
        "ВозвратСЛицевогоСчета",
    ):
        result = normalize_one_c_finance_record(
            source_entity=REVENUE_ENTITY,
            source_record_id=operation,
            branch_code="main",
            payload={
                "Period": "2026-07-31T12:00:00",
                "Сумма": "100",
                "ВидОперации": operation,
            },
        )

        assert result is not None and result.is_valid
        assert result.data["amount"] == Decimal("100")


def test_sales_register_is_zeroed_after_switch_to_service_documents() -> None:
    result = normalize_one_c_finance_record(
        source_entity=SALES_ENTITY,
        source_record_id="sale|1",
        branch_code="main",
        payload={"Period": "2026-07-01T09:00:00", "СуммаПродажи": "25 500,50"},
    )

    assert result is not None and result.is_valid
    assert result.target_entity == "revenue_fact"
    assert result.data["recognition_type"] == "accrual"
    assert result.data["amount"] == Decimal("0")


def test_expense_register_is_zeroed_after_switch_to_purchase_documents() -> None:
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
    assert result.data["amount"] == Decimal("0")


def test_service_document_lines_match_verified_july_revenue() -> None:
    rows = (
        (RECEPTION_SERVICE_ENTITY, "30331339.88"),
        (RETAIL_SALE_SERVICE_ENTITY, "35663349.77"),
    )
    mapped = [
        normalize_one_c_finance_record(
            source_entity=entity,
            source_record_id=f"service|{index}",
            branch_code="main",
            payload={
                "Ref_Key": f"doc-{index}",
                "LineNumber": 1,
                "Date": "2026-07-31T12:00:00",
                "Posted": True,
                "Сумма": amount,
                "Сотрудник_Key": f"doctor-{index}",
                "Номенклатура_Key": f"service-{index}",
            },
        )
        for index, (entity, amount) in enumerate(rows)
    ]

    assert all(item is not None and item.is_valid for item in mapped)
    assert sum((item.data["amount"] for item in mapped if item), Decimal("0")) == Decimal(
        "65994689.65"
    )


def test_doctor_payment_lines_include_patient_deposit_refund_and_insurance() -> None:
    rows = (
        (INCOMING_PAYMENT_LINE_ENTITY, "Оплата от клиента", "54797222.28"),
        (INCOMING_PAYMENT_LINE_ENTITY, "Взнос на лицевой счет", "4057122.00"),
        (OUTGOING_PAYMENT_LINE_ENTITY, "Возврат оплаты клиенту", "16500.00"),
        (INCOMING_PAYMENT_LINE_ENTITY, "Оплата от страховой компании", "203895.00"),
    )
    mapped = [
        normalize_one_c_finance_record(
            source_entity=entity,
            source_record_id=f"doctor-payment|{index}",
            branch_code="main",
            payload={
                "Ref_Key": f"payment-{index}",
                "LineNumber": 1,
                "Date": "2026-07-31T12:00:00",
                "Posted": True,
                "ВидОперации": operation,
                "Сумма": amount,
                "Сотрудник_Key": "doctor-1",
            },
        )
        for index, (entity, operation, amount) in enumerate(rows)
    ]

    assert all(item is not None and item.is_valid for item in mapped)
    assert all(item.data["recognition_type"] == "doctor_payment" for item in mapped if item)
    assert sum((item.data["amount"] for item in mapped if item), Decimal("0")) == Decimal(
        "59041739.28"
    )


def test_salary_payment_breakdown_is_excluded_from_doctor_revenue() -> None:
    result = normalize_one_c_finance_record(
        source_entity=OUTGOING_PAYMENT_LINE_ENTITY,
        source_record_id="salary-payment|breakdown|1",
        branch_code="main",
        payload={
            "Ref_Key": "salary-payment",
            "LineNumber": 1,
            "Date": "2026-08-05T10:00:00",
            "Posted": True,
            "ВидОперации": "Выплата зарплаты",
            "Сумма": "23199091.80",
            "Сотрудник_Key": "employee-1",
        },
    )

    assert result is not None and result.is_valid
    assert result.data["recognition_type"] == "doctor_payment"
    assert result.data["amount"] == Decimal("0")


def test_purchase_document_maps_accrued_and_paid_totals_once() -> None:
    result = normalize_one_c_finance_record(
        source_entity=PURCHASE_ENTITY,
        source_record_id="purchase-1",
        branch_code="main",
        payload={
            "Ref_Key": "purchase-1",
            "Date": "2026-07-31T12:00:00",
            "Posted": True,
            "СуммаДокумента": "24360327.76",
            "СуммаОплачено": "19598332.82",
        },
    )

    assert result is not None and result.is_valid
    assert result.data["amount"] == Decimal("24360327.76")
    assert result.data["paid_amount"] == Decimal("19598332.82")


def test_expense_without_branch_is_quarantined() -> None:
    result = normalize_one_c_finance_record(
        source_entity=EXPENSE_ENTITY,
        source_record_id="expense-without-branch",
        branch_code=None,
        payload={"Period": "2026-07-15T00:00:00", "Сумма": 50000},
    )

    assert result is not None and not result.is_valid
    assert {issue.code for issue in result.issues} == {"ONE_C_BRANCH_MAPPING_REQUIRED"}


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


def test_payroll_document_header_is_zeroed() -> None:
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
    assert result.data["amount"] == Decimal("0")


def test_payroll_calculation_line_is_zeroed_as_superseded() -> None:
    result = normalize_one_c_finance_record(
        source_entity=PAYROLL_LINE_ENTITY,
        source_record_id="payroll-july|1",
        branch_code="main",
        payload={
            "Ref_Key": "payroll-july",
            "LineNumber": 1,
            "ДатаОкончанияПериода": "2026-07-31T23:59:59",
            "Сумма": "481048.99",
        },
    )

    assert result is not None and result.is_valid
    assert result.data["occurred_on"].isoformat() == "2026-07-31"
    assert result.data["amount"] == Decimal("0")


def test_payroll_expense_lines_match_verified_july_accrual() -> None:
    result = normalize_one_c_finance_record(
        source_entity=PAYROLL_EXPENSE_LINE_ENTITY,
        source_record_id="payroll-july|1",
        branch_code="main",
        payload={
            "Ref_Key": "payroll-july",
            "LineNumber": 1,
            "ДатаОкончанияПериода": "2026-07-31T23:59:59",
            "Сотрудник_Key": "employee-1",
            "Сумма": "24549806.17",
            "Posted": True,
        },
    )

    assert result is not None and result.is_valid
    assert result.data["amount"] == Decimal("24549806.17")
    assert result.data["paid_amount"] == Decimal("0")


def test_payroll_payment_uses_employee_expense_line_and_payroll_month() -> None:
    result = normalize_one_c_finance_record(
        source_entity=OUTGOING_PAYMENT_EXPENSE_LINE_ENTITY,
        source_record_id="salary-payment|1",
        branch_code="main",
        payload={
            "Ref_Key": "salary-payment",
            "LineNumber": 1,
            "Date": "2026-08-05T10:00:00",
            "Posted": True,
            "ВидОперации": "Выплата зарплаты",
            "ВыплатаЗПМесяц": "2026-07-31T23:59:59",
            "Сотрудник_Key": "employee-1",
            "Сумма": "23199091.80",
        },
    )

    assert result is not None and result.is_valid
    assert result.data["occurred_on"].isoformat() == "2026-07-31"
    assert result.data["amount"] == Decimal("0")
    assert result.data["paid_amount"] == Decimal("23199091.80")


def test_payroll_deduction_line_is_not_counted_as_accrued_salary() -> None:
    result = normalize_one_c_finance_record(
        source_entity=PAYROLL_LINE_ENTITY,
        source_record_id="payroll-july|2",
        branch_code="main",
        payload={
            "Ref_Key": "payroll-july",
            "LineNumber": 2,
            "Сотрудник_Key": "employee-1",
            "ДатаОкончанияПериода": "2026-07-31T23:59:59",
            "Сумма": "50000",
            "_ResolvedPayrollKind": "Удержание",
        },
    )

    assert result is not None and result.is_valid
    assert result.data["employee_external_id"] == "employee-1"
    assert result.data["amount"] == Decimal("0")


def test_payroll_register_is_zeroed_after_switch_to_documents() -> None:
    result = normalize_one_c_finance_record(
        source_entity=PAYROLL_REGISTER_ENTITY,
        source_record_id="payroll-register-july",
        branch_code="main",
        payload={
            "Period": "2026-08-05T10:00:00",
            "МесяцНачисления": "2026-07-31T23:59:59",
            "RecordType": "Receipt",
            "Сумма": "24549806.17",
            "Active": True,
        },
    )

    assert result is not None and result.is_valid
    assert result.target_entity == "payroll_fact"
    assert result.data["occurred_on"].isoformat() == "2026-07-31"
    assert result.data["amount"] == Decimal("0")


def test_payroll_register_payment_movement_is_zeroed() -> None:
    result = normalize_one_c_finance_record(
        source_entity=PAYROLL_REGISTER_ENTITY,
        source_record_id="payroll-register-payment",
        branch_code="main",
        payload={
            "Period": "2026-08-05T10:00:00",
            "МесяцНачисления": "2026-07-31T23:59:59",
            "RecordType": "Expense",
            "Сумма": "23199091.80",
        },
    )

    assert result is not None and result.is_valid
    assert result.data["amount"] == Decimal("0")


def test_payroll_without_branch_is_quarantined() -> None:
    result = normalize_one_c_finance_record(
        source_entity=PAYROLL_REGISTER_ENTITY,
        source_record_id="payroll-without-branch",
        branch_code=None,
        payload={
            "Period": "2026-08-05T10:00:00",
            "МесяцНачисления": "2026-07-31T23:59:59",
            "RecordType": "Receipt",
            "Сумма": "100000",
        },
    )

    assert result is not None and not result.is_valid
    assert {issue.code for issue in result.issues} == {"ONE_C_BRANCH_MAPPING_REQUIRED"}


def test_revenue_without_structural_unit_is_quarantined() -> None:
    result = normalize_one_c_finance_record(
        source_entity=REVENUE_ENTITY,
        source_record_id="payment-without-branch",
        branch_code=None,
        payload={
            "Period": "2026-07-20T12:00:00",
            "Сумма": "150000",
            "ВидОперации": "Оплата от пациента",
            "Контрагент_Key": "patient-1",
        },
    )

    assert result is not None and not result.is_valid
    assert result.data["branch_code"] is None
    assert result.data["patient_external_id"] == "patient-1"


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
    assert outgoing.data["amount"] == Decimal("0")


def test_money_register_keeps_resolved_category_and_account() -> None:
    result = normalize_one_c_finance_record(
        source_entity=MONEY_ENTITY,
        source_record_id="money|categorized",
        branch_code="main",
        payload={
            "Period": "2026-07-16T00:00:00",
            "RecordType": "Expense",
            "Сумма": 12000,
            "БанковскийСчетКасса": "cashbox-1",
            "_ResolvedCategoryName": "Реклама",
        },
    )

    assert result is not None and result.is_valid
    assert result.data["direction"] == "out"
    assert result.data["category_name"] == "Реклама"
    assert result.data["account_ref"] == "cashbox-1"


def test_money_without_branch_is_quarantined() -> None:
    result = normalize_one_c_finance_record(
        source_entity=MONEY_ENTITY,
        source_record_id="money-without-branch",
        branch_code=None,
        payload={
            "Period": "2026-07-16T00:00:00",
            "Сумма": 75000,
            "ВидОперации": "Поступление оплаты",
        },
    )

    assert result is not None and not result.is_valid
    assert {issue.code for issue in result.issues} == {"ONE_C_BRANCH_MAPPING_REQUIRED"}


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
