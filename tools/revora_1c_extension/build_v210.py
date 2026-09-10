"""Build and verify the production Revora 1C sync v2.1."""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "RevoraExtensionReady-v20-comprehensive-diagnostic.zip"
OUT = BASE / "RevoraExtensionReady-v21-production-sync.zip"
SERVER = BASE / "РвОбменСервер.bsl"
FORM = BASE / "РвНастройкиОбмена.Форма.Модуль.bsl"
SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
VERSION = "2.1.0.0"
BOM = b"\xef\xbb\xbf"


def encoded(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def main() -> None:
    text = SERVER.read_text(encoding="utf-8-sig")
    server, form = encoded(SERVER), encoded(FORM)
    assert f'Возврат "{VERSION}";' in text
    assert f"// Revora_Обмен {VERSION}" in text
    for marker in (
        'Результат.Вставить("ПоказыватьДиагностику", Ложь)',
        'Результат.Вставить("КомплексныйОтчет", "")',
        'Контроль = Новый Структура("Выполнен,Ошибка,Данные,РежимВосстановлен"',
        'СКДИсходная = РвНовыйРезультатСбораСКД("disabled_in_production")',
        "СКДИсточник = СобратьУслугиИзСКДСАвтоИсключением(",
        "Для НомерПопытки = 1 По 20",
        "ИтогоОплатыЛечения = Итого",
        "ИтогоДенежногоПритока = ПолучитьИтогОплатыИзШтатногоОтчета",
        'ДобавитьМетрику(Метрики, "revenue_payment", "payment_method"',
        'ДобавитьМетрику(Метрики, "revenue_payment", "cash_account"',
        'ДобавитьМетрику(Метрики, "cash_inflow", "clinic"',
        '"revenue_payment_source", "filtered_treatment_receipts_register"',
        '"cash_inflow_source", "standard_management_monitor"',
        'Результат.Вставить("ОшибкиСинхронизации", ОшибкиСнимков)',
    ):
        assert marker in text, f"missing production marker: {marker}"

    # The completed diagnostic experiments must not run in production.
    assert text.count("КонтрольныйСборБезОграниченийRLS(") == 1
    assert 'СобратьУслугиИзОфициальнойСКД(НачалоПериода, КонецПериода, "original")' not in text
    assert "Если СобиратьПрофиль Тогда" in text
    assert len(re.findall(r"(?m)^\s*Функция\b", text)) == len(
        re.findall(r"(?m)^\s*КонецФункции\s*$", text)
    )
    assert len(re.findall(r"(?m)^\s*Процедура\b", text)) == len(
        re.findall(r"(?m)^\s*КонецПроцедуры\s*$", text)
    )
    assert len(re.findall(r"(?m)^\s*Попытка\s*$", text)) == len(
        re.findall(r"(?m)^\s*КонецПопытки\s*;?\s*$", text)
    )

    with zipfile.ZipFile(SRC) as source:
        config = source.read(CONFIG_ENTRY).decode("utf-8-sig")
        config, count = re.subn(
            r"<Version>2\.0\.0\.0</Version>", f"<Version>{VERSION}</Version>", config
        )
        assert count == 1
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as output:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == CONFIG_ENTRY:
                    data = config.encode("utf-8")
                elif item.filename == SERVER_ENTRY:
                    data = server
                elif item.filename == FORM_ENTRY:
                    data = form
                output.writestr(item, data)

    with zipfile.ZipFile(OUT) as archive:
        assert archive.testzip() is None
        assert archive.read(SERVER_ENTRY) == server
        assert archive.read(FORM_ENTRY) == form
        assert f"<Version>{VERSION}</Version>" in archive.read(CONFIG_ENTRY).decode("utf-8-sig")
        for name in archive.namelist():
            raw = archive.read(name)
            if name.endswith(".xml"):
                ET.fromstring(raw)
            if name.endswith((".xml", ".bsl")):
                raw.decode("utf-8-sig")
        assert "<Use>false</Use>" in archive.read(JOB_ENTRY).decode("utf-8-sig")

    print(f"Built: {OUT.name}")
    print(f"Size: {OUT.stat().st_size} bytes")
    print(f"SHA-256: {hashlib.sha256(OUT.read_bytes()).hexdigest()}")
    print("ZIP/XML/UTF-8/version/revenue semantics/production mode/disabled job: OK")


if __name__ == "__main__":
    main()
