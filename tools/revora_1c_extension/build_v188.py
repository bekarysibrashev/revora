"""Build and verify Revora 1C extension v18.8 from v18.7."""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_ZIP = BASE_DIR / "RevoraExtensionReady-v18.7-complete-sync.zip"
OUT_ZIP = BASE_DIR / "RevoraExtensionReady-v18.8-complete-sync.zip"
SERVER_SOURCE = BASE_DIR / "РвОбменСервер.bsl"
FORM_SOURCE = BASE_DIR / "РвНастройкиОбмена.Форма.Модуль.bsl"
SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
VERSION = "1.8.8.0"
BOM = b"\xef\xbb\xbf"


def module_bytes(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def main() -> None:
    server_text = SERVER_SOURCE.read_text(encoding="utf-8-sig")
    server = module_bytes(SERVER_SOURCE)
    form = module_bytes(FORM_SOURCE)

    assert f'Возврат "{VERSION}";' in server_text
    assert f"// Revora_Обмен {VERSION}" in server_text
    assert server_text.count("Функция СобратьУслугиИзОфициальнойСКД(") == 1
    function_text = server_text.split("Функция СобратьУслугиИзОфициальнойСКД(", 1)[1].split(
        "КонецФункции", 1
    )[0]
    for required in (
        "ПроцессорВывода.НачатьВывод()",
        "ПроцессорКомпоновки.Следующий()",
        "ПроцессорВывода.ВывестиЭлемент(ЭлементРезультата)",
        "ПроцессорВывода.ЗакончитьВывод()",
    ):
        assert required in function_text, f"missing collection output step: {required}"
    assert "ПроцессорВывода.Вывести(ПроцессорКомпоновки)" not in function_text
    assert 'ИсточникРазрезов = "official_skd_collection"' in server_text
    assert "СКДИсточник.СтрокСВрачом > 0" in server_text
    assert len(re.findall(r"(?m)^\s*Функция\b", server_text)) == len(
        re.findall(r"(?m)^\s*КонецФункции\s*$", server_text)
    )
    assert len(re.findall(r"(?m)^\s*Процедура\b", server_text)) == len(
        re.findall(r"(?m)^\s*КонецПроцедуры\s*$", server_text)
    )

    with zipfile.ZipFile(SRC_ZIP) as source:
        config = source.read(CONFIG_ENTRY).decode("utf-8-sig")
        config, count = re.subn(
            r"<Version>1\.8\.7\.0</Version>", f"<Version>{VERSION}</Version>", config
        )
        assert count == 1
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
        assert "<Use>false</Use>" in job

    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    print(f"Built: {OUT_ZIP.name}")
    print(f"Size: {OUT_ZIP.stat().st_size} bytes")
    print(f"SHA-256: {digest}")
    print("ZIP/XML/UTF-8/version/modules/full collection output/disabled job: OK")


if __name__ == "__main__":
    main()
