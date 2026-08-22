"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "@/shared/api-client";
import {
  DataState,
  DateFilters,
  Metric,
  PageHeader,
  money,
  queryString,
} from "@/shared/ui";

type Overview = {
  total_spend: string;
  total_attributed_revenue: string;
  roas: string | null;
  sources: {
    source: string;
    spend: string;
    attributed_revenue: string;
    roas: string | null;
  }[];
  data_as_of: string | null;
};

type MetaStatus = {
  accounts: {
    external_account_id: string;
    name: string;
    account_status: number;
    currency: string;
    timezone_name: string;
    last_error: string | null;
  }[];
};

type MetaOverview = {
  total_spend: string;
  currency: string | null;
  impressions: number;
  clicks: number;
  unique_clicks: number;
  link_clicks: number;
  outbound_clicks: number;
  landing_page_views: number;
  leads: number;
  purchases: number;
  conversations_started: number;
  messaging_connections: number;
  video_plays: number;
  video_thruplays: number;
  ctr: string | null;
  cpc: string | null;
  cpm: string | null;
  cost_per_lead: string | null;
  cost_per_conversation: string | null;
  click_to_conversation_rate: string | null;
  landing_page_view_rate: string | null;
  video_thruplay_rate: string | null;
  selected_account_id: string | null;
  comparison: {
    previous_date_from: string;
    previous_date_to: string;
    total_spend: string;
    conversations_started: number;
    leads: number;
    cost_per_conversation: string | null;
    spend_change: string | null;
    conversations_change: string | null;
    leads_change: string | null;
    cost_per_conversation_change: string | null;
  };
  alerts: {
    severity: string;
    code: string;
    account_external_id: string;
    campaign_external_id: string;
    campaign_name: string;
    title: string;
    description: string;
  }[];
  recommendations: {
    rank: number;
    action: "increase" | "keep" | "reduce" | "pause" | "insufficient_data";
    account_external_id: string;
    campaign_external_id: string;
    campaign_name: string;
    score: number;
    result_metric: string;
    results: number;
    cost_per_result: string | null;
    suggested_budget_change_percent: number;
    reason: string;
  }[];
  accounts: {
    account_external_id: string;
    account_name: string;
    currency: string;
    spend: string;
    impressions: number;
    clicks: number;
    conversations_started: number;
    leads: number;
    ctr: string | null;
    cpc: string | null;
    cost_per_conversation: string | null;
  }[];
  campaigns: {
    account_external_id: string;
    account_name: string;
    currency: string;
    campaign_external_id: string;
    campaign_name: string;
    status: string;
    effective_status: string;
    spend: string;
    impressions: number;
    clicks: number;
    unique_clicks: number;
    link_clicks: number;
    outbound_clicks: number;
    landing_page_views: number;
    leads: number;
    purchases: number;
    conversations_started: number;
    messaging_connections: number;
    video_plays: number;
    video_thruplays: number;
    ctr: string | null;
    cpc: string | null;
    cpm: string | null;
    cost_per_lead: string | null;
    cost_per_conversation: string | null;
    click_to_conversation_rate: string | null;
    landing_page_view_rate: string | null;
    video_thruplay_rate: string | null;
  }[];
  data_as_of: string | null;
};

function currency(value: string | number, code = "USD") {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: code,
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function change(value: string | null, inverse = false) {
  if (value === null) return "Нет данных за прошлый период";
  const numeric = Number(value) * 100;
  const sign = numeric > 0 ? "+" : "";
  const direction = inverse
    ? numeric <= 0
      ? "лучше"
      : "хуже"
    : numeric >= 0
      ? "выше"
      : "ниже";
  return `${sign}${numeric.toLocaleString("ru-RU", {
    maximumFractionDigits: 1,
  })}% · ${direction} прошлого периода`;
}

const recommendationLabel = {
  increase: "Увеличить",
  keep: "Оставить",
  reduce: "Снизить",
  pause: "Остановить",
  insufficient_data: "Мало данных",
};

export default function MarketingPage() {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const query = queryString(search);
  const selectedAccount = search.get("meta_account_id") || "";
  const metaQuery = new URLSearchParams(query);
  if (selectedAccount) metaQuery.set("account_id", selectedAccount);
  const [showStopped, setShowStopped] = useState(false);
  const overview = useQuery({
    queryKey: ["marketing", query],
    queryFn: () => api<Overview>(`/marketing/overview?${query}`),
  });
  const metaStatus = useQuery({
    queryKey: ["meta-status"],
    queryFn: () => api<MetaStatus>("/marketing/meta/status"),
    refetchInterval: 60_000,
  });
  const meta = useQuery({
    queryKey: ["meta-overview", metaQuery.toString()],
    queryFn: () =>
      api<MetaOverview>(`/marketing/meta/overview?${metaQuery.toString()}`),
    refetchInterval: 300_000,
  });

  function chooseMetaAccount(value: string) {
    const params = new URLSearchParams(search.toString());
    value
      ? params.set("meta_account_id", value)
      : params.delete("meta_account_id");
    router.push(`${pathname}?${params.toString()}`);
  }
  const availableMetaAccounts =
    metaStatus.data?.accounts.filter((account) => account.account_status !== 0) ?? [];
  const metaTokenExpired = metaStatus.data?.accounts.some((account) =>
    /token|oauth|error 190|access.*expired|session.*expired/i.test(account.last_error ?? ""),
  );

  return (
    <>
      <PageHeader
        title="Маркетинг"
        subtitle="Какая реклама приносит обращения и куда направить бюджет"
        action={<DateFilters />}
      />

      {metaTokenExpired && (
        <section className="panel">
          <div className="error-box">
            Истёк доступ к Meta Ads. Попросите администратора переподключить Meta.
          </div>
        </section>
      )}

      <DataState loading={meta.isLoading} error={null}>
        {meta.data && (
          <>
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Рекламный кабинет</h2>
                  <p>Фильтр применяется ко всем показателям и кампаниям ниже.</p>
                </div>
                <select
                  aria-label="Рекламный кабинет Meta"
                  value={selectedAccount}
                  onChange={(event) => chooseMetaAccount(event.target.value)}
                >
                  <option value="">Все кабинеты</option>
                  {availableMetaAccounts.map((account) => (
                    <option
                      key={account.external_account_id}
                      value={account.external_account_id}
                    >
                      {account.name}
                    </option>
                  ))}
                </select>
              </div>
            </section>
            <section className="metric-grid">
              <Metric
                label="Расход Meta"
                value={currency(meta.data.total_spend, meta.data.currency || "USD")}
                note={change(meta.data.comparison.spend_change, true)}
              />
              <Metric
                label="WhatsApp-диалоги"
                value={meta.data.conversations_started.toLocaleString("ru-RU")}
                note={`${change(meta.data.comparison.conversations_change)} · Цена: ${
                  meta.data.cost_per_conversation
                    ? currency(
                        meta.data.cost_per_conversation,
                        meta.data.currency || "USD",
                      )
                    : "—"
                  }`}
              />
              <Metric
                label="Цена диалога"
                value={
                  meta.data.cost_per_conversation
                    ? currency(meta.data.cost_per_conversation, meta.data.currency || "USD")
                    : "—"
                }
                note={change(meta.data.comparison.cost_per_conversation_change, true)}
              />
              <Metric
                label="Лиды Meta"
                value={meta.data.leads.toLocaleString("ru-RU")}
                note={change(meta.data.comparison.leads_change)}
              />
            </section>
            <section className="panel marketing-chart">
              <div className="panel-head"><div><h2>Сравнение активных кампаний</h2><p>Расход и количество WhatsApp-диалогов за выбранный период</p></div></div>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={meta.data.campaigns.filter(item=>item.effective_status==="ACTIVE"||item.effective_status==="UNKNOWN").slice(0,8)} layout="vertical" margin={{left:20,right:25}}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false}/><XAxis type="number"/><YAxis type="category" dataKey="campaign_name" width={180} tick={{fontSize:11}}/><Tooltip formatter={(value,name)=>name==="spend"?currency(Number(value),meta.data?.currency||"USD"):Number(value).toLocaleString("ru-RU")}/><Bar dataKey="spend" name="Расход" fill="#2F725B" radius={[0,6,6,0]}/><Bar dataKey="conversations_started" name="Диалоги" fill="#B9D7C8" radius={[0,6,6,0]}/>
                </BarChart>
              </ResponsiveContainer>
            </section>
            <section className="panel budget-advisor">
              <div className="panel-head">
                <div>
                  <p className="eyebrow">Решение, а не набор цифр</p>
                  <h2>Куда перераспределить бюджет</h2>
                  <p>Кампании ранжируются по цене WhatsApp-диалога, а если диалогов нет — по цене лида Meta.</p>
                </div>
              </div>
              <div className="recommendation-list">
                {meta.data.recommendations.map((item) => (
                  <article className={`recommendation-card ${item.action}`} key={`${item.account_external_id}:${item.campaign_external_id}`}>
                    <div className="recommendation-rank">#{item.rank}</div>
                    <div>
                      <strong>{item.campaign_name}</strong>
                      <small>{item.results} · {item.result_metric} · цена {item.cost_per_result ? currency(item.cost_per_result, meta.data.currency || "USD") : "—"}</small>
                      <p>{item.reason}</p>
                    </div>
                    <div className="recommendation-decision">
                      <span className={`decision ${item.action}`}>{recommendationLabel[item.action]}</span>
                      <b>{item.suggested_budget_change_percent > 0 ? "+" : ""}{item.suggested_budget_change_percent}%</b>
                      <small>оценка {item.score}/100</small>
                    </div>
                  </article>
                ))}
                {!meta.data.recommendations.length && <p className="empty">Пока недостаточно результатов для рекомендации.</p>}
              </div>
              <p className="advisor-note">Важно: пока нет связки с 1С, Revora оптимизирует рекламные диалоги и лиды, а не фактически оплаченные лечения. После интеграции добавим реальную выручку и ROMI.</p>
            </section>
            {!!meta.data.alerts.length && (
              <section className="insights">
                <h2>Что требует внимания в Meta Ads</h2>
                {meta.data.alerts.map((alert) => (
                  <article
                    key={`${alert.code}:${alert.account_external_id}:${alert.campaign_external_id}`}
                    className={`insight ${alert.severity}`}
                  >
                    <span>!</span>
                    <div>
                      <strong>
                        {alert.title} · {alert.campaign_name}
                      </strong>
                      <p>{alert.description}</p>
                    </div>
                  </article>
                ))}
              </section>
            )}
            {!selectedAccount && meta.data.accounts.length > 1 && (
              <section className="panel">
                <h2>Сравнение кабинетов</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Кабинет</th>
                        <th>Расход</th>
                        <th>Лиды</th>
                        <th>Диалоги</th>
                        <th>Цена диалога</th>
                      </tr>
                    </thead>
                    <tbody>
                      {meta.data.accounts.map((account) => (
                        <tr key={account.account_external_id}>
                          <td><strong>{account.account_name}</strong></td>
                          <td>{currency(account.spend, account.currency)}</td>
                          <td>{account.leads.toLocaleString("ru-RU")}</td>
                          <td>{account.conversations_started.toLocaleString("ru-RU")}</td>
                          <td>
                            {account.cost_per_conversation
                              ? currency(account.cost_per_conversation, account.currency)
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
            <section className="panel">
              <div className="panel-head"><div><h2>Кампании Meta</h2><p>Остановленные кампании скрыты и не участвуют в рекомендациях</p></div><label className="toggle-row"><input type="checkbox" checked={showStopped} onChange={event=>setShowStopped(event.target.checked)}/><span>Показать остановленные</span></label></div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Кампания</th>
                      <th>Статус</th><th>Кабинет</th>
                      <th>Расход</th>
                      <th>Лиды</th>
                      <th>CPL</th>
                      <th>Диалоги</th>
                      <th>Цена диалога</th>
                    </tr>
                  </thead>
                  <tbody>
                    {meta.data.campaigns.filter(campaign=>showStopped||campaign.effective_status==="ACTIVE"||campaign.effective_status==="UNKNOWN").map((campaign) => (
                      <tr
                        key={`${campaign.account_external_id}:${campaign.campaign_external_id}`}
                      >
                        <td>
                          <strong>{campaign.campaign_name}</strong>
                        </td>
                        <td><span className={`campaign-status ${campaign.effective_status.toLowerCase()}`}>{campaign.effective_status==="ACTIVE"?"Активна":campaign.effective_status==="UNKNOWN"?"Статус не получен":"Остановлена"}</span></td><td>{campaign.account_name}</td>
                        <td>{currency(campaign.spend, campaign.currency)}</td>
                        <td>{campaign.leads.toLocaleString("ru-RU")}</td>
                        <td>
                          {campaign.cost_per_lead
                            ? currency(
                                campaign.cost_per_lead,
                                campaign.currency,
                              )
                            : "—"}
                        </td>
                        <td>
                          {campaign.conversations_started.toLocaleString("ru-RU")}
                        </td>
                        <td>
                          {campaign.cost_per_conversation
                            ? currency(
                                campaign.cost_per_conversation,
                                campaign.currency,
                              )
                            : "—"}
                        </td>
                      </tr>
                    ))}
                    {!meta.data.campaigns.length && (
                      <tr>
                        <td colSpan={8} className="empty">
                          За выбранный период рекламы нет.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </DataState>

      <DataState loading={overview.isLoading} error={overview.error}>
        {overview.data && (
          <>
            <section className="metric-grid three">
              <Metric
                label="Прочие рекламные расходы"
                value={money(overview.data.total_spend)}
              />
              <Metric
                label="Связанная выручка"
                value={money(overview.data.total_attributed_revenue)}
              />
              <Metric
                label="ROAS"
                value={
                  overview.data.roas
                    ? `${Number(overview.data.roas).toFixed(2)}×`
                    : "—"
                }
                tone={Number(overview.data.roas || 0) >= 1 ? "good" : "bad"}
              />
            </section>
            <section className="panel">
              <h2>Другие каналы привлечения</h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Источник</th>
                      <th>Затраты</th>
                      <th>Выручка</th>
                      <th>ROAS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {overview.data.sources.map((source) => (
                      <tr key={source.source}>
                        <td>
                          <strong>{source.source}</strong>
                        </td>
                        <td>{money(source.spend)}</td>
                        <td>{money(source.attributed_revenue)}</td>
                        <td>
                          {source.roas
                            ? `${Number(source.roas).toFixed(2)}×`
                            : "—"}
                        </td>
                      </tr>
                    ))}
                    {!overview.data.sources.length && (
                      <tr>
                        <td colSpan={4} className="empty">
                          Нет данных из других каналов за период
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </DataState>
    </>
  );
}
