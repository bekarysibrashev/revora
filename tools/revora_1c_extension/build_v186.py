"""Build and verify Revora 1C extension v18.6 from the v18.5 archive.

v18.6 stops diagnosing and tries to settle the question, running both
remaining hypotheses in a single pass so no further diagnostic ZIP is
needed to choose between them.

The cheap one goes first, because it needs no privileges at all:
СформироватьВыручкуПоУслугам executes ONE dataset of the report schema
(.Найти("Запрос")) while the DCS composes the report from all of them. If
the schema holds more than one dataset, the direct query is behind by
construction and access rights are irrelevant. The schema's dataset count,
names, links, calculated fields and parameters are now reported.

The second is the control run: the same query, same parameters, same three
aggregates, executed with RLS lifted. Its boundaries are deliberate --
privileged mode is entered locally around one read-only query and left in
the same frame including on the exception path (the call is counted, so
each Истина is matched by exactly one Ложь); no field and no entity is
added to what Revora exports; ВЫБРАТЬ РАЗРЕШЕННЫЕ is not removed from any
query anywhere, it simply stops excluding rows while privileged; nothing
is disabled globally; and if the configuration refuses the switch the
function returns Выполнен = Ложь with the error text and the ordinary path
continues unchanged.

The control result is adopted for the breakdowns only when quantity,
revenue and before-discount ALL reproduce the ИТОГО row of the same run,
and only when the ordinary path did not already agree. The invariants are
read from that run's own ИТОГО row rather than hard-coded, so the test is
not fitted to one period, and "larger" or "closer to the expected figure"
is never a reason to accept a result.

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
SRC_ZIP = BASE_DIR / "RevoraExtensionReady-v18.5-complete-sync.zip"
OUT_ZIP = BASE_DIR / "RevoraExtensionReady-v18.6-complete-sync.zip"
SERVER_SOURCE = BASE_DIR / "РвОбменСервер.bsl"
FORM_SOURCE = BASE_DIR / "РвНастройкиОбмена.Форма.Модуль.bsl"

SERVER_ENTRY = "CommonModules/РвОбменСервер/Ext/Module.bsl"
FORM_ENTRY = "CommonForms/РвНастройкиОбмена/Ext/Form/Module.bsl"
CONFIG_ENTRY = "Configuration.xml"
JOB_ENTRY = "ScheduledJobs/РвПочасоваяСинхронизация.xml"
BOM = b"\xef\xbb\xbf"

VERSION = "1.8.6.0"

# Every guarded substitution the new revision must actually contain. If a
# future edit drops one of these, the corresponding report silently goes
# back to querying all of history.
GUARDED_REPORTS = (
    "ОказанныеУслугиПоВрачу",
    "АнализОплатПоВрачам",
    "ПациентыПосетившиеКлиникуЗаПериод",
)
NEW_SUMMARY_KEYS = (
    "schema_datasets",
    "schema_dataset_names",
    "schema_dataset_links",
    "control_ran",
    "control_quantity",
    "control_revenue",
    "control_before_discount",
    "control_invariants_hold",
    "control_mode_restored",
    "breakdown_source",
    "total_row_headers",
    "total_row_number_taken",
    "query_rows",
    "query_quantity",
    "query_before_discount",
    "query_uses_allowed_only",
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
            r"<Version>1\.8\.5\.0</Version>",
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

    # The whole point of v18.4: the diagnostics reach the sync window, not
    # just the snapshot. Guard both the hand-off and the rendering.
    for field in ("ИтогОтчета", "ИтогЗапроса", "ИтогРазница", "КолонокИтога",
                  "ВзятаКолонка", "ЧислаИтога", "ЗаголовкиИтога", "ВзятоЧисло",
                  "СтрокЗапроса", "КоличествоЗапроса", "БезСкидкиЗапроса",
                  "ТолькоРазрешенные", "НаборовСхемы", "КонтрольВыполнен",
                  "КонтрольИнварианты", "ИсточникРазрезов"):
        assert f'Результат.Вставить("{field}"' in server_text, f"not handed over: {field}"
        assert f"Итоги.{field}" in server_text, f"not rendered: {field}"
    assert server_text.count("ВЫВОД:") == 3, "the three verdicts must all be present"

    # The verdict must turn on the quantity comparison, not on how many
    # columns happen to be present -- that is the v18.4 mistake.
    assert "КоличествоОтчета" in server_text and "Итоги.КоличествоЗапроса" in server_text
    assert "ЧастиСходятся" in server_text, "the part-sum check must be present"
    assert "ЗАГЛУШКА" not in server_text

    # Privileged mode: entered once, left on both the success and the
    # failure path, and never left switched on.
    assert server_text.count("УстановитьПривилегированныйРежим(Истина)") == 1
    assert server_text.count("УстановитьПривилегированныйРежим(Ложь)") == 2
    assert server_text.count("Функция КонтрольныйСборБезОграниченийRLS(") == 1
    assert "РежимВосстановлен" in server_text

    # РАЗРЕШЕННЫЕ is never stripped from a query -- only observed.
    assert 'СтрЗаменить(ТекстЗапроса, "РАЗРЕШЕННЫЕ"' not in server_text
    assert "РАЗРЕШЕННЫЕ\", \"\"" not in server_text

    # The control result may only be adopted through the invariant gate.
    assert "ИнвариантыКонтроля" in server_text
    assert 'ИсточникРазрезов = "privileged_control"' in server_text
    assert "Не ОбычныйСошелся И ИнвариантыКонтроля" in server_text

    # One gathering routine, used by both paths, so they cannot drift.
    assert server_text.count("Функция СобратьУслугиИзЗапроса(") == 1
    assert server_text.count("СобратьУслугиИзЗапроса(Запрос)") == 3

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
