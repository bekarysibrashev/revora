"""Build Revora 2.3: actionable, patient-level loss-map sync."""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "RevoraExtensionReady-v22-automatic-production-sync.zip"
OUT = BASE / "RevoraExtensionReady-v23-actionable-loss-map.zip"
SERVER = BASE / "РвОбменСервер.bsl"
SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
VERSION = "2.3.0.0"
BOM = b"\xef\xbb\xbf"


def encoded(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def main() -> None:
    text = SERVER.read_text(encoding="utf-8-sig")
    assert f'Возврат "{VERSION}";' in text
    assert f"// Revora_Обмен {VERSION}" in text
    for marker in (
        "НормализованныйТелефон",
        'Данные.Вставить("phone_e164", НормализованныйТелефон)',
        'Данные.Вставить("phone_hash", Хэш)',
        "ПоследнийУспешныйКонец",
        "РвДлительностьАрендыСекунд",
    ):
        assert marker in text, f"missing v23 invariant: {marker}"
    assert len(re.findall(r"(?m)^\s*Функция\b", text)) == len(
        re.findall(r"(?m)^\s*КонецФункции\s*$", text)
    )
    assert len(re.findall(r"(?m)^\s*Процедура\b", text)) == len(
        re.findall(r"(?m)^\s*КонецПроцедуры\s*$", text)
    )

    server = encoded(SERVER)
    with zipfile.ZipFile(SRC) as source, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as output:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == CONFIG_ENTRY:
                config = data.decode("utf-8-sig")
                config, count = re.subn(
                    r"<Version>2\.2\.0\.0</Version>",
                    f"<Version>{VERSION}</Version>",
                    config,
                )
                assert count == 1
                data = config.encode("utf-8")
            elif item.filename == SERVER_ENTRY:
                data = server
            output.writestr(item, data)

    with zipfile.ZipFile(OUT) as archive:
        assert archive.testzip() is None
        assert archive.read(SERVER_ENTRY) == server
        for name in archive.namelist():
            raw = archive.read(name)
            if name.endswith(".xml"):
                ET.fromstring(raw)
            if name.endswith((".xml", ".bsl")):
                raw.decode("utf-8-sig")

    print(f"Built: {OUT.name}")
    print(f"Size: {OUT.stat().st_size} bytes")
    print(f"SHA-256: {hashlib.sha256(OUT.read_bytes()).hexdigest()}")
    print("ZIP/XML/UTF-8/version/patient-phone invariants: OK")


if __name__ == "__main__":
    main()
