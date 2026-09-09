"""Build and verify Revora 1C extension v19.1 from v19.0."""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "RevoraExtensionReady-v19.0-one-pass-sync.zip"
OUT = BASE / "RevoraExtensionReady-v19.1-one-pass-sync.zip"
SERVER = BASE / "РвОбменСервер.bsl"
FORM = BASE / "РвНастройкиОбмена.Форма.Модуль.bsl"
SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
VERSION = "1.9.1.0"
BOM = b"\xef\xbb\xbf"


def encoded(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def main() -> None:
    text = SERVER.read_text(encoding="utf-8-sig")
    server, form = encoded(SERVER), encoded(FORM)
    assert f'Возврат "{VERSION}";' in text
    assert f"// Revora_Обмен {VERSION}" in text
    assert "ПолеНабора.ПутьКДанным" in text
    assert "ПолеНабора.Поле" not in text
    for marker in (
        '"original"', '"details_all"', "БезопасныйПрофильТабличногоДокумента",
        '"skd_original_rows"', '"skd_collection_dataset_fields"',
        'ИсточникРазрезов = "official_skd_collection"', "СКДИсточник.СтрокСВрачом > 0",
    ):
        assert marker in text
    assert len(re.findall(r"(?m)^\s*Функция\b", text)) == len(
        re.findall(r"(?m)^\s*КонецФункции\s*$", text)
    )
    assert len(re.findall(r"(?m)^\s*Процедура\b", text)) == len(
        re.findall(r"(?m)^\s*КонецПроцедуры\s*$", text)
    )

    with zipfile.ZipFile(SRC) as source:
        config = source.read(CONFIG_ENTRY).decode("utf-8-sig")
        config, count = re.subn(
            r"<Version>1\.9\.0\.0</Version>", f"<Version>{VERSION}</Version>", config
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
    print("ZIP/XML/UTF-8/version/data-path/multi-strategy/gates/disabled job: OK")


if __name__ == "__main__":
    main()
