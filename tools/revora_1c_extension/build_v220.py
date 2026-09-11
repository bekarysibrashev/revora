"""Build the final production 1C extension with safe automatic sync enabled."""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "RevoraExtensionReady-v21-production-sync.zip"
OUT = BASE / "RevoraExtensionReady-v22-automatic-production-sync.zip"
SERVER = BASE / "РвОбменСервер.bsl"
FORM = BASE / "РвНастройкиОбмена.Форма.Модуль.bsl"
SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
VERSION = "2.2.0.0"
BOM = b"\xef\xbb\xbf"


def encoded(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def main() -> None:
    text = SERVER.read_text(encoding="utf-8-sig")
    assert f'Возврат "{VERSION}";' in text
    assert f"// Revora_Обмен {VERSION}" in text
    for marker in (
        "АвтоматическийРежим = Ложь",
        "ПоследнийДеньДляСнимка",
        "Итоги.ОшибкиСинхронизации.Количество() > 0",
        "ПоследнийУспешныйКонец",
        "РвДлительностьАрендыСекунд",
    ):
        assert marker in text, f"missing automatic-sync invariant: {marker}"
    assert len(re.findall(r"(?m)^\s*Функция\b", text)) == len(
        re.findall(r"(?m)^\s*КонецФункции\s*$", text)
    )
    assert len(re.findall(r"(?m)^\s*Процедура\b", text)) == len(
        re.findall(r"(?m)^\s*КонецПроцедуры\s*$", text)
    )

    server, form = encoded(SERVER), encoded(FORM)
    with zipfile.ZipFile(SRC) as source, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as output:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == CONFIG_ENTRY:
                config = data.decode("utf-8-sig")
                config, count = re.subn(
                    r"<Version>2\.1\.0\.0</Version>", f"<Version>{VERSION}</Version>", config
                )
                assert count == 1
                data = config.encode("utf-8")
            elif item.filename == JOB_ENTRY:
                job = data.decode("utf-8-sig")
                job, count = job.replace("<Use>false</Use>", "<Use>true</Use>"), job.count("<Use>false</Use>")
                assert count == 1
                data = job.encode("utf-8")
            elif item.filename == SERVER_ENTRY:
                data = server
            elif item.filename == FORM_ENTRY:
                data = form
            output.writestr(item, data)

    with zipfile.ZipFile(OUT) as archive:
        assert archive.testzip() is None
        assert archive.read(SERVER_ENTRY) == server
        assert "<Use>true</Use>" in archive.read(JOB_ENTRY).decode("utf-8-sig")
        for name in archive.namelist():
            raw = archive.read(name)
            if name.endswith(".xml"):
                ET.fromstring(raw)
            if name.endswith((".xml", ".bsl")):
                raw.decode("utf-8-sig")

    print(f"Built: {OUT.name}")
    print(f"Size: {OUT.stat().st_size} bytes")
    print(f"SHA-256: {hashlib.sha256(OUT.read_bytes()).hexdigest()}")
    print("ZIP/XML/UTF-8/version/closed-day/watermark/enabled-job: OK")


if __name__ == "__main__":
    main()
