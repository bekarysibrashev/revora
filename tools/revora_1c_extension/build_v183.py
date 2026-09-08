"""Build and verify Revora 1C extension v18.3 from the v18.2 archive.

v18.3 changes only the server common module, and only in ways that add
information or refuse to proceed on a silent failure. No metric formula
changes, so the numbers the clinic already trusts stay identical:

1. Period substitution into the standard reports' dataset queries now goes
   through ПодставитьПериодВЗапрос, which raises if the pattern did not
   match. Previously СтрЗаменить failed silently, the &НачалоПериода /
   &КонецПериода parameters never appeared, and the turnover virtual table
   ran over the entire history while claiming to cover the requested
   period. Three call sites were exposed: ОказанныеУслугиПоВрачу,
   АнализОплатПоВрачам and ПациентыПосетившиеКлиникуЗаПериод.

2. The clinic revenue total is still read from the standard report's ИТОГО
   row exactly as before, but the direct-query sum it used to overwrite is
   now kept alongside it, and the difference ships in the snapshot.

3. The ИТОГО row is now reported in full: how many numeric columns it had,
   which one was taken, and their values. This is what distinguishes "the
   scrape read the wrong column" from "the report and the register really
   do disagree" -- the two hypotheses behind the ~1.97M KZT accrued gap --
   in a single sync run.

4. Sales rows with no employee are labelled "Не указано" instead of an
   empty string, so Revora counts them as genuinely unattributed money
   rather than confusing them with the unexplained residual.

The build itself is byte-for-byte the v18.2 archive with the server module
and Configuration.xml version replaced, so the forms, reports, roles and
the (still disabled) scheduled job are carried over untouched.
"""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_ZIP = BASE_DIR / "RevoraExtensionReady-v18.2-complete-sync.zip"
OUT_ZIP = BASE_DIR / "RevoraExtensionReady-v18.3-complete-sync.zip"
SERVER_SOURCE = BASE_DIR / "РвОбменСервер.bsl"
FORM_SOURCE = BASE_DIR / "РвНастройкиОбмена.Форма.Модуль.bsl"

SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
BOM = b"\xef\xbb\xbf"

VERSION = "1.8.3.0"

# Every guarded substitution the new revision must actually contain. If a
# future edit drops one of these, the corresponding report silently goes
# back to querying all of history.
GUARDED_REPORTS = (
    "ОказанныеУслугиПоВрачу",
    "АнализОплатПоВрачам",
    "ПациентыПосетившиеКлиникуЗаПериод",
)
NEW_SUMMARY_KEYS = (
    "clinic_total_report",
    "clinic_total_query",
    "clinic_total_difference",
    "total_row_numeric_columns",
    "total_row_column_taken",
    "total_row_numbers",
)


def module_bytes(path: Path) -> bytes:
    return BOM + path.read_text(encoding="utf-8-sig").encode("utf-8")


def main() -> None:
    server = module_bytes(SERVER_SOURCE)
    form = module_bytes(FORM_SOURCE)

    with zipfile.ZipFile(SRC_ZIP) as source:
        config = source.read(CONFIG_ENTRY).decode("utf-8-sig")
        config, count = re.subn(
            r"<Version>1\.8\.2\.0</Version>",
            f"<Version>{VERSION}</Version>",
            config,
        )
        assert count == 1, "Configuration.xml version not found"

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
        for name in archive.namelist():
            raw = archive.read(name)
            if name.endswith(".xml"):
                ET.fromstring(raw)
            if name.endswith((".xml", ".bsl")):
                raw.decode("utf-8-sig")
        assert archive.read(SERVER_ENTRY) == server
        assert archive.read(FORM_ENTRY) == form
        config_check = archive.read(CONFIG_ENTRY).decode("utf-8-sig")
        assert f"<Version>{VERSION}</Version>" in config_check

        # v18.2 fixed the scheduled job's qualified MethodName and left the
        # job disabled. Both must survive this rebuild untouched: hourly
        # sync is explicitly not being enabled yet.
        job_check = archive.read(JOB_ENTRY).decode("utf-8-sig")
        assert (
            "<MethodName>CommonModule.РвОбменСервер.ВыполнитьРегламентнуюСинхронизацию</MethodName>"
            in job_check
        )
        assert "<Use>false</Use>" in job_check

    server_text = SERVER_SOURCE.read_text(encoding="utf-8-sig")
    assert f'Возврат "{VERSION}";' in server_text
    assert f"// Revora_Обмен {VERSION}" in server_text
    assert len(re.findall(r"(?m)^\s*Функция\b", server_text)) == len(
        re.findall(r"(?m)^\s*КонецФункции\s*$", server_text)
    )
    assert len(re.findall(r"(?m)^\s*Процедура\b", server_text)) == len(
        re.findall(r"(?m)^\s*КонецПроцедуры\s*$", server_text)
    )

    # No unguarded period substitution may remain: that is the silent
    # all-history failure this revision exists to prevent.
    # Exactly one СтрЗаменить may touch a query text, and it is the one
    # inside ПодставитьПериодВЗапрос, which is guarded. Any other is an
    # unguarded call site that would fail silently.
    assert server_text.count("СтрЗаменить(ТекстЗапроса") == 1, (
        "an unguarded period substitution is back"
    )
    for report in GUARDED_REPORTS:
        assert f'"{report}");' in server_text, f"unguarded: {report}"
    assert server_text.count("Функция ПодставитьПериодВЗапрос(") == 1

    for key in NEW_SUMMARY_KEYS:
        assert f'"{key}"' in server_text, f"missing snapshot key: {key}"

    # The value returned to callers must still come from the same place.
    assert "Функция ДиагностикаИтогаВыручкиШтатногоОтчета(" in server_text
    assert (
        "Возврат ДиагностикаИтогаВыручкиШтатногоОтчета(НачалоПериода, КонецПериода).Значение;"
        in server_text
    )

    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    print(f"Built: {OUT_ZIP.name}")
    print(f"Size: {OUT_ZIP.stat().st_size} bytes")
    print(f"SHA-256: {digest}")
    print(f"Version: {VERSION}")
    print(f"Guarded period substitutions: {', '.join(GUARDED_REPORTS)}")
    print("ZIP/XML/UTF-8/modules/version/BSL balance/guards/summary keys: OK")


if __name__ == "__main__":
    main()
