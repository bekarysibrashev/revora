"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/shared/api-client";
import { AsOf, DataState, DateFilters, PageHeader, money, percent, queryString } from "@/shared/ui";

type Dashboard = { finance:{revenue_accrual:string;revenue_payment:string;total_expenses:string;net_profit:string;net_cash_flow:string;closing_balance:string|null;cashflow_is_complete:boolean;meta:{data_as_of:string|null;official_metric_codes:string[];is_reconciled:boolean}};sales:{leads_total:number;leads_won:number;lead_conversion_rate:string;appointments_total:number;appointments_completed:number;appointments_cancelled:number;appointments_no_show:number;patients_total:number;patients_primary:number;patients_repeat:number;appointment_completion_rate:string;paid_revenue:string;meta:{data_as_of:string|null}};top_doctors:{doctor_id:string;full_name:string;specialty:string|null;appointments_completed:number;completion_rate:string;revenue_accrual:string;revenue_payment:string}[];marketing:{total_spend:string;total_attributed_revenue:string;roas:string|null};new_contacts:{total:number;from_kcell:number;from_whatsapp:number;existing_patients_contacted:number;data_as_of:string|null} };
type Pnl = { revenue_accrual:string;revenue_payment:string;total_expenses:string;payroll_accrual:string;gross_profit:string;ebitda:string;net_profit:string;expense_classification_rate:string;profit_is_complete:boolean;profit_label:string;meta:{data_as_of:string|null;official_metric_codes:string[];is_reconciled:boolean} };
type Meta = { total_spend:string;currency:string|null;leads:number;conversations_started:number;cost_per_lead:string|null;data_as_of:string|null };
type Insights = {items:{id:string;severity:string;title:string;description:string}[]};

function previousQuery(current:string) {
  const params = new URLSearchParams(current);
  const from = new Date(`${params.get("date_from")}T00:00:00`);
  const to = new Date(`${params.get("date_to")}T00:00:00`);
  const days = Math.max(1,Math.round((to.getTime()-from.getTime())/86400000)+1);
  const previousTo = new Date(from); previousTo.setDate(previousTo.getDate()-1);
  const previousFrom = new Date(previousTo); previousFrom.setDate(previousFrom.getDate()-(days-1));
  params.set("date_from",previousFrom.toISOString().slice(0,10));
  params.set("date_to",previousTo.toISOString().slice(0,10));
  return params.toString();
}

function Kpi({label,value,source,note,missing=false,tone}:{label:string;value?:string;source:string;note?:string;missing?:boolean;tone?:"good"|"bad"}) {
  return <article className={`ceo-kpi ${missing?"missing":""}`}><div><p>{label}</p><span>{source}</span></div><strong className={tone||""}>{missing?"Не хватает данных":value}</strong>{missing?<small>Нужен дополнительный объект из 1С</small>:note&&<small>{note}</small>}</article>;
}

function SectionTitle({title,subtitle}:{title:string;subtitle:string}) { return <div className="section-title"><div><h2>{title}</h2><p>{subtitle}</p></div></div>; }

export default function DashboardPage() {
  const search=useSearchParams(); const query=queryString(search); const previous=previousQuery(query);
  const dashboard=useQuery({queryKey:["dashboard",query],queryFn:()=>api<Dashboard>(`/dashboard/ceo?${query}`)});
  const previousDashboard=useQuery({queryKey:["dashboard-previous",previous],queryFn:()=>api<Dashboard>(`/dashboard/ceo?${previous}`)});
  const pnl=useQuery({queryKey:["dashboard-pnl",query],queryFn:()=>api<Pnl>(`/finance/pnl?${query}`)});
  const meta=useQuery({queryKey:["dashboard-meta",query],queryFn:()=>api<Meta>(`/marketing/meta/overview?${query}`),retry:false});
  const insights=useQuery({queryKey:["insights",search.get("branch_id")],queryFn:()=>api<Insights>(`/dashboard/insights${search.get("branch_id")?`?branch_id=${search.get("branch_id")}`:""}`)});

  return <>
    <PageHeader title="Обзор клиники" subtitle="Dashboard CEO · все ключевые показатели из ТЗ" action={<DateFilters/>}/>
    <DataState loading={dashboard.isLoading||pnl.isLoading} error={dashboard.error||pnl.error}>
      {dashboard.data&&pnl.data&&(()=>{
        const currentRevenue=Number(dashboard.data.finance.revenue_accrual||0);
        const previousRevenue=Number(previousDashboard.data?.finance.revenue_accrual||0);
        const growth=previousRevenue?((currentRevenue-previousRevenue)/previousRevenue):null;
        const margin=currentRevenue?Number(pnl.data.net_profit)/currentRevenue:null;
        const averageCheck=dashboard.data.sales.appointments_completed?currentRevenue/dashboard.data.sales.appointments_completed:null;
        const hasSales=Boolean(dashboard.data.sales.meta.data_as_of);
        const official=new Set(pnl.data.meta.official_metric_codes||[]);
        const metaLeads=(meta.data?.leads||0)+dashboard.data.new_contacts.total;
        const cpl=metaLeads&&meta.data?Number(meta.data.total_spend)/metaLeads:null;
        const chartData=[
          {name:"Выручка",previous:previousRevenue,current:currentRevenue},
          {name:"Расходы",previous:Number(previousDashboard.data?.finance.total_expenses||0),current:Number(dashboard.data.finance.total_expenses||0)},
          ...(pnl.data.profit_is_complete?[{name:"Прибыль",previous:Number(previousDashboard.data?.finance.net_profit||0),current:Number(dashboard.data.finance.net_profit||0)}]:[]),
        ];
        return <>
          <section className="ceo-hero">
            <div><p className="eyebrow">Управленческий срез</p><h2>{money(currentRevenue)}</h2><span>выручка за выбранный период</span></div>
            <div className="ceo-hero-stats"><span>{pnl.data.profit_label}<strong>{pnl.data.profit_is_complete?money(pnl.data.net_profit):"Не подтверждено"}</strong></span><span>{dashboard.data.finance.cashflow_is_complete?"Денежный поток":"Поток по доступным данным"}<strong>{money(dashboard.data.finance.net_cash_flow)}</strong></span><span>Рост<strong>{growth===null?"—":percent(growth)}</strong></span></div>
          </section>

          <SectionTitle title="Финансы" subtitle="Фактические показатели из финансовых регистров 1С"/>
          <section className="ceo-kpi-grid">
            <Kpi label="Выручка · начисление" value={money(currentRevenue)} source={official.has("revenue_accrual")?"Отчёт 1С":"OData 1С"} note={`Оплачено ${money(dashboard.data.finance.revenue_payment)}`}/>
            <Kpi label="Выручка · оплата" value={money(dashboard.data.finance.revenue_payment)} source={official.has("revenue_payment")?"Отчёт 1С":"OData 1С"}/>
            <Kpi label="Предыдущий период" value={money(previousRevenue)} source="1С" note="Период той же длины"/>
            <Kpi label="Темп роста" value={growth===null?"—":percent(growth)} source="Расчёт" tone={growth!==null&&growth>=0?"good":"bad"}/>
            <Kpi label="Валовая прибыль" source="Расчёт" missing={!pnl.data.profit_is_complete} value={money(pnl.data.gross_profit)}/>
            <Kpi label="Начислено зарплаты" value={money(pnl.data.payroll_accrual)} source={official.has("payroll_accrual")?"Отчёт 1С":"OData 1С"} note="Справочно, без повторного прибавления к расходам"/>
            <Kpi label="EBITDA" source="Расчёт" missing={!pnl.data.profit_is_complete} value={money(pnl.data.ebitda)}/>
            <Kpi label={pnl.data.profit_label} source="Расчёт" missing={!pnl.data.profit_is_complete} value={money(pnl.data.net_profit)} tone={Number(pnl.data.net_profit)>=0?"good":"bad"}/>
            <Kpi label="Маржинальность" value={margin===null?"—":percent(margin)} source="Расчёт" missing={!pnl.data.profit_is_complete}/>
            <Kpi label="Средний чек завершённого приёма" value={averageCheck===null?"—":money(averageCheck)} source="Расчёт 1С" missing={averageCheck===null}/>
            <Kpi label="Количество пациентов" value={String(dashboard.data.sales.patients_total)} source="1С" missing={!hasSales}/>
          </section>
          <section className="panel ceo-chart"><div className="panel-head"><div><h2>Динамика к предыдущему периоду</h2><p>Сопоставление периодов одинаковой длины, KZT</p></div></div><ResponsiveContainer width="100%" height={280}><BarChart data={chartData}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="name"/><YAxis tickFormatter={value=>`${Math.round(Number(value)/1000000)}м`}/><Tooltip formatter={(value)=>money(Number(value))}/><Bar dataKey="previous" name="Предыдущий" fill="#BFC9C3" radius={[6,6,0,0]}/><Bar dataKey="current" name="Текущий" fill="#2F725B" radius={[6,6,0,0]}/></BarChart></ResponsiveContainer></section>

          <SectionTitle title="Продажи и пациенты" subtitle="Воронка от обращения до оплаты лечения"/>
          <section className="ceo-kpi-grid">
            <Kpi label="Записи на приём" value={String(dashboard.data.sales.appointments_total)} source="1С" missing={!hasSales}/>
            <Kpi label="Пациенты" value={String(dashboard.data.sales.patients_total)} source="1С" missing={!hasSales}/>
            <Kpi label="Первичные пациенты" value={String(dashboard.data.sales.patients_primary)} source="1С" missing={!hasSales}/>
            <Kpi label="Повторные пациенты" value={String(dashboard.data.sales.patients_repeat)} source="1С" missing={!hasSales}/>
            <Kpi label="Новые номера" value={String(dashboard.data.new_contacts.total)} source="Kcell + WhatsApp + сверка 1С" note={`${dashboard.data.new_contacts.from_kcell} звонки · ${dashboard.data.new_contacts.from_whatsapp} WhatsApp`}/>
            <Kpi label="Обращение → лечение" source="1С" missing/>
            <Kpi label="Консультация → план" source="1С" missing/>
            <Kpi label="План → оплата" source="1С" missing/>
          </section>

          <SectionTitle title="Маркетинг" subtitle="Заявки Meta и новые номера из Kcell и WhatsApp"/>
          <section className="ceo-kpi-grid">
            <Kpi label="Лиды и новые номера" value={String(metaLeads)} source="Meta + Kcell + WhatsApp" note={`${meta.data?.leads||0} Meta · ${dashboard.data.new_contacts.total} впервые обратились`}/>
            <Kpi label="CPL" value={cpl===null?"—":new Intl.NumberFormat("ru-RU",{style:"currency",currency:meta.data?.currency||"USD",maximumFractionDigits:2}).format(cpl)} source="Расчёт"/>
            <Kpi label="CAC" source="1С + Meta" missing/>
            <Kpi label="ROAS" value={dashboard.data.marketing.roas?`${Number(dashboard.data.marketing.roas).toFixed(2)}×`:undefined} source="Атрибуция" missing={!dashboard.data.marketing.roas}/>
            <Kpi label="ROMI" source="1С + Meta" missing/>
            <Kpi label="Стоимость первичного пациента" source="1С + Meta" missing/>
          </section>

          <SectionTitle title="Операционная эффективность" subtitle="Загрузка клиники и потери расписания"/>
          <section className="ceo-kpi-grid">
            <Kpi label="Загрузка врачей" source="1С" missing/>
            <Kpi label="Загрузка кабинетов" source="1С" missing/>
            <Kpi label="Отмены" value={String(dashboard.data.sales.appointments_cancelled)} source="1С" missing={!hasSales}/>
            <Kpi label="Переносы" source="1С" missing/>
            <Kpi label="Неявки" value={String(dashboard.data.sales.appointments_no_show)} source="1С" missing={!hasSales}/>
          </section>

          <section className="panel"><div className="panel-head"><div><h2>Лучшие врачи</h2><p>Оплаченная выручка из официального отчёта 1С, нагрузка — из OData</p></div></div><div className="table-wrap"><table><thead><tr><th>Врач</th><th>Специальность</th><th>Завершено</th><th>Выполнение</th><th>Оплачено</th></tr></thead><tbody>{dashboard.data.top_doctors.map(item=><tr key={item.doctor_id}><td><strong>{item.full_name}</strong></td><td>{item.specialty||"—"}</td><td>{item.appointments_completed}</td><td>{percent(item.completion_rate)}</td><td>{money(item.revenue_payment)}</td></tr>)}{!dashboard.data.top_doctors.length&&<tr><td colSpan={5} className="empty">Не хватает данных из 1С: врачи, записи и связь выручки с врачом</td></tr>}</tbody></table></div></section>
          {!!insights.data?.items.length&&<section className="insights"><h2>Что требует внимания</h2>{insights.data.items.slice(0,3).map(item=><article key={item.id} className={`insight ${item.severity}`}><span>!</span><div><strong>{item.title}</strong><p>{item.description}</p></div></article>)}</section>}
          <AsOf value={dashboard.data.finance.meta.data_as_of}/>
        </>;
      })()}
    </DataState>
  </>;
}
