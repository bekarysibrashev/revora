# Revora 1C Extension v18.1 — "complete-sync" (safety + observability pass)

`RevoraExtensionReady-v18.1-complete-sync.zip`
(size and SHA-256 are stated in the delivery report for this change, and
should be re-verified against the actual file before installing.)

This is a follow-up to v18 (`RevoraExtensionReady-v18-complete-sync.zip`,
"Revora 1.8.0.0", documented in `README-v18-complete-sync.md`), built from
that same proven zip as the skeleton. Only the two BSL modules
(`РвОбменСервер.bsl`, `РвНастройкиОбмена.Форма.Модуль.bsl`) and
`Configuration.xml`'s version string changed. The 7 official report
functions, the daily/control snapshot builders, the operational
patient/doctor/appointment/expense record shapes, and the scheduled job's
metadata object are unchanged from v18.

Source of truth for the two changed modules is, as with v18, the top-level
tracked files in this directory — `РвОбменСервер.bsl` and
`РвНастройкиОбмена.Форма.Модуль.bsl` — never the stale `package/` mirror.

## What changed since v18 (this pass fixed 8 specific problems)

### 1. Custom date-range picker could apply a mismatched from/to pair (frontend)

`frontend/shared/ui.tsx`'s `DateFilters()` had a `useEffect` that fired
`applyCustom()` on *any* single change to either date field — editing just
"С" sent a request pairing the new "С" against the still-old "По", and
closed the popover before "По" was ever picked. Fixed: the range is now
only ever applied by an explicit click on "Применить" (removed the
auto-apply effect entirely), the button is disabled until both fields hold
a valid range (`С <= По`), and an invalid pair is rejected rather than
silently swapped. Presets and cross-page persistence are unchanged. See
`frontend/shared/__tests__/DateFilters.test.tsx`.

### 2. Historical lead backfill treated every phone match as a lead

`backend/app/cli/backfill_leads.py` used to create a "won"/"new"/"lost" Lead
for any phone_hash that currently matched an *active* Patient, regardless of
whether that patient existed in 1C before or after the contact, and treated
an *inactive* old patient's phone as if no patient existed at all (silently
inflating "new"/"lost" counts for real, established patients). Rewritten:
the decision now compares the contact's first-touch time against the
matched Patient's `first_visit_at` (active or inactive — 1C marking someone
inactive does not erase the fact that a real relationship already existed).
A patient that existed before the contact creates no Lead at all; a contact
that came before the patient's first 1C visit is a genuine "won" lead; an
unmatched phone is "new"/"lost" by the existing 14-day cutoff; a matched
patient with no usable `first_visit_at` date is conservatively treated as
"not a lead" rather than guessed. See `resolve_lead_outcome` and its unit
tests in `backend/tests/test_backfill_leads.py`.

### 3. No responsible employee was ever attached to a backfilled lead

`Call.external_user` (Kcell's own raw agent/extension string) was never
resolved to a real `User` anywhere in the codebase. A new, explicit,
administrator-maintained mapping table (`kcell_extension_assignments`, see
migration `20260908_0037_kcell_extension_assignments.py`) now provides that
resolution — never by fuzzy/full-name matching. No row for an extension
means "unresolved" (never configured); a row that exists but is explicitly
unassigned means "ambiguous" (an administrator marked it as a shared line,
e.g. a front desk). WhatsApp has no per-message responsible-employee field,
so `WhatsAppConversation.assigned_user_id`'s *current* state is used as a
documented best-effort proxy only. See `resolve_assignment` and its tests.

`kcell_extension_assignments` has no UI of its own -- it is populated only
through `python -m app.cli.manage_kcell_assignments` (`list` /`set` /
`mark-ambiguous` / `delete`), see "Before running the lead backfill" below.

### 4. Backfill had no controlled, observable way to run in production

`backfill_leads.py` now supports `--dry-run` (computes and prints every
statistic without writing a single row) and always prints
`contacts_scanned`, `skipped_existing_patients`, `won`, `new`, `lost`,
`skipped_existing_leads`, `assigned`, `unresolved_assignment`,
`ambiguous_assignment`, `errors`. It is never run automatically — Render's
start command remains only `alembic upgrade head && uvicorn ...` (see
`render.yaml`) — and is invoked manually from Render's Shell tab:

```
python -m app.cli.backfill_leads --tenant-slug san-dental --dry-run
# review the printed stats, then, only with separate explicit approval:
python -m app.cli.backfill_leads --tenant-slug san-dental
```

Re-running it (dry-run or real) is always safe: existing Leads are never
touched (`ON CONFLICT ... DO NOTHING`), so a second run of the same range
only ever adds `skipped_existing_leads`.

### 5. One rejected operational record could be treated as a full success

`ОтправитьПакетОперационныхДанных` already only aborted on a real HTTP
failure (fixed in v18) and returned a rejected count — but the *reasons*
for rejection were discarded, and `ВыполнитьРегламентнуюСинхронизацию`
(the hourly job) advanced its watermark even when some records were
rejected, so those specific records would never be automatically resent.
Fixed:

- `ОтправитьПакетОперационныхДанных` now also parses the `errors` array the
  backend already returns (`{index, target_entity, external_id, message}` —
  short, structural messages only; confirmed by reading every
  `CanonicalWriteError` raise site in `canonical_writer.py`: never a phone
  number, token, or full record). Up to 5 reasons per batch, capped overall
  at 20 per sync run (`ДобавитьПричины`).
- The hourly job's run now has three states — `succeeded` (nothing
  rejected, watermark advances), `partial` (something was rejected,
  watermark does **not** advance — the same window is retried next run;
  already-accepted records are never rolled back and resending them is
  safe because the backend's writes are idempotent upserts), and `failed`
  (an exception — watermark also does not advance, same as before).
- The manual sync result text (`ПредставлениеИтоговСинхронизации`, shared
  by both manual sync and the hourly job) now shows the rejected count
  *and* up to 5 of the actual safe reasons, not just a bare number.

### 6. The hourly job's overlap lock was a 2-hour heuristic, not a real lease

The lock lived in `ХранилищеСистемныхНастроек` as a "started at" timestamp,
checked with a fixed "busy if less than 2 hours have passed" rule — if the
process crashed mid-run, the job would refuse to run again for up to 2
hours. Fixed: it is now an explicit lease with a stated expiry
(`ЗахваченоДо`, `РвДлительностьАрендыСекунд()` = 45 minutes — generous
against a normal incremental run's actual duration of seconds to minutes,
but far shorter than the old 2-hour worst case), released immediately on
normal completion exactly as before.

**Honest limits, stated plainly**: 1C's own scheduled-job scheduler on a
single-infobase deployment does not normally start a second instance of the
*same* scheduled job while one is still running — that already covers the
ordinary "two hourly firings overlap" case on its own. This lease is a
second, defense-in-depth layer for what the platform does **not** promise:
a manual invocation of `ВыполнитьРегламентнуюСинхронизацию` from the
Configurator/Enterprise client while the scheduled job is mid-run, a
distributed (RIB) deployment with independent schedulers, or a cluster with
multiple working processes — none of these have been tested against a real
multi-process 1C cluster. The read-then-write against
`ХранилищеСистемныхНастроек` is **not** an atomic database-level lock (not
`БлокировкаДанных`); a true atomic guarantee would need a new metadata
object (an Информационный регистр with a managed lock), which cannot be
validated without a real Configurator and is out of scope for this change.
If that stronger guarantee matters, it is the recommended next step.

### 7. Hourly sync polish

Ships disabled (`Use=false`) exactly as in v18 — an administrator must
enable it. The journal now also records `ПоследнийЗапущенВ` (started_at),
`ПоследнееЗавершеноВ` (finished_at), `ПоследнийДиапазон` (the exact window
synced), `ПоследнееПринято`/`ПоследнееОтклонено` (accepted/rejected
counts), and `ПоследнийСтатус` (`succeeded`/`partial`/`failed`), alongside
the existing `ПоследнееСообщение`/`ПоследняяОшибка`. The settings form
(`РвНастройкиОбмена`) now distinguishes all three states instead of only
"error" vs "success" — a partial run explicitly says how many records were
rejected and that the same window will be retried automatically. See
"Verifying after install" below for how to enable/disable and check status.

### 8. Version string was inconsistent (`1.7.0.0` in one place, `1.8.0.0` in others)

Unified to **`Revora 1.8.1.0`** everywhere: the `РвОбменСервер.bsl` header
comment, `ВерсияРасширения()`, `Configuration.xml`'s `<Version>`, this
README, and the built ZIP's filename. The manual and scheduled sync
messages already derive their version text from `ВерсияРасширения()`, so
they update automatically.

## What did NOT change

- All 7 official report functions and their HTTP payloads.
- Daily/control snapshot structure and counts.
- Patient/doctor/appointment/expense operational record shapes.
- The scheduled job's metadata object (still `Use=false` by default).
- No new fields were invented on the 1C side — every new field is derived
  from data the extension, or the backend response, already carries.

## Static verification performed before this build was finalized

Same methodology as v18 (see `README-v18-complete-sync.md`'s "Static
verification" section), re-run against this build:

- BSL `Функция`/`КонецФункции` and `Процедура`/`КонецПроцедуры` balance
  checked automatically after every edit (54/54 functions, 12/12
  procedures in the server module after this pass; 3/3 total in the
  settings-form module).
- Every touched/added XML parses with `xml.etree.ElementTree`.
- `zipfile.testzip()`: no bad entry.
- The embedded server and settings-form modules are byte-identical (modulo
  the UTF-8 BOM the 1C Configurator expects) to the standalone tracked
  `.bsl` files in this directory.
- All touched `.bsl`/`.xml` zip entries decode as valid UTF-8.
- Version string is `1.8.1.0` consistently in `Configuration.xml` and in
  `РвОбменСервер.ВерсияРасширения()`.
- The seven official report functions and the snapshot builders are
  byte-for-byte identical to v18 (only the two modules named above changed,
  and within them only the specific functions/procedures listed in items
  1–8 above).

**What this does not, and cannot, verify without a real 1C Configurator**:
that the extension actually compiles and loads cleanly in a live
information base ("Проверка модулей"), that the scheduled job's metadata is
accepted by a real Configurator save, and that the lease/lock behaves as
described under real concurrent execution or a real process crash. All of
that requires the manual verification steps below, performed by a human
with access to the real 1C base — this document does not claim otherwise.

## Before running the lead backfill: configure Kcell extension assignments

`backend/app/cli/backfill_leads.py` resolves a Kcell-sourced lead's
`assigned_user_id` only from `kcell_extension_assignments` (see problem 3
above) -- it never guesses from a name, and it never writes to that table
itself. Run this sequence once per tenant, before the first real (non
`--dry-run`) backfill, from the same shell that has `DATABASE_URL` pointing
at that tenant's database (e.g. Render's Shell tab):

```
# 1. See which Kcell extensions have actually placed calls, and which of
#    those are already mapped -- run this first, every time.
python -m app.cli.manage_kcell_assignments list --tenant-slug san-dental

# 2. For each extension listed as unconfigured that has one clear owner,
#    map it to that person's existing Revora account (same tenant only --
#    the command refuses a user from any other tenant).
python -m app.cli.manage_kcell_assignments set --tenant-slug san-dental \
    --external-user 101 --user-email doctor@example.com

# 3. For an extension with no single owner (e.g. a shared front-desk
#    line), mark it explicitly rather than leaving it unconfigured -- this
#    is what makes backfill_leads report it as "ambiguous" instead of
#    "unresolved", an intentionally different and more informative outcome.
python -m app.cli.manage_kcell_assignments mark-ambiguous --tenant-slug san-dental \
    --external-user front-desk

# 4. Re-run list and confirm "Seen in calls but not yet configured" is
#    either empty or contains only extensions you've deliberately decided
#    to leave unresolved for now.
python -m app.cli.manage_kcell_assignments list --tenant-slug san-dental
```

Only after this -- run `backfill_leads --dry-run` (see problem 4 above),
review its `assigned` / `unresolved_assignment` / `ambiguous_assignment`
counts against what step 4 showed, and only then run backfill for real.
Assignments can be revisited any time afterwards (`set` again to correct a
mapping, `delete` to revert to unresolved) -- backfill only ever reads this
table, so changing it later does not touch any Lead already created; it
only affects the next run.

## Installing

1. 1C:Enterprise → Configurator → Конфигурация → Расширения → open the
   existing "Revora" extension → "Обновить из файлов…" → select
   `RevoraExtensionReady-v18.1-complete-sync.zip`.
2. Save/apply the extension, then run "Проверка модулей" in the
   Configurator to confirm the two changed modules compile cleanly — this
   step can only be done in a real Configurator, not by this document.
3. Run one manual sync from "Revora: настройки обмена" for a short, recent
   period to confirm items 1–5, 7, 8 above before deciding whether to also
   (re-)enable the hourly job.

## Verifying after install

- The custom date-range popover (frontend) only applies once both dates are
  picked and "Применить" is clicked; editing one field alone must not close
  the popover or send a request.
- Before the first real backfill for a tenant, run the
  `manage_kcell_assignments` setup sequence in "Before running the lead
  backfill" above. Then run
  `python -m app.cli.backfill_leads --tenant-slug san-dental --dry-run`
  from Render's Shell tab and review the printed statistics before ever
  running it for real.
- Manually sync a period where you know at least one record was previously
  rejected (or force one, e.g. a record 1C hasn't sent branch data for) and
  confirm the sync result text now names a safe reason, not just a count.
- In "Revora: настройки обмена", confirm the automatic-run status area
  distinguishes "выполнен частично" from a plain error or a plain success.
- To enable hourly sync: 1C Configurator → Администрирование → Регламентные
  и фоновые задания → "Revora: почасовая синхронизация" → tick
  "Использование" and set an hourly schedule. To disable: untick it. Manual
  sync keeps working either way, independent of the scheduled job.
