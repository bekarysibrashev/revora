"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/modules/auth";
import { getLossMap } from "@/modules/losses";
import { api } from "@/shared/api-client";
import { CoverageInfo, DataState, DateFilters, PageHeader, money, queryString, useFilters } from "@/shared/ui";
import s from "./overview.module.css";

const DetailReport = dynamic(() => import("./detail-report"));
type Source = { data_as_of: string | null; coverage: Record<string, CoverageInfo>; official_metric_codes?: string[] };
type Overview = {
  finance: { revenue_payment: string; meta: Source };
  sales: { appointments_completed: number; meta: Source };
  new_contacts: { total: number; data_as_of: string | null };
};

function Figure({ label, value, note, featured }: { label: string; value: string; note: string; featured?: boolean }) {
  return <article className={featured ? s.featured : s.figure}><h2>{label}</h2><strong>{value}</strong><small>{note}</small></article>;
}

export default function DashboardPage() {
  const { filters } = useFilters();
  const { user } = useAuth();
  const query = queryString(filters);
  const [expanded, setExpanded] = useState(false);
  const dashboard = useQuery({ queryKey: ["dashboard", query], queryFn: () => api<Overview>(`/dashboard/ceo?${query}`) });
  const losses = useQuery({ queryKey: ["loss-map", query], queryFn: () => getLossMap(query), enabled: !!user && (user.role !== "administrator" || !!filters.branch_id) });
  const d = dashboard.data;
  const summary = losses.data?.summary;
  const rows = losses.data?.items.filter(item => item.status === "open")
    .sort((a,b) => Number(b.severity === "critical") - Number(a.severity === "critical") || Number(b.estimated_amount) - Number(a.estimated_amount)).slice(0,3) || [];
  const payment = d?.finance.meta.coverage?.revenue_payment;
  const visits = d?.sales.meta.coverage?.appointments_completed;
  const paidKnown = payment ? payment.is_exact || payment.is_partial : d?.finance.meta.official_metric_codes?.includes("revenue_payment");
  const visitsKnown = visits ? visits.is_exact || visits.is_partial : Boolean(d?.sales.appointments_completed);
  const hasReport = paidKnown || visitsKnown || d?.sales.meta.data_as_of || d?.finance.meta.data_as_of || d?.new_contacts.data_as_of;
  return <div className={s.overview}>
    <PageHeader title="Обзор клиники" subtitle="Деньги, приёмы и обращения за выбранный период" action={<DateFilters/>}/>
    <DataState loading={dashboard.isLoading} error={dashboard.error}>
      {d && (hasReport ? <section className={s.figures} aria-label="Основные показатели">
        <Figure featured label="Получено от пациентов" value={paidKnown ? money(d.finance.revenue_payment) : "—"} note={payment?.is_partial ? "Только за выгруженную часть периода" : paidKnown ? "Фактические оплаты · 1С" : "Нет отчёта об оплатах"}/>
        <Figure label="Завершённые приёмы" value={visitsKnown ? String(d.sales.appointments_completed) : "—"} note={visits?.is_partial ? "Только за выгруженную часть периода" : visitsKnown ? "По данным 1С" : "Нет отчёта о приёмах"}/>
        <Figure label="Новые номера" value={d.new_contacts.data_as_of || d.new_contacts.total > 0 ? String(d.new_contacts.total) : "—"} note="Впервые обратились по телефону или в WhatsApp"/>
      </section> : <section className={s.setup}><span className={s.kicker}>Источники данных</span><h2>За этот период пока нет сводки</h2><p>Выберите период с выгрузкой или отправьте отчёт из 1С. После загрузки здесь появятся оплаты и завершённые приёмы.</p>{user?.role === "owner" && <Link href="/admin">Перейти к настройкам 1С →</Link>}</section>)}
    </DataState>
    <section className={s.queue}>
      <header><div><span className={s.kicker}>Работа с пациентами</span><h2>Кому нужно уделить внимание</h2></div><Link href="/losses">Карта потерь →</Link></header>
      {user?.role === "administrator" && !filters.branch_id ? <p>Выберите филиал, чтобы увидеть его обращения.</p> :
       losses.isLoading ? <p role="status">Загружаем карточки…</p> :
       losses.isError ? <p role="status">Не удалось загрузить карту. <button onClick={() => losses.refetch()}>Повторить</button></p> :
       summary && <><div className={s.meta}><span>Открыто <b>{summary.open_count}</b></span><span>В работе <b>{summary.in_progress_count}</b></span>{Number(summary.estimated_total)>0 && <span>Потенциал, оценка <b>{money(summary.estimated_total)}</b></span>}</div>
       {rows.length ? <ul>{rows.map(item => <li key={item.id}><div><span className={s.priority}>{item.severity==="critical"?"Высокий приоритет":"Проверить"}</span><h3>{item.title}</h3><p>{item.recommended_action}</p></div></li>)}</ul> : <p>Открытых карточек в этой выборке нет. После загрузки данных пересчитайте карту потерь.</p>}</>}
    </section>
    {(user?.role === "owner" || user?.role === "manager") && <section className={s.details}><button aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}><span>Подробный отчёт<small>Финансы, продажи, маркетинг и врачи</small></span><b aria-hidden="true">{expanded?"−":"+"}</b></button>{expanded && <DetailReport/>}</section>}
  </div>;
}
