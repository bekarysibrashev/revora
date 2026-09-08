"""Build and verify Revora 1C extension v18.2 from the v18.1 archive.

v18.2 fixes the ScheduledJob MethodName exported by 1C XML: a scheduled
job references an exported common-module procedure through the qualified
metadata path ``CommonModule.<module>.<procedure>``.
"""
import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_ZIP = BASE_DIR / "RevoraExtensionReady-v18.1-complete-sync.zip"
OUT_ZIP = BASE_DIR / "RevoraExtensionReady-v18.2-complete-sync.zip"
SERVER_SOURCE = BASE_DIR / "РвОбменСервер.bsl"
FORM_SOURCE = BASE_DIR / "РвНастройкиОбмена.Форма.Модуль.bsl"

SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
BOM = b"\xef\xbb\xbf"


def module_bytes(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def main() -> None:
    server = module_bytes(SERVER_SOURCE)
    form = module_bytes(FORM_SOURCE)

    with zipfile.ZipFile(SRC_ZIP) as source:
        config = source.read(CONFIG_ENTRY).decode("utf-8-sig")
        config, count = re.subn(
            r"<Version>1\.8\.1\.0</Version>",
            "<Version>1.8.2.0</Version>",
            config,
        )
        assert count == 1

        job = source.read(JOB_ENTRY).decode("utf-8-sig")
        old_method = "<MethodName>РвОбменСервер.ВыполнитьРегламентнуюСинхронизацию</MethodName>"
        new_method = "<MethodName>CommonModule.РвОбменСервер.ВыполнитьРегламентнуюСинхронизацию</MethodName>"
        assert job.count(old_method) == 1
        job = job.replace(old_method, new_method)

        with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as output:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == CONFIG_ENTRY:
                    data = config.encode("utf-8")
                elif item.filename == JOB_ENTRY:
                    data = job.encode("utf-8")
                elif item.filename == SERVER_ENTRY:
                    data = server
                elif item.filename == FORM_ENTRY:
                    data = form
                output.writestr(item, data)

    with zipfile.ZipFile(OUT_ZIP) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            raw = archive.read(name)
            if name.endswith(".xml"):
                ET.fromstring(raw)
            if name.endswith((".xml", ".bsl")):
                raw.decode("utf-8-sig")
        assert archive.read(SERVER_ENTRY) == server
        assert archive.read(FORM_ENTRY) == form
        config_check = archive.read(CONFIG_ENTRY).decode("utf-8-sig")
        job_check = archive.read(JOB_ENTRY).decode("utf-8-sig")
        assert "<Version>1.8.2.0</Version>" in config_check
        assert new_method in job_check
        assert "<Use>false</Use>" in job_check

    server_text = SERVER_SOURCE.read_text(encoding="utf-8-sig")
    assert 'Возврат "1.8.2.0";' in server_text
    assert len(re.findall(r"(?m)^\s*Функция\b", server_text)) == len(
        re.findall(r"(?m)^\s*КонецФункции\s*$", server_text)
    )
    assert len(re.findall(r"(?m)^\s*Процедура\b", server_text)) == len(
        re.findall(r"(?m)^\s*КонецПроцедуры\s*$", server_text)
    )

    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    print(f"Built: {OUT_ZIP.name}")
    print(f"Size: {OUT_ZIP.stat().st_size} bytes")
    print(f"SHA-256: {digest}")
    print(f"MethodName: {new_method[12:-13]}")
    print("ZIP/XML/UTF-8/modules/version/BSL balance: OK")


if __name__ == "__main__":
    main()
