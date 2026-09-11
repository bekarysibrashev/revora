"""Static acceptance contract for the single final 1C production release.

The real scheduler still needs one check in the clinic's 1C, but these tests
prevent shipping the two regressions we can prove locally: treating today's
unfinished financial report as fatal and advancing the watermark on a partial
snapshot failure.
"""

from hashlib import sha256
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "tools" / "revora_1c_extension"
MODULE = EXTENSION / "РвОбменСервер.bsl"
ARCHIVE = EXTENSION / "RevoraExtensionReady-v22-automatic-production-sync.zip"


def test_automatic_mode_sends_current_operations_but_only_closed_daily_finance() -> None:
    source = MODULE.read_text(encoding="utf-8-sig")

    assert "АвтоматическийРежим = Ложь" in source
    assert "ПоследнийДеньДляСнимка = НачалоДня(ТекущаяДата()) - 24 * 60 * 60" in source
    assert source.index("СинхронизироватьОперационныеДанные(") < source.index(
        "ПоследнийДеньДляСнимка = НачалоДня(КонецПериода)"
    )


def test_partial_snapshot_failure_does_not_advance_watermark() -> None:
    source = MODULE.read_text(encoding="utf-8-sig")
    condition = (
        "Если Итоги.ОперационныхОтклонено > 0 Или "
        "Итоги.ОшибкиСинхронизации.Количество() > 0 Тогда"
    )
    partial = source.index(condition)
    success = source.index('Журнал.Вставить("ПоследнийУспешныйКонец", КонецПериода)', partial)

    assert partial < success
    assert "ЗахваченоДо" in source
    assert "ПоследнийУспешныйКонец - 3 * 60 * 60" in source


def test_final_zip_is_enabled_valid_and_contains_exact_module() -> None:
    assert ARCHIVE.is_file()
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        module = archive.read("CommonModules/РвОбменСервер/Ext/Module.bsl")
        config = archive.read("Configuration.xml").decode("utf-8-sig")
        job = archive.read("ScheduledJobs/РвПочасоваяСинхронизация.xml").decode(
            "utf-8-sig"
        )

    assert module.decode("utf-8-sig") == MODULE.read_text(encoding="utf-8-sig")
    assert "<Version>2.2.0.0</Version>" in config
    assert "<Use>true</Use>" in job
    assert re.fullmatch(r"[0-9a-f]{64}", sha256(ARCHIVE.read_bytes()).hexdigest())
