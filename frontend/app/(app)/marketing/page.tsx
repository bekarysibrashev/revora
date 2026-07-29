"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { api } from "@/shared/api-client";
import {
  AsOf,
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
  configured: boolean;
  requested_account_ids: string[];
  accounts: {
    external_account_id: string;
    name: string;
    account_status: number;
    currency: string;
    timezone_name: string;
    last_synced_at: string | null;
    last_error: string | null;
  }[];
  last_synced_at: string | null;
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

type SyncResult = {
  accounts_synced: number;
  rows_written: number;
  synced_at: string;
};

function currency(value: string | number, code = "USD") {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: code,
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function ratio(value: string | null) {
  return value === null
    ? "—"
    : `${(Number(value) * 100).toLocaleString("ru-RU", {
        maximumFractionDigits: 2,
      })}%`;
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

export default function MarketingPage() {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const query = queryString(search);
  const selectedAccount = search.get("meta_account_id") || "";
  const metaQuery = new URLSearchParams(query);
  if (selectedAccount) metaQuery.set("account_id", selectedAccount);
  const queryClient = useQueryClient();
  const overview = useQuery({
    queryKey: ["marketing", query],
    queryFn: () => api<Overview>(`/marketing/overview?${query}`),
  });
  const metaStatus = useQuery({
    queryKey: ["meta-status"],
    queryFn: () => api<MetaStatus>("/marketing/meta/status"),
  });
  const meta = useQuery({
    queryKey: ["meta-overview", metaQuery.toString()],
    queryFn: () =>
      api<MetaOverview>(`/marketing/meta/overview?${metaQuery.toString()}`),
  });

  function chooseMetaAccount(value: string) {
    const params = new URLSearchParams(search.toString());
    value
      ? params.set("meta_account_id", value)
      : params.delete("meta_account_id");
    router.push(`${pathname}?${params.toString()}`);
  }
  const sync = useMutation({
    mutationFn: () =>
      api<SyncResult>(`/marketing/meta/sync?${query}`, { method: "POST" }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["meta-status"] }),
        queryClient.invalidateQueries({ queryKey: ["meta-overview"] }),
      ]);
    },
  });

  return (
    <>
      <PageHeader
        title="Маркетинг"
        subtitle="Рекламные расходы, WhatsApp-диалоги и возврат вложений"
        action={<DateFilters />}
      />

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Meta Ads</h2>
            <p>
              Два рекламных кабинета · данные хранятся по кампаниям и дням в
              исходной валюте Meta
            </p>
          </div>
          <button
            className="primary small"
            onClick={() => sync.mutate()}
            disabled={!metaStatus.data?.configured || sync.isPending}
          >
            {sync.isPending ? "Синхронизация…" : "Синхронизировать Meta"}
          </button>
        </div>
        {!metaStatus.isLoading && !metaStatus.data?.configured && (
          <div className="error-box">
            Секреты Meta Ads ещё не обнаружены backend-сервисом.
          </div>
        )}
        {sync.isError && (
          <div className="error-box">
            {sync.error instanceof Error
              ? sync.error.message
              : "Не удалось синхронизировать Meta"}
          </div>
        )}
        {sync.data && (
          <div className="success-box">
            Загружено кабинетов: {sync.data.accounts_synced}; дневных строк:{" "}
            {sync.data.rows_written}.
          </div>
        )}
        {!!metaStatus.data?.accounts.length && (
          <div className="status-list">
            {metaStatus.data.accounts.map((account) => (
              <span key={account.external_account_id}>
                {account.name}
                <strong>{account.currency}</strong>
                {account.timezone_name}
              </span>
            ))}
          </div>
        )}
      </section>

      <DataState loading={meta.isLoading} error={meta.error}>
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
                  {metaStatus.data?.accounts.map((account) => (
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
                label="Показы"
                value={meta.data.impressions.toLocaleString("ru-RU")}
              />
              <Metric label="CTR" value={ratio(meta.data.ctr)} />
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
            </section>
            <section className="metric-grid">
              <Metric
                label="CPM · 1 000 показов"
                value={
                  meta.data.cpm
                    ? currency(meta.data.cpm, meta.data.currency || "USD")
                    : "—"
                }
              />
              <Metric
                label="CPC · клик"
                value={
                  meta.data.cpc
                    ? currency(meta.data.cpc, meta.data.currency || "USD")
                    : "—"
                }
              />
              <Metric
                label="CPL · лид"
                value={
                  meta.data.cost_per_lead
                    ? currency(
                        meta.data.cost_per_lead,
                        meta.data.currency || "USD",
                      )
                    : "—"
                }
                note={change(meta.data.comparison.leads_change)}
              />
              <Metric
                label="Клик → диалог"
                value={ratio(meta.data.click_to_conversation_rate)}
              />
            </section>
            <section className="metric-grid">
              <Metric
                label="Уникальные клики"
                value={meta.data.unique_clicks.toLocaleString("ru-RU")}
              />
              <Metric
                label="Переходы по ссылке"
                value={meta.data.link_clicks.toLocaleString("ru-RU")}
              />
              <Metric
                label="Просмотры страницы"
                value={meta.data.landing_page_views.toLocaleString("ru-RU")}
                note={`Дошли после клика: ${ratio(meta.data.landing_page_view_rate)}`}
              />
              <Metric
                label="Лиды Meta"
                value={meta.data.leads.toLocaleString("ru-RU")}
                note={`Покупки: ${meta.data.purchases.toLocaleString("ru-RU")}`}
              />
              <Metric
                label="Запуски видео"
                value={meta.data.video_plays.toLocaleString("ru-RU")}
                note={`ThruPlay: ${meta.data.video_thruplays.toLocaleString("ru-RU")} · ${ratio(meta.data.video_thruplay_rate)}`}
              />
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
                        <th>Показы</th>
                        <th>Клики</th>
                        <th>CTR</th>
                        <th>Диалоги</th>
                        <th>Цена диалога</th>
                      </tr>
                    </thead>
                    <tbody>
                      {meta.data.accounts.map((account) => (
                        <tr key={account.account_external_id}>
                          <td><strong>{account.account_name}</strong></td>
                          <td>{currency(account.spend, account.currency)}</td>
                          <td>{account.impressions.toLocaleString("ru-RU")}</td>
                          <td>{account.clicks.toLocaleString("ru-RU")}</td>
                          <td>{ratio(account.ctr)}</td>
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
              <h2>Кампании Meta</h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Кампания</th>
                      <th>Кабинет</th>
                      <th>Расход</th>
                      <th>Показы</th>
                      <th>Клики</th>
                      <th>CTR</th>
                      <th>CPM</th>
                      <th>CPL</th>
                      <th>Диалоги</th>
                      <th>Цена диалога</th>
                    </tr>
                  </thead>
                  <tbody>
                    {meta.data.campaigns.map((campaign) => (
                      <tr
                        key={`${campaign.account_external_id}:${campaign.campaign_external_id}`}
                      >
                        <td>
                          <strong>{campaign.campaign_name}</strong>
                        </td>
                        <td>{campaign.account_name}</td>
                        <td>{currency(campaign.spend, campaign.currency)}</td>
                        <td>{campaign.impressions.toLocaleString("ru-RU")}</td>
                        <td>{campaign.clicks.toLocaleString("ru-RU")}</td>
                        <td>{ratio(campaign.ctr)}</td>
                        <td>
                          {campaign.cpm
                            ? currency(campaign.cpm, campaign.currency)
                            : "—"}
                        </td>
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
                        <td colSpan={10} className="empty">
                          Нажмите «Синхронизировать Meta», чтобы загрузить данные
                          выбранного периода.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
            <AsOf value={meta.data.data_as_of} />
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
