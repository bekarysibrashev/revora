"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

import {
  createNoShowSnapshot,
  getMLRegistry,
  getMLSnapshots,
  getNoShowReadiness,
} from "@/modules/ml";
import {
  DataState,
  DateFilters,
  Metric,
  PageHeader,
  percent,
  queryString,
} from "@/shared/ui";

export default function DataSciencePage() {
  const search = useSearchParams();
  const query = queryString(search);
  const client = useQueryClient();
  const readiness = useQuery({
    queryKey: ["ml-readiness", query],
    queryFn: () => getNoShowReadiness(query),
  });
  const registry = useQuery({
    queryKey: ["ml-registry"],
    queryFn: getMLRegistry,
  });
  const snapshots = useQuery({
    queryKey: ["ml-snapshots"],
    queryFn: getMLSnapshots,
  });
  const createSnapshot = useMutation({
    mutationFn: () => createNoShowSnapshot(query),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["ml-snapshots"] });
      client.invalidateQueries({ queryKey: ["ml-registry"] });
    },
  });

  return (
    <>
      <PageHeader
        title="Data Science Lab"
        subtitle="Подготовка честной ML-модели неявок: качество выборки, признаки и статистические когорты"
        action={<DateFilters />}
      />
      <DataState loading={readiness.isLoading} error={readiness.error}>
        {readiness.data && (
          <>
            <section className="ds-readiness panel">
              <div>
                <span className={`ds-state ${readiness.data.status}`}>
                  {readinessLabel(readiness.data.status)}
                </span>
                <h2>Готовность датасета</h2>
                <p>{readiness.data.status_reason}</p>
              </div>
              <button
                className="primary small"
                disabled={createSnapshot.isPending || !readiness.data.row_count}
                onClick={() => createSnapshot.mutate()}
              >
                {createSnapshot.isPending
                  ? "Фиксируем…"
                  : "Создать версию датасета"}
              </button>
            </section>

            <section className="metric-grid">
              <Metric
                label="Наблюдений"
                value={readiness.data.row_count.toLocaleString("ru-RU")}
                note={`Цель: ${readiness.data.recommended_train_rows}+`}
              />
              <Metric
                label="Неявок"
                value={readiness.data.positive_count.toLocaleString("ru-RU")}
                note={`Цель: ${readiness.data.recommended_positive_rows}+`}
              />
              <Metric
                label="Доля целевого класса"
                value={percent(readiness.data.positive_rate)}
                note="Показывает дисбаланс классов"
              />
              <Metric
                label="Версий датасета"
                value={String(registry.data?.dataset_snapshots || 0)}
                note={
                  registry.data?.active_model
                    ? "Production-модель активна"
                    : "Модель ещё не обучалась"
                }
              />
            </section>

            <div className="two-col ds-columns">
              <section className="panel">
                <div className="panel-head">
                  <div>
                    <h2>Покрытие признаков</h2>
                    <p>В модель попадут только признаки, известные до приёма</p>
                  </div>
                </div>
                <div className="feature-list">
                  {readiness.data.feature_coverage.map((feature) => (
                    <div key={feature.name}>
                      <div>
                        <strong>{feature.description}</strong>
                        <span
                          className={
                            feature.usable ? "health-badge ready" : "health-badge warning"
                          }
                        >
                          {percent(feature.coverage_rate)}
                        </span>
                      </div>
                      <i>
                        <b
                          style={{
                            width: `${Math.min(
                              100,
                              Number(feature.coverage_rate) * 100,
                            )}%`,
                          }}
                        />
                      </i>
                    </div>
                  ))}
                </div>
              </section>
              <section className="panel ds-learning">
                <h2>Что здесь изучается</h2>
                <ol>
                  <li>
                    <strong>Target:</strong> статус записи `no_show`.
                  </li>
                  <li>
                    <strong>Class balance:</strong> достаточно ли положительных
                    примеров.
                  </li>
                  <li>
                    <strong>Feature coverage:</strong> насколько заполнены
                    признаки.
                  </li>
                  <li>
                    <strong>Data leakage:</strong> запрещены данные, появившиеся
                    после начала приёма.
                  </li>
                  <li>
                    <strong>Temporal split:</strong> будущее нельзя смешивать с
                    обучающей выборкой.
                  </li>
                  <li>
                    <strong>Confidence interval:</strong> диапазон
                    неопределённости каждой когорты.
                  </li>
                </ol>
              </section>
            </div>

            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Исследовательский анализ неявок</h2>
                  <p>
                    Это статистические наблюдения, а не причинные выводы и не
                    прогноз модели
                  </p>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Когорта</th>
                      <th>Записей</th>
                      <th>Неявок</th>
                      <th>Доля</th>
                      <th>Относительно среднего</th>
                      <th>95% интервал</th>
                      <th>Надёжность</th>
                    </tr>
                  </thead>
                  <tbody>
                    {readiness.data.cohorts.map((cohort) => (
                      <tr key={`${cohort.dimension}-${cohort.value}`}>
                        <td>
                          <strong>{cohort.label}</strong>
                        </td>
                        <td>{cohort.appointments}</td>
                        <td>{cohort.no_shows}</td>
                        <td>{percent(cohort.no_show_rate)}</td>
                        <td>
                          {cohort.lift_vs_baseline
                            ? `${Number(cohort.lift_vs_baseline).toFixed(2)}×`
                            : "—"}
                        </td>
                        <td>
                          {percent(cohort.confidence_low)}–{percent(cohort.confidence_high)}
                        </td>
                        <td>
                          <span
                            className={
                              cohort.reliable
                                ? "health-badge ready"
                                : "health-badge warning"
                            }
                          >
                            {cohort.reliable ? "Можно сравнивать" : "Мало данных"}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {!readiness.data.cohorts.length && (
                      <tr>
                        <td colSpan={7} className="empty">
                          В выбранном периоде пока нет подходящих наблюдений
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Реестр воспроизводимых датасетов</h2>
                  <p>
                    Одинаковый источник и период дают тот же ключ, поэтому
                    эксперименты можно повторять
                  </p>
                </div>
              </div>
              <div className="snapshot-list">
                {snapshots.data?.items.map((snapshot) => (
                  <article key={snapshot.id}>
                    <div>
                      <strong>
                        {snapshot.date_from} — {snapshot.date_to}
                      </strong>
                      <small>
                        {snapshot.row_count} строк · {snapshot.positive_count} неявок
                      </small>
                    </div>
                    <code>{snapshot.snapshot_key.slice(0, 12)}</code>
                  </article>
                ))}
                {!snapshots.data?.items.length && (
                  <p className="muted">
                    Создайте первую версию датасета после выбора периода.
                  </p>
                )}
              </div>
            </section>
          </>
        )}
      </DataState>
    </>
  );
}

function readinessLabel(status: string) {
  return {
    empty: "Нет данных",
    insufficient: "Недостаточно для обучения",
    exploratory: "Готово для исследований",
    ready: "Готово для ML",
  }[status];
}
