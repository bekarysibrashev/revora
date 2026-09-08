# Revora 1C Extension v18 — "complete-sync"

`RevoraExtensionReady-v18-complete-sync.zip`
SHA-256: `bbe6bf564d999849c40455337ba8635690c6ef81ef26c61aa5c1edb6a915144d`

Built from the proven, currently-installed production build
(`RevoraExtensionReady-v17-operations.zip`, "Revora 1.7.0.0") as the
skeleton, with exactly two BSL modules replaced and one new metadata object
(a disabled-by-default scheduled job) added. Nothing else in the extension
changed: the 7 official report functions, the daily/control snapshot
builders, and every existing HTTP-send procedure are byte-for-byte what is
already running in production today, except where this document says
otherwise.

Source of truth for the two changed modules is the top-level tracked files
in this directory — `РвОбменСервер.bsl` and
`РвНастройкиОбмена.Форма.Модуль.bsl` — **not** the copies under `package/`.
The `package/` mirror is stale (its settings-form module still says
"Revora 1.1.0", an old hardcoded string, and does not match anything that
has actually shipped since); it was not touched by this change and should
not be treated as authoritative.

## Root causes fixed (Tasks 1–2 of the audit)

### 1. "Начислено" (accrued doctor revenue) showing 0 KZT

`СформироватьВыручкуПоУслугам` computed the per-doctor accrual breakdown
correctly, then **silently discarded the entire `doctor_revenue_accrual`
metric** whenever it didn't reconcile to the official report total to
within 0.01 KZT (`РазницаИтогов < 0.01`). On real data — rounding, a
service captured under a slightly different official-report bucket, a
doctor with no assigned specialization — an exact match is the exception,
not the rule, so the metric was dropped on nearly every real sync, even
though the underlying numbers were correct and available. This is exactly
why a sync could report "no errors" while the dashboard still showed 0: the
data never left 1C's memory, the extension chose not to send it.

**Fix**: the metric is now always sent. The reconciliation difference is
still computed and attached to the snapshot for diagnostics
(`doctor_accrual_reconciliation_diff`, `doctor_accrual_rows`), but it no
longer gates whether real data reaches Revora.

### 2. "Разрезы оплат не отправлены" (payment breakdowns never sent)

Identical bug, same shape, in `СформироватьФактическиеПоступления`: the
branch/payment-method/cash-account payment breakdowns were computed but
only sent when they matched the official payments total exactly. Same
fix — the breakdowns are now always sent; `breakdowns_reconciliation_diff`
carries the diagnostic difference instead of gating anything.

### 3. Any single rejected operational record aborted the whole batch

`ОтправитьПакетОперационныхДанных` treated a response with `rejected > 0`
as a hard failure and aborted the sync (raising an exception), even when
199 of 200 records in the batch were accepted. One bad record — a
malformed date, a branch code Revora doesn't recognise yet — could silently
stop patients, doctors, referrals, appointments or expenses from syncing
for the rest of the run. It is now a `Функция` that only raises on an
actual HTTP failure; a positive `rejected` count is parsed from the real
JSON response (`Новый ЧтениеJSON`, not a brittle substring search) and
surfaced in the sync summary instead of aborting anything.

## New in v18: sync observability (Task 7)

The manual sync result and the automatic hourly job (below) now share one
summary builder, `РвОбменСервер.ПредставлениеИтоговСинхронизации(Итоги)`,
which reports, separately:

- patients sent / doctors sent / направлений (referrals) sent / appointments
  sent / expenses sent — each with its own accepted/rejected counts, not one
  combined "operational data" line
- control snapshots and daily snapshots (unchanged counts, still reported)
- accrued-revenue breakdown rows and whether they reconciled to the official
  report exactly (informational — never blocks sending, see fix #1)
- payment breakdown rows and the same reconciliation status (fix #2)
- a rejected-records count, only ever shown when the server actually
  rejected something (fix #3) — "не отправлены" is now reserved for a
  dataset that is genuinely empty or genuinely not sent, not for one that
  was sent but didn't hit an exact reconciliation

## New in v18: hourly incremental sync (Task 8)

A new scheduled job, `ScheduledJob.РвПочасоваяСинхронизация`
(`РвОбменСервер.ВыполнитьРегламентнуюСинхронизацию`), **disabled by default**
(`Use=false` in the shipped metadata — an administrator must turn it on).

What it does on each run:
- Reads the same address/token used by manual sync
  (`ХранилищеСистемныхНастроек`, key `Revora/Обмен`) — no separate
  credentials, and the token is never written to the event log.
- Takes a single-flight lock (a timestamp in
  `ХранилищеСистемныхНастроек`, key `Revora/ПочасоваяСинхронизация`) so two
  overlapping runs never execute concurrently; a run that finds a fresh,
  unexpired lock exits immediately instead of piling up.
- Syncs an incremental window: from the last successful run's end (minus a
  few hours of overlap, so a late-arriving 1C document from just before the
  last run is never permanently missed) through now, falling back to a
  6-hour window on the very first run.
- On success, advances "last successful end" and records a timestamped
  success message. On failure (including a Render/network outage), it does
  **not** advance the watermark, so the next run naturally retries the same
  window — and the failure is logged with
  `ЗаписьЖурналаРегистрации`/`УровеньЖурналаРегистрации.Ошибка` plus the
  same journal storage the settings form reads to show "Последний
  автоматический запуск завершился ошибкой: …".
- Never touches the initial historical backfill — that remains the existing
  manual "Синхронизировать" flow with an explicit period, unchanged.

The settings form (`РвНастройкиОбмена`) now also shows the result of the
last automatic run (success timestamp or error message) alongside the
manual sync button, so an administrator can see both without leaving the
form.

**To enable hourly sync**: 1C Configurator → Администрирование →
Регламентные и фоновые задания → find "Revora: почасовая синхронизация" →
tick "Использование" (Use) and set the desired schedule (an hourly
schedule, e.g. every hour on the hour, is the intended cadence — the
metadata itself does not hard-code a period, that's configured here per
standard 1C practice). **To disable**: untick "Использование". Manual sync
from the settings form is completely independent and keeps working either
way.

## What did not change

- All 7 official report functions and their HTTP payloads: unchanged.
- Daily/control snapshot structure and counts: unchanged.
- Patient/doctor/appointment/expense operational record shapes: unchanged
  (only the batch-rejection handling around them changed, fix #3).
- No new fields were invented on the 1C side — every new summary field is
  derived from data the extension was already querying.

## Static verification performed before this build was finalized

- BSL balance: 53 `Функция` / 53 `КонецФункции`, 11 `Процедура` /
  11 `КонецПроцедуры` in the server module; 3/3 in the settings-form module.
- Every touched/added XML (`Configuration.xml`, `ConfigDumpInfo.xml`, the
  new `ScheduledJobs/РвПочасоваяСинхронизация.xml`) parses with
  `xml.etree.ElementTree`.
- `ConfigDumpInfo.xml` base-entry cross-check: all `ChildObjects` in
  `Configuration.xml` (including the new `ScheduledJob`) have a matching
  base entry.
- `zipfile.testzip()`: no bad entry.
- The embedded server and settings-form modules are byte-identical (modulo
  a UTF-8 BOM the 1C Configurator expects) to the standalone tracked
  `.bsl` files in this directory — the zip is not hand-edited separately
  from the source.
- All touched `.bsl`/`.xml` zip entries decode as valid UTF-8.
- Version string is `1.8.0.0` consistently in `Configuration.xml` and in
  `РвОбменСервер.ВерсияРасширения()`.

## Installing

1. 1C:Enterprise → Configurator → Конфигурация → Расширения → open the
   existing "Revora" extension → "Обновить из файлов…" → select
   `RevoraExtensionReady-v18-complete-sync.zip`.
2. Save/apply the extension (1C does not cryptographically validate
   `ConfigDumpInfo.xml`'s `configVersion` field — this build's approach was
   already proven by the diagnostic form/command that shipped in v17).
3. Run one manual sync from "Revora: настройки обмена" for a short period
   (see verification below) to confirm the fixes before deciding whether to
   also enable the hourly job.
4. Optionally enable the hourly scheduled job as described above.

## Verifying after install

Re-sync the same period that showed the original bug
(01.06.2026–02.06.2026, or any short recent period):

- The "Врачи" page's "Начислено" column should now show a real KZT figure
  matching (or close to, per the reconciliation diagnostics) the official
  per-doctor accrual — not 0.
- The manual sync result text should list patients / doctors / направлений
  / appointments / expenses / control snapshots / daily snapshots
  separately, plus accrued- and paid-revenue breakdown counts, rather than
  the old combined message.
- "разрезы оплат" should no longer say "не отправлены" unless there
  genuinely were no payment records for the period.
