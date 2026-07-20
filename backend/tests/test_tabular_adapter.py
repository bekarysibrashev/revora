from io import BytesIO

from openpyxl import Workbook
import pytest

from app.modules.integrations.tabular_adapter import (
    InvalidTabularFile,
    TabularFileAdapter,
    UnsupportedTabularFile,
)


async def collect(adapter: TabularFileAdapter):
    return [record async for record in adapter.fetch()]


@pytest.mark.asyncio
async def test_csv_adapter_detects_delimiter_and_keeps_source_headers() -> None:
    adapter = TabularFileAdapter(
        filename="payments.csv",
        content="Клиент;Сумма платежа;Дата\nИванов;50000;2026-07-10\n".encode(),
        source_entity="payments",
    )

    records = await collect(adapter)

    assert len(records) == 1
    assert records[0].payload == {
        "Клиент": "Иванов",
        "Сумма платежа": "50000",
        "Дата": "2026-07-10",
    }
    assert records[0].external_id == "2"
    assert records[0].schema_version


@pytest.mark.asyncio
async def test_xlsx_adapter_emits_same_source_record_contract() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Пациент", "Оплата"])
    sheet.append(["Петров", 75000])
    buffer = BytesIO()
    workbook.save(buffer)

    records = await collect(
        TabularFileAdapter(
            filename="payments.xlsx",
            content=buffer.getvalue(),
            source_entity="payments",
        )
    )

    assert records[0].payload == {"Пациент": "Петров", "Оплата": 75000}
    assert records[0].source_entity == "payments"


@pytest.mark.asyncio
async def test_duplicate_headers_are_rejected() -> None:
    adapter = TabularFileAdapter(
        filename="bad.csv",
        content="Сумма;сумма\n1;2\n".encode(),
        source_entity="payments",
    )

    with pytest.raises(InvalidTabularFile, match="unique"):
        await collect(adapter)


@pytest.mark.asyncio
async def test_unknown_file_type_is_rejected() -> None:
    adapter = TabularFileAdapter(
        filename="payments.xls",
        content=b"legacy",
        source_entity="payments",
    )

    with pytest.raises(UnsupportedTabularFile):
        await collect(adapter)
