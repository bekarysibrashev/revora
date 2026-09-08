"""Builds RevoraExtensionReady-v18.1-complete-sync.zip from the v18 zip as a
skeleton, replacing only the two changed BSL modules and Configuration.xml's
version string. Then runs the same static verification v18's build used.
"""
import hashlib
import re
import zipfile
from pathlib import Path

BASE_DIR = Path(".")
SRC_ZIP = BASE_DIR / "RevoraExtensionReady-v18-complete-sync.zip"
OUT_ZIP = BASE_DIR / "RevoraExtensionReady-v18.1-complete-sync.zip"
SERVER_MODULE_PATH = BASE_DIR / "РвОбменСервер.bsl"
FORM_MODULE_PATH = BASE_DIR / "РвНастройкиОбмена.Форма.Модуль.bsl"

ZIP_SERVER_MODULE = "CommonModules/РвОбменСервер/Ext/Module.bsl"
ZIP_FORM_MODULE = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
ZIP_CONFIGURATION = "Configuration.xml"

BOM = b"\xef\xbb\xbf"

def read_module_with_bom(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    return BOM + text.encode("utf-8")

def main() -> None:
    assert SRC_ZIP.exists(), f"missing skeleton {SRC_ZIP}"
    src = zipfile.ZipFile(SRC_ZIP)

    config_xml = src.read(ZIP_CONFIGURATION).decode("utf-8")
    new_config_xml, n = re.subn(
        r"<Version>1\.8\.0\.0</Version>", "<Version>1.8.1.0</Version>", config_xml
    )
    assert n == 1, f"expected exactly 1 Version replacement, got {n}"

    new_server_module = read_module_with_bom(SERVER_MODULE_PATH)
    new_form_module = read_module_with_bom(FORM_MODULE_PATH)

    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == ZIP_CONFIGURATION:
                data = new_config_xml.encode("utf-8")
            elif item.filename == ZIP_SERVER_MODULE:
                data = new_server_module
            elif item.filename == ZIP_FORM_MODULE:
                data = new_form_module
            out.writestr(item, data)

    print(f"Built {OUT_ZIP}")

    # --- Static verification, mirroring what v18's build already did ---
    verify = zipfile.ZipFile(OUT_ZIP)
    bad = verify.testzip()
    assert bad is None, f"testzip() reported a bad entry: {bad}"
    print("testzip(): OK, no bad entry")

    for name in verify.namelist():
        if name.endswith("/"):
            continue
        raw = verify.read(name)
        if name.endswith(".xml"):
            import xml.etree.ElementTree as ET
            ET.fromstring(raw)
        if name.endswith((".xml", ".bsl")):
            raw.decode("utf-8")
    print("All .xml parse; all .xml/.bsl entries decode as UTF-8: OK")

    server_in_zip = verify.read(ZIP_SERVER_MODULE)
    form_in_zip = verify.read(ZIP_FORM_MODULE)
    assert server_in_zip == new_server_module, "server module mismatch vs source .bsl"
    assert form_in_zip == new_form_module, "form module mismatch vs source .bsl"
    print("Embedded modules byte-identical (modulo BOM) to tracked .bsl sources: OK")

    config_check = verify.read(ZIP_CONFIGURATION).decode("utf-8")
    assert "<Version>1.8.1.0</Version>" in config_check
    server_text = SERVER_MODULE_PATH.read_text(encoding="utf-8")
    assert 'Возврат "1.8.1.0";' in server_text
    assert "// Revora_Обмен 1.8.1.0" in server_text
    print("Version 1.8.1.0 consistent in Configuration.xml and ВерсияРасширения(): OK")

    func_count = len(re.findall(r"(?m)^\s*Функция\b", server_text))
    endfunc_count = len(re.findall(r"(?m)^\s*КонецФункции\s*$", server_text))
    proc_count = len(re.findall(r"(?m)^\s*Процедура\b", server_text))
    endproc_count = len(re.findall(r"(?m)^\s*КонецПроцедуры\s*$", server_text))
    assert func_count == endfunc_count and func_count > 0
    assert proc_count == endproc_count and proc_count > 0
    print(f"Функция/КонецФункции balance: {func_count}/{endfunc_count} OK")
    print(f"Процедура/КонецПроцедуры balance: {proc_count}/{endproc_count} OK")

    # Confirm the 7 official report functions are untouched vs v18 baseline.
    official_functions = [
        "СформироватьВыручкуПоУслугам",
        "СформироватьФактическиеПоступления",
        "СформироватьЗарплату",
        "СформироватьПоступления",
        "СформироватьПациентов",
        "СформироватьЗаписи",
        "СформироватьВыручкуПоВрачам",
    ]

    def extract_function(text: str, name: str) -> str:
        pattern = re.compile(
            r"Функция\s+" + re.escape(name) + r"\(.*?\nКонецФункции", re.S
        )
        m = pattern.search(text)
        assert m, f"function {name} not found"
        return m.group()

    src_fresh = zipfile.ZipFile(SRC_ZIP)
    src_server_bytes = src_fresh.read(ZIP_SERVER_MODULE)
    old_server_text = src_server_bytes[len(BOM):].decode("utf-8") if src_server_bytes.startswith(BOM) else src_server_bytes.decode("utf-8")
    diffs = []
    for name in official_functions:
        old_fn = extract_function(old_server_text, name)
        new_fn = extract_function(server_text, name)
        if old_fn != new_fn:
            diffs.append(name)
    if diffs:
        print(f"WARNING: official report functions changed vs v18: {diffs}")
    else:
        print(f"All {len(official_functions)} official report functions byte-identical to v18: OK")

    size = OUT_ZIP.stat().st_size
    sha256 = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    print(f"Size: {size} bytes")
    print(f"SHA-256: {sha256}")

if __name__ == "__main__":
    main()
