from decimal import Decimal

from app.modules.reports.one_c_parser import (
    SheetData,
    _parse_appointments,
    _parse_patients,
    _parse_purchases,
    _parse_service_revenue,
)


def metric_value(parsed, code, dimension_type="clinic", branch_code=None):
    matches = [
        metric.value
        for metric in parsed.metrics
        if metric.metric_code == code
        and metric.dimension_type == dimension_type
        and metric.branch_code == branch_code
    ]
    assert len(matches) == 1
    return matches[0]


def test_service_revenue_uses_report_total_and_preserves_branch_totals() -> None:
    sheet = SheetData(
        rows=[
            ["Выручка по оказанным услугам"],
            ["Номенклатура.Специализация", "Количество", "Сумма", "До скидки"],
            ["SAN (Сейфуллина)", 100, 30_331_339.88, 34_000_000],
            ["SAN (Батыс Мура)", 120, 35_663_349.77, 42_970_151.25],
            ["Итого", 220, 65_994_689.65, 76_970_151.25],
        ],
        outline_levels=[0, 0, 0, 0, 0],
    )

    parsed = _parse_service_revenue(sheet)

    assert metric_value(parsed, "revenue_accrual") == Decimal("65994689.65")
    assert metric_value(parsed, "revenue_accrual", "branch", "seifullina") == Decimal("30331339.88")
    assert metric_value(parsed, "revenue_accrual", "branch", "batysmura") == Decimal("35663349.77")


def test_purchases_deduplicate_documents_and_exclude_dentco() -> None:
    header = [[""] * 22 for _ in range(8)]

    def row(document, branch, accrued, paid):
        values = [""] * 22
        values[0] = document
        values[18] = branch
        values[20] = accrued
        values[21] = paid
        return values

    total = [""] * 22
    total[0] = "Итого"
    total[20] = 1_600
    total[21] = 1_300
    sheet = SheetData(
        rows=header + [
            row("Поступление 1", "SAN (Сейфуллина)", 1_000, 800),
            row("Поступление 1", "SAN (Сейфуллина)", 1_000, 800),
            row("Поступление 2", "SAN (Батыс Мура)", 200, 100),
            row("Поступление 3", "ИП Dent.Co", 400, 400),
            total,
        ],
        outline_levels=[0] * 13,
    )

    parsed = _parse_purchases(sheet)

    assert metric_value(parsed, "purchases_accrual") == Decimal("1200")
    assert metric_value(parsed, "purchases_paid") == Decimal("900")
    assert metric_value(parsed, "purchases_accrual_all_entities") == Decimal("1600")


def test_patient_report_does_not_invent_a_clinic_unique_patient_total() -> None:
    sheet = SheetData(
        rows=[
            ["Количество пациентов", "Первичные", "Количество посещений"],
            ["SAN (Сейфуллина)", 469, 228, 838, 1_000, 900],
            ["SAN (Батыс Мура)", 339, 107, 580, 1_000, 900],
            ["Итого", "", 335, "", 2_000, 1_800],
        ],
        outline_levels=[0, 0, 0, 0],
    )

    parsed = _parse_patients(sheet)

    assert not any(
        metric.metric_code == "patients_total" and metric.dimension_type == "clinic"
        for metric in parsed.metrics
    )
    assert metric_value(parsed, "patients_primary") == Decimal("335")


def test_appointment_totals_and_statuses_are_separate_metrics() -> None:
    sheet = SheetData(
        rows=[
            ["Статистика предварительной записи"],
            ["Оформлено записей", "Оформленно приемов"],
            [""],
            ["Пациент 1", "", "Отменено", "", "", "", "", "", ""],
            ["Пациент 2", "", "", "Не пришёл", "", "", "", "", ""],
            ["Итого", "", "", "", 2206, 539, 1388, 66_150_944.65, 59_840_604.28],
        ],
        outline_levels=[0, 0, 0, 2, 2, 0],
    )

    parsed = _parse_appointments(sheet)

    assert metric_value(parsed, "appointments_total") == Decimal("2206")
    assert metric_value(parsed, "appointments_completed") == Decimal("1388")
    assert metric_value(parsed, "appointments_cancelled") == Decimal("1")
    assert metric_value(parsed, "appointments_no_show") == Decimal("1")
