"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import {
  getLossMap,
  refreshLossMap,
  updateLoss,
  type LossOpportunity,
} from "@/modules/losses";
import {
  DataState,
  DateFilters,
  Metric,
  PageHeader,
  money,
  queryString,
} from "@/shared/ui";

export default function LossesPage() {
  const search = useSearchParams();
  const query = queryString(search);
  const client = useQueryClient();
  const data = useQuery({
    queryKey: ["loss-map", query],
    queryFn: () => getLossMap(query),
  });
  const refresh = useMutation({
    mutationFn: () => refreshLossMap(query),
    onSuccess: (result) => {
      client.setQueryData(["loss-map", query], result);
    },
  });
  const change = useMutation({
    mutationFn: ({
      id,
      status,
      amount,
    }: {
      id: string;
      status: string;
      amount?: number;
    }) =>
      updateLoss(id, {
        status,
        recovered_amount: amount,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["loss-map", query] }),
  });

  return (
    <>
      <PageHeader
        title="Карта потерь"
        subtitle="Финансовые возможности, которые можно проверить, взять в работу и вернуть"
        action={<DateFilters />}
      />
      <DataState loading={data.isLoading} error={data.error}>
        {data.data && (
          <>
            <section className="metric-grid">
              <Metric
                label="Потенциально теряется"
                value={money(data.data.summary.estimated_total)}
                tone={Number(data.data.summary.estimated_total) > 0 ? "bad" : "good"}
                note="Оценка, а не подтверждённая потеря"
              />
              <Metric
                label="Уже возвращено"
                value={money(data.data.summary.recovered_total)}
                tone="good"
                note={`${data.data.summary.recovered_count} закрытых возможностей`}
              />
              <Metric
                label="Открыто"
                value={String(data.data.summary.open_count)}
                note={`${data.data.summary.critical_count} критических`}
              />
              <Metric
                label="В работе"
                value={String(data.data.summary.in_progress_count)}
                note="Назначены действия сотрудникам"
              />
            </section>

            <section className="panel loss-toolbar">
              <div>
                <strong>Детерминированный поиск потерь</strong>
                <p>
                  Revora использует только существующие факты и отдельно
                  показывает уверенность финансовой оценки.
                </p>
              </div>
              <button
                className="primary small"
                disabled={refresh.isPending}
                onClick={() => refresh.mutate()}
              >
                {refresh.isPending
                  ? "Пересчитываем…"
                  : data.data.total
                    ? "Пересчитать карту"
                    : "Построить карту"}
              </button>
            </section>

            {refresh.data && (
              <p className="success-box">
                Проверено возможностей: {refresh.data.detected}. Повторный
                расчёт не создаёт дубли.
              </p>
            )}

            <div className="loss-list">
              {data.data.items.map((item) => (
                <LossCard
                  key={item.id}
                  item={item}
                  pending={change.isPending}
                  onChange={(status, amount) =>
                    change.mutate({ id: item.id, status, amount })
                  }
                />
              ))}
              {!data.data.items.length && (
                <section className="panel quality-empty">
                  <span>₸</span>
                  <div>
                    <strong>Карта ещё не рассчитана</strong>
                    <p>
                      Нажмите «Построить карту». Revora проверит данные
                      выбранного периода и сохранит найденные возможности.
                    </p>
                  </div>
                </section>
              )}
            </div>
          </>
        )}
      </DataState>
    </>
  );
}

function LossCard({
  item,
  pending,
  onChange,
}: {
  item: LossOpportunity;
  pending: boolean;
  onChange: (status: string, amount?: number) => void;
}) {
  const [amount, setAmount] = useState(item.recovered_amount || "");
  const confidence = Math.round(Number(item.confidence) * 100);
  return (
    <article className={`loss-card ${item.severity}`}>
      <div className="loss-card-main">
        <div className="loss-card-head">
          <span className={`health-badge ${item.severity}`}>
            {item.severity === "critical" ? "Высокий приоритет" : "Проверить"}
          </span>
          <span className={`loss-status ${item.status}`}>
            {statusLabel(item.status)}
          </span>
        </div>
        <h2>{item.title}</h2>
        <p>{item.description}</p>
        <div className="loss-action">
          <small>Следующее действие</small>
          <strong>{item.recommended_action}</strong>
        </div>
      </div>
      <div className="loss-card-money">
        <small>Оценка возможности</small>
        <strong>{money(item.estimated_amount)}</strong>
        <span>Уверенность {confidence}%</span>
        {item.status === "recovered" ? (
          <b className="good">Возвращено {money(item.recovered_amount)}</b>
        ) : (
          <div className="loss-controls">
            {item.status === "open" && (
              <button
                disabled={pending}
                onClick={() => onChange("in_progress")}
              >
                Взять в работу
              </button>
            )}
            {item.status === "in_progress" && (
              <>
                <input
                  type="number"
                  min="0"
                  placeholder="Возвращено, ₸"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                />
                <button
                  className="primary"
                  disabled={pending || Number(amount) <= 0}
                  onClick={() => onChange("recovered", Number(amount))}
                >
                  Зафиксировать результат
                </button>
              </>
            )}
            {item.status !== "dismissed" && (
              <button
                className="quiet"
                disabled={pending}
                onClick={() => onChange("dismissed")}
              >
                Не является потерей
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

function statusLabel(status: LossOpportunity["status"]) {
  return {
    open: "Открыто",
    in_progress: "В работе",
    recovered: "Возвращено",
    dismissed: "Исключено",
  }[status];
}
