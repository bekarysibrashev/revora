"""Build and verify the comprehensive one-run Revora 1C diagnostic v2.0."""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "RevoraExtensionReady-v19.2-self-healing-sync.zip"
OUT = BASE / "RevoraExtensionReady-v20-comprehensive-diagnostic.zip"
SERVER = BASE / "РвОбменСервер.bsl"
FORM = BASE / "РвНастройкиОбмена.Форма.Модуль.bsl"
SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
VERSION = "2.0.0.0"
BOM = b"\xef\xbb\xbf"


def encoded(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def main() -> None:
    text = SERVER.read_text(encoding="utf-8-sig")
    server, form = encoded(SERVER), encoded(FORM)
    assert f'Возврат "{VERSION}";' in text
    assert f"// Revora_Обмен {VERSION}" in text
    for marker in (
        "Функция РвКомплексныйОтчетСнимков(",
        '"КОМПЛЕКСНАЯ ДИАГНОСТИКА ВСЕЙ СИНХРОНИЗАЦИИ"',
        '"ОШИБКИ ИСТОЧНИКОВ/ОТПРАВКИ: "',
        '"ОПЕРАЦИОННЫЕ ДАННЫЕ:"',
        '" [РАСХОЖДЕНИЕ]"',
        'ОшибкиСнимков.Добавить("cash_receipts:',
        'ОшибкиСнимков.Добавить("doctor_revenue:',
        'ОшибкиСнимков.Добавить("payroll:',
        'ОшибкиСнимков.Добавить("purchases:',
        'ОшибкиСнимков.Добавить("patients:',
        'ОшибкиСнимков.Добавить("appointments:',
        'ОшибкиПотоков.Добавить("patients:',
        'ОшибкиПотоков.Добавить("doctors:',
        'ОшибкиПотоков.Добавить("appointments:',
        'ОшибкиПотоков.Добавить("expenses:',
        '"daily/" + Формат(ТекущийДень',
        '"send/daily-batch: "',
        '"КомплексныйОтчет"',
        "Функция СобратьУслугиИзСКДСАвтоИсключением(",
        "Для НомерПопытки = 1 По 20",
        'ИсточникРазрезов = "official_skd_collection"',
    ):
        assert marker in text, f"missing comprehensive diagnostic marker: {marker}"

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
            r"<Version>1\.9\.2\.0</Version>", f"<Version>{VERSION}</Version>", config
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
    print("ZIP/XML/UTF-8/version/all-source diagnostics/self-healing/disabled job: OK")


if __name__ == "__main__":
    main()
