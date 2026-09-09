"""Build and verify Revora 1C extension v18.7.

v18.7 executes the complete official DCS (СКД) report into a value tree and
uses that structured result for clinic/doctor breakdowns only when quantity,
revenue and before-discount all reproduce the official total row.  The hourly
scheduled job deliberately remains disabled.
"""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SRC_ZIP = BASE_DIR / "RevoraExtensionReady-v18.6-complete-sync.zip"
OUT_ZIP = BASE_DIR / "RevoraExtensionReady-v18.7-complete-sync.zip"
SERVER_SOURCE = BASE_DIR / "РвОбменСервер.bsl"
FORM_SOURCE = BASE_DIR / "РвНастройкиОбмена.Форма.Модуль.bsl"

SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
VERSION = "1.8.7.0"
BOM = b"\xef\xbb\xbf"

SUMMARY_KEYS = (
    "skd_collection_ran",
    "skd_collection_error",
    "skd_collection_rows",
    "skd_collection_doctor_rows",
    "skd_collection_quantity",
    "skd_collection_revenue",
    "skd_collection_before_discount",
    "skd_collection_columns",
    "skd_collection_invariants_hold",
    "breakdown_source",
)

RESULT_FIELDS = (
    "СКДВыполнена",
    "СКДОшибка",
    "СКДСтрок",
    "СКДСтрокСВрачом",
    "СКДКоличество",
    "СКДВыручка",
    "СКДБезСкидки",
    "СКДКолонки",
    "СКДИнварианты",
)


def module_bytes(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def assert_balanced(text: str, start: str, end: str) -> None:
    starts = len(re.findall(rf"(?m)^\s*{start}\b", text))
    ends = len(re.findall(rf"(?m)^\s*{end}\s*;?\s*$", text))
    assert starts == ends, f"unbalanced {start}/{end}: {starts}/{ends}"


def main() -> None:
    server_text = SERVER_SOURCE.read_text(encoding="utf-8-sig")
    server = module_bytes(SERVER_SOURCE)
    form = module_bytes(FORM_SOURCE)

    assert f'Возврат "{VERSION}";' in server_text
    assert f"// Revora_Обмен {VERSION}" in server_text
    assert "Функция СобратьУслугиИзОфициальнойСКД(" in server_text
    assert "Процедура ОбойтиСтрокиВыручкиСКД(" in server_text
    assert 'ИсточникРазрезов = "official_skd_collection"' in server_text
    assert "Не ОбычныйСошелся И ИнвариантыСКД" in server_text
    assert "СКДИсточник.СтрокСВрачом > 0" in server_text
    assert "ГенераторМакетаКомпоновкиДанныхДляКоллекцииЗначений" in server_text
    assert "ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений" in server_text
    for key in SUMMARY_KEYS:
        assert f'"{key}"' in server_text, f"missing summary key: {key}"
    for field in RESULT_FIELDS:
        assert f'Результат.Вставить("{field}"' in server_text, f"not handed over: {field}"
        assert f"Итоги.{field}" in server_text, f"not rendered: {field}"

    # Function/procedure balance catches accidental truncation. Block-level BSL
    # checks belong to Configurator: one-line constructs and keywords inside
    # strings/comments make a regex count for Если/Цикл unreliable.
    assert_balanced(server_text, "Функция", "КонецФункции")
    assert_balanced(server_text, "Процедура", "КонецПроцедуры")
    assert "Примечание: дополнительные наборы могут быть вспомогательными" in server_text
    assert "Отчет складывает все" not in server_text

    with zipfile.ZipFile(SRC_ZIP) as source:
        config = source.read(CONFIG_ENTRY).decode("utf-8-sig")
        config, count = re.subn(
            r"<Version>1\.8\.6\.0</Version>",
            f"<Version>{VERSION}</Version>",
            config,
        )
        assert count == 1, "Configuration.xml v18.6 version not found"

        with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as output:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == CONFIG_ENTRY:
                    data = config.encode("utf-8")
                elif item.filename == SERVER_ENTRY:
                    data = server
                elif item.filename == FORM_ENTRY:
                    data = form
                output.writestr(item, data)

    with zipfile.ZipFile(OUT_ZIP) as archive:
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

        job = archive.read(JOB_ENTRY).decode("utf-8-sig")
        assert "<Use>false</Use>" in job, "hourly synchronization must remain disabled"
        assert (
            "<MethodName>CommonModule.РвОбменСервер."
            "ВыполнитьРегламентнуюСинхронизацию</MethodName>"
        ) in job

    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    print(f"Built: {OUT_ZIP.name}")
    print(f"Size: {OUT_ZIP.stat().st_size} bytes")
    print(f"SHA-256: {digest}")
    print(f"Version: {VERSION}")
    print("ZIP/XML/UTF-8/modules/version/structure/СКД gate/scheduled job: OK")


if __name__ == "__main__":
    main()
