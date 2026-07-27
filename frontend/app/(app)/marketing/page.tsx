"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

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
  conversations_started: number;
  ctr: string | null;
  cpc: string | null;
  cost_per_conversation: string | null;
  campaigns: {
    account_external_id: string;
    account_name: string;
    currency: string;
    campaign_external_id: string;
    campaign_name: string;
    spend: string;
    impressions: number;
    clicks: number;
    conversations_started: number;
    ctr: string | null;
    cpc: string | null;
    cost_per_conversation: string | null;
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

export default function MarketingPage() {
  const search = useSearchParams();
  const query = queryString(search);
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
    queryKey: ["meta-overview", query],
    queryFn: () => api<MetaOverview>(`/marketing/meta/overview?${query}`),
  });
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
            <section className="metric-grid">
              <Metric
                label="Расход Meta"
                value={currency(meta.data.total_spend, meta.data.currency || "USD")}
              />
              <Metric
                label="Показы"
                value={meta.data.impressions.toLocaleString("ru-RU")}
              />
              <Metric label="CTR" value={ratio(meta.data.ctr)} />
              <Metric
                label="WhatsApp-диалоги"
                value={meta.data.conversations_started.toLocaleString("ru-RU")}
                note={`Цена диалога: ${
                  meta.data.cost_per_conversation
                    ? currency(
                        meta.data.cost_per_conversation,
                        meta.data.currency || "USD",
                      )
                    : "—"
                }`}
              />
            </section>
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
