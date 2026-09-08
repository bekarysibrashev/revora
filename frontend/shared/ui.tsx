"use client";
import { ReactNode, createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

export function PageHeader({ title, subtitle, action }: { title: string; subtitle: string; action?: ReactNode }) { return <div className="page-header"><div><h1>{title}</h1><p>{subtitle}</p></div>{action}</div>; }

export type Filters = { date_from: string; date_to: string; branch_id: string };

const FILTERS_STORAGE_KEY = "revora.filters.v1";

function todayIso() { return new Date().toISOString().slice(0, 10); }
function isoDate(value: Date) { return value.toISOString().slice(0, 10); }
function daysAgoIso(days: number) { const value = new Date(); value.setDate(value.getDate() - (days - 1)); return isoDate(value); }
function startOfMonth(value: Date) { return new Date(value.getFullYear(), value.getMonth(), 1); }
function endOfMonth(value: Date) { return new Date(value.getFullYear(), value.getMonth() + 1, 0); }
function defaultFilters(): Filters { return { date_from: daysAgoIso(90), date_to: todayIso(), branch_id: "" }; }

function loadFilters(): Filters {
  if (typeof window === "undefined") return defaultFilters();
  try {
    const raw = window.localStorage.getItem(FILTERS_STORAGE_KEY);
    if (!raw) return defaultFilters();
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.date_from === "string" && typeof parsed.date_to === "string") {
      return { date_from: parsed.date_from, date_to: parsed.date_to, branch_id: typeof parsed.branch_id === "string" ? parsed.branch_id : "" };
    }
  } catch {}
  return defaultFilters();
}

type FiltersContextValue = { filters: Filters; setRange: (dateFrom: string, dateTo: string) => void; setBranch: (branchId: string) => void };
const FiltersContext = createContext<FiltersContextValue | null>(null);

// Keeps the selected period and branch in one place (persisted to localStorage)
// so switching tabs never silently resets the filters the person just set.
export function FiltersProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Filters>(() => loadFilters());
  useEffect(() => {
    try { window.localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(filters)); } catch {}
  }, [filters]);
  const value = useMemo<FiltersContextValue>(() => ({
    filters,
    setRange: (dateFrom, dateTo) => setFilters((prev) => ({ ...prev, date_from: dateFrom, date_to: dateTo })),
    setBranch: (branchId) => setFilters((prev) => ({ ...prev, branch_id: branchId })),
  }), [filters]);
  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>;
}

export function useFilters() {
  const ctx = useContext(FiltersContext);
  if (!ctx) throw new Error("useFilters() must be used within a FiltersProvider");
  return ctx;
}

type Preset = { key: string; label: string; range: () => { date_from: string; date_to: string } };

const PRESETS: Preset[] = [
  { key: "today", label: "Сегодня", range: () => ({ date_from: todayIso(), date_to: todayIso() }) },
  { key: "yesterday", label: "Вчера", range: () => { const d = new Date(); d.setDate(d.getDate() - 1); return { date_from: isoDate(d), date_to: isoDate(d) }; } },
  { key: "7", label: "Последние 7 дней", range: () => ({ date_from: daysAgoIso(7), date_to: todayIso() }) },
  { key: "30", label: "Последние 30 дней", range: () => ({ date_from: daysAgoIso(30), date_to: todayIso() }) },
  { key: "90", label: "Последние 90 дней", range: () => ({ date_from: daysAgoIso(90), date_to: todayIso() }) },
  { key: "this_month", label: "Этот месяц", range: () => ({ date_from: isoDate(startOfMonth(new Date())), date_to: todayIso() }) },
  { key: "last_month", label: "Прошлый месяц", range: () => { const d = new Date(); d.setMonth(d.getMonth() - 1); return { date_from: isoDate(startOfMonth(d)), date_to: isoDate(endOfMonth(d)) }; } },
  { key: "year", label: "Этот год", range: () => ({ date_from: `${new Date().getFullYear()}-01-01`, date_to: todayIso() }) },
];

const MONTHS_SHORT_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
function formatShort(value: string) { const parts = value.split("-"); const month = Number(parts[1]) - 1; return `${Number(parts[2])} ${MONTHS_SHORT_RU[month] || parts[1]}`; }

function rangeLabel(filters: Filters, activeKey?: string) {
  const preset = activeKey && PRESETS.find((p) => p.key === activeKey);
  if (preset) return preset.label;
  if (filters.date_from === filters.date_to) return formatShort(filters.date_from);
  const fromYear = filters.date_from.slice(0, 4);
  const toYear = filters.date_to.slice(0, 4);
  const from = formatShort(filters.date_from);
  const to = fromYear === toYear ? formatShort(filters.date_to) : `${formatShort(filters.date_to)} ${toYear}`;
  return `${from} – ${to}`;
}

function CalendarIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M7 2.5v3M17 2.5v3M4 9h16M5.5 4.5h13A1.5 1.5 0 0 1 20 6v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19V6a1.5 1.5 0 0 1 1.5-1.5Z" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function ChevronIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// A single trigger button that opens a popover with quick presets plus a custom
// range, replacing the old always-visible preset row + two bare date inputs.
// The selected range lives in FiltersContext, so it now persists as the person
// moves between tabs instead of resetting on every navigation.
export function DateFilters() {
  const { filters, setRange } = useFilters();
  const [open, setOpen] = useState(false);
  const [draftFrom, setDraftFrom] = useState(filters.date_from);
  const [draftTo, setDraftTo] = useState(filters.date_to);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDraftFrom(filters.date_from);
    setDraftTo(filters.date_to);
  }, [filters.date_from, filters.date_to]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const activeKey = useMemo(() => {
    const match = PRESETS.find((p) => { const r = p.range(); return r.date_from === filters.date_from && r.date_to === filters.date_to; });
    return match?.key;
  }, [filters.date_from, filters.date_to]);

  function applyPreset(preset: Preset) {
    const r = preset.range();
    setRange(r.date_from, r.date_to);
    setOpen(false);
  }

  function applyCustom() {
    if (!draftFrom || !draftTo) return;
    const from = draftFrom <= draftTo ? draftFrom : draftTo;
    const to = draftFrom <= draftTo ? draftTo : draftFrom;
    setRange(from, to);
    setOpen(false);
  }

  // A custom "С"/"По" edit used to only ever reach FiltersContext (and thus
  // every page's react-query key) after a separate click on "Применить".
  // Until that click, the two inputs visibly showed the new dates while
  // every card kept rendering the previously committed period -- easy to
  // read as "the filter didn't work" rather than "not applied yet". Both
  // fields already hold a complete, valid date at all times (they start
  // from, and are reset back to, the committed filters), so once either one
  // actually changes we already have a full, valid custom range: commit it
  // immediately, still through the same single atomic applyCustom() call
  // used everywhere else, never a partial from-only/to-only update.
  useEffect(() => {
    if (!draftFrom || !draftTo) return;
    if (draftFrom === filters.date_from && draftTo === filters.date_to) return;
    applyCustom();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftFrom, draftTo]);

  return (
    <div className="date-range" ref={wrapRef}>
      <button type="button" className={`date-range-trigger${open ? " open" : ""}`} onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="dialog">
        <CalendarIcon />
        <span>{rangeLabel(filters, activeKey)}</span>
        <span className="chevron"><ChevronIcon /></span>
      </button>
      {open && (
        <div className="date-range-pop" role="dialog" aria-label="Выбор периода">
          <div className="date-range-presets">
            {PRESETS.map((preset) => (
              <button type="button" key={preset.key} className={activeKey === preset.key ? "active" : ""} onClick={() => applyPreset(preset)}>
                {preset.label}
                {activeKey === preset.key && <i aria-hidden="true">✓</i>}
              </button>
            ))}
          </div>
          <div className="date-range-custom">
            <p>Произвольный период</p>
            <div className="date-range-custom-inputs">
              <label>С<input type="date" value={draftFrom} max={draftTo || undefined} onChange={(e) => setDraftFrom(e.target.value)} /></label>
              <label>По<input type="date" value={draftTo} min={draftFrom || undefined} onChange={(e) => setDraftTo(e.target.value)} /></label>
            </div>
            <button type="button" className="date-range-apply" onClick={applyCustom}>Применить</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function queryString(filters: Filters) {
  const p = new URLSearchParams();
  p.set("date_from", filters.date_from);
  p.set("date_to", filters.date_to);
  if (filters.branch_id) p.set("branch_id", filters.branch_id);
  return p.toString();
}

export function Metric({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "good" | "bad" }) { return <article className="metric"><p>{label}</p><strong className={tone || ""}>{value}</strong>{note && <small>{note}</small>}</article>; }
export function DataState({ loading, error, children }: { loading: boolean; error: unknown; children: ReactNode }) {
  if (loading) return (
    <div className="panel skeleton-panel" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">Собираем показатели…</span>
      <div className="skeleton-cards">
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
      </div>
      <div className="skeleton skeleton-line medium" />
      <div className="skeleton skeleton-line" />
      <div className="skeleton skeleton-line short" />
    </div>
  );
  if (error) return <div className="panel error-box">{error instanceof Error ? error.message : "Не удалось загрузить данные"}</div>;
  return <>{children}</>;
}
export function AsOf({ value }: { value?: string | null }) { return <p className="as-of">Данные актуальны на: {value ? new Date(value).toLocaleString("ru-RU") : "нет загруженных данных"}</p>; }
export function money(value: string | number | null | undefined) { return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "KZT", maximumFractionDigits: 0 }).format(Number(value || 0)); }
export function percent(value: string | number | null | undefined) { return `${(Number(value || 0) * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`; }

export type CoverageInfo = {
  requested_from: string;
  requested_to: string;
  covered_from: string | null;
  covered_to: string | null;
  covered_months: string[];
  missing_months: string[];
  coverage_ratio: number;
  is_partial: boolean;
  is_exact: boolean;
};

const MONTH_LABELS_RU = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"];
function monthLabel(key: string) { const [year, month] = key.split("-"); const index = Number(month) - 1; return `${MONTH_LABELS_RU[index] || month} ${year}`; }

// Renders a warning whenever a date range is not fully backed by real 1С data,
// so a partial or missing total is never mistaken for a complete one (never a
// silent 0 or a partial sum presented as if it covered the whole period).
export function CoverageBanner({ coverage, label }: { coverage?: CoverageInfo | null; label?: string }) {
  if (!coverage || coverage.is_exact) return null;
  const prefix = label ? `${label}: ` : "";
  if (!coverage.covered_months.length) {
    return <div className="coverage-banner coverage-banner-unavailable"><strong>{prefix}нет данных за выбранный период.</strong> Отправьте снимки 1С за этот диапазон, чтобы увидеть показатели.</div>;
  }
  if (!coverage.is_partial) return null;
  return (
    <div className="coverage-banner coverage-banner-partial">
      <strong>{prefix}показаны данные только за {coverage.covered_months.map(monthLabel).join(", ")}.</strong>
      {" "}Нет данных за {coverage.missing_months.map(monthLabel).join(", ")} — сумма посчитана только по доступным месяцам ({Math.round(coverage.coverage_ratio * 100)}% периода).
    </div>
  );
}
