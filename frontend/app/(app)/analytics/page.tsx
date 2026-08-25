"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import {
  getDataQuality,
  getMetricCatalog,
  type DatasetHealth,
} from "@/modules/analytics";
import {
  DataState,
  DateFilters,
  Metric,
  PageHeader,
  queryString,
} from "@/shared/ui";

const datasetNames: Record<string, string> = {
  patients: "Пациенты",
  doctors: "Врачи",
  appointments: "Записи",
  leads: "Лиды",
  revenue: "Начисления и оплаты",
  expenses: "Расходы",
  cashflow: "Движение денег",
  balances: "Остатки",
  marketing_spend: "Маркетинговые расходы",
  attribution: "Атрибуция",
};

export default function AnalyticsPage() {
  const search = useSearchParams();
  const query = queryString(search);
  const [tab, setTab] = useState<"quality" | "metrics">("quality");
  const quality = useQuery({
    queryKey: ["analytics-quality", query],
    queryFn: () => getDataQuality(query),
  });
  const metrics = useQuery({
    queryKey: ["analytics-metrics", query],
    queryFn: () => getMetricCatalog(query),
  });

  return (
    <>
      <PageHeader
        title="Контроль данных"
        subtitle="Готовность аналитики, свежесть источников и причины неточных показателей"
        action={<DateFilters />}
      />
      <div className="tabs analytics-tabs">
        <button
          className={tab === "quality" ? "active" : ""}
          onClick={() => setTab("quality")}
        >
          Качество данных
        </button>
        <button
          className={tab === "metrics" ? "active" : ""}
          onClick={() => setTab("metrics")}
        >
          Справочник показателей
        </button>
      </div>

      {tab === "quality" ? (
        <DataState loading={quality.isLoading} error={quality.error}>
          {quality.data && (
            <>
              <section className="metric-grid">
                <Metric
                  label="Оценка качества"
                  value={`${quality.data.summary.score}/100`}
                  tone={
                    quality.data.summary.status === "good" ? "good" : "bad"
                  }
                  note={qualityLabel(quality.data.summary.status)}
                />
                <Metric
                  label="Наборы с данными"
                  value={`${quality.data.summary.ready_datasets}/${quality.data.summary.total_datasets}`}
                  note="Для выбранного периода"
                />
                <Metric
                  label="Критические проблемы"
                  value={String(quality.data.summary.critical_issues)}
                  tone={
                    quality.data.summary.critical_issues ? "bad" : "good"
                  }
                  note="Влияют на расчёт показателей"
                />
                <Metric
                  label="Предупреждения"
                  value={String(quality.data.summary.warning_issues)}
                  note="Требуют проверки"
                />
              </section>

              <section className="panel">
                <div className="panel-head">
                  <div>
                    <h2>Готовность наборов данных</h2>
                    <p>
                      Количество записей и последнее обновление в выбранном
                      периоде
                    </p>
                  </div>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Набор</th>
                        <th>Состояние</th>
                        <th>Записей</th>
                        <th>Область</th>
                        <th>Последнее обновление</th>
                      </tr>
                    </thead>
                    <tbody>
                      {quality.data.datasets.map((dataset) => (
                        <DatasetRow key={dataset.key} dataset={dataset} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="panel">
                <div className="panel-head">
                  <div>
                    <h2>Что требует исправления</h2>
                    <p>
                      Показываем только найденные проблемы, нулевые проверки
                      скрыты
                    </p>
                  </div>
                </div>
                {quality.data.issues.length ? (
                  <div className="quality-issues">
                    {quality.data.issues.map((issue) => (
                      <article
                        key={issue.code}
                        className={`quality-issue ${issue.severity}`}
                      >
                        <div>
                          <span className={`health-badge ${issue.severity}`}>
                            {issue.severity === "critical"
                              ? "Критично"
                              : "Проверить"}
                          </span>
                          <strong>{issue.name}</strong>
                          <p>{issue.description}</p>
                        </div>
                        <b>{issue.affected_records}</b>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="quality-empty">
                    <span>✓</span>
                    <div>
                      <strong>Проблем не обнаружено</strong>
                      <p>
                        Все автоматические проверки выбранного периода
                        пройдены.
                      </p>
                    </div>
                  </div>
                )}
              </section>

              <section className="panel">
                <div className="panel-head">
                  <div>
                    <h2>Источники данных</h2>
                    <p>Подключения и результат их последней синхронизации</p>
                  </div>
                </div>
                {quality.data.connections.length ? (
                  <div className="connection-grid">
                    {quality.data.connections.map((connection) => (
                      <article key={connection.id} className="connection-card">
                        <span>{connection.provider}</span>
                        <strong>{connection.name}</strong>
                        <small>
                          {connection.last_sync_at
                            ? `Синхронизация: ${formatDate(connection.last_sync_at)}`
                            : "Синхронизаций ещё не было"}
                        </small>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="muted">
                    Автоматические источники пока не подключены. Канонические
                    данные в базе уже учитываются выше.
                  </p>
                )}
              </section>
              <p className="as-of">
                Проверка выполнена: {formatDate(quality.data.generated_at)}
              </p>
            </>
          )}
        </DataState>
      ) : (
        <DataState loading={metrics.isLoading} error={metrics.error}>
          {metrics.data && (
            <>
              <section className="metric-grid three">
                <Metric
                  label="Доступно показателей"
                  value={`${metrics.data.available}/${metrics.data.total}`}
                  note="На данных выбранного периода"
                />
                <Metric
                  label="Недоступно"
                  value={String(metrics.data.total - metrics.data.available)}
                  tone={
                    metrics.data.total === metrics.data.available
                      ? "good"
                      : "bad"
                  }
                  note="Не хватает обязательных наборов"
                />
                <Metric
                  label="Принцип расчёта"
                  value="Единый"
                  note="Одна формула во всех разделах Revora"
                />
              </section>
              <div className="metric-catalog">
                {metrics.data.items.map((metric) => (
                  <article className="metric-definition" key={metric.key}>
                    <div className="metric-definition-head">
                      <span>{metric.group}</span>
                      <i
                        className={`health-badge ${
                          metric.available ? "ready" : "empty"
                        }`}
                      >
                        {metric.available ? "Доступен" : "Нет данных"}
                      </i>
                    </div>
                    <h2>{metric.name}</h2>
                    <p>{metric.description}</p>
                    <div className="formula">
                      <small>Формула</small>
                      <strong>{metric.formula}</strong>
                    </div>
                    <div className="dataset-chips">
                      {metric.required_datasets.map((dataset) => (
                        <span
                          key={dataset}
                          className={
                            metric.missing_datasets.includes(dataset)
                              ? "missing"
                              : ""
                          }
                        >
                          {datasetNames[dataset] || dataset}
                        </span>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </DataState>
      )}
    </>
  );
}

function DatasetRow({ dataset }: { dataset: DatasetHealth }) {
  return (
    <tr>
      <td>
        <strong>{dataset.name}</strong>
      </td>
      <td>
        <span className={`health-badge ${dataset.status}`}>
          {datasetStatus(dataset.status)}
        </span>
      </td>
      <td>{dataset.record_count.toLocaleString("ru-RU")}</td>
      <td>
        {dataset.scope === "tenant"
          ? "Вся клиника"
          : dataset.scope === "external"
            ? "Отдельное подключение"
            : "Период"}
      </td>
      <td>{dataset.latest_at ? formatDate(dataset.latest_at) : "—"}</td>
    </tr>
  );
}

function datasetStatus(status: DatasetHealth["status"]) {
  return {
    ready: "Готов",
    stale: "Устарел",
    empty: "Нет данных",
    unknown: "Дата неизвестна",
    not_connected: "Не подключён",
  }[status];
}

function qualityLabel(status: "good" | "warning" | "critical") {
  return {
    good: "Данные пригодны для аналитики",
    warning: "Есть ограничения",
    critical: "Нужны исправления",
  }[status];
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  });
}
