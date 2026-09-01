"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ReactNode } from "react";

export function PageHeader({ title, subtitle, action }: { title: string; subtitle: string; action?: ReactNode }) { return <div className="page-header"><div><h1>{title}</h1><p>{subtitle}</p></div>{action}</div>; }
function defaultStart(days = 90) { const value = new Date(); value.setDate(value.getDate() - (days - 1)); return value.toISOString().slice(0,10); }
export function DateFilters() { const router = useRouter(); const path = usePathname(); const search = useSearchParams(); const end = new Date().toISOString().slice(0, 10); const start = defaultStart(); function update(values:Record<string,string>) { const p = new URLSearchParams(search.toString()); Object.entries(values).forEach(([key,value])=>p.set(key,value)); router.push(`${path}?${p}`); } function preset(days:number) { update({date_from:defaultStart(days),date_to:end}); } return <div className="date-filter-wrap"><div className="date-presets"><button onClick={()=>preset(7)}>7 дней</button><button onClick={()=>preset(30)}>30 дней</button><button onClick={()=>preset(90)}>90 дней</button></div><div className="filters"><label>С<input type="date" value={search.get("date_from") || start} onChange={e => update({date_from:e.target.value})} /></label><label>По<input type="date" value={search.get("date_to") || end} onChange={e => update({date_to:e.target.value})} /></label></div></div>; }
export function queryString(search: URLSearchParams | ReadonlyURLSearchParams) { const today = new Date(); const p = new URLSearchParams(); p.set("date_from", search.get("date_from") || defaultStart()); p.set("date_to", search.get("date_to") || today.toISOString().slice(0,10)); if (search.get("branch_id")) p.set("branch_id", search.get("branch_id")!); return p.toString(); }
type ReadonlyURLSearchParams = { get(name: string): string | null };
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
