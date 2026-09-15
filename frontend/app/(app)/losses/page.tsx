"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/shared/api-client";

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
  useFilters,
} from "@/shared/ui";

export default function LossesPage() {
  const { filters } = useFilters();
  const query = queryString(filters);
  const client = useQueryClient();
  const employees = useQuery({
    queryKey: ["telegram-employees"],
    queryFn: () => api<{ items: TelegramEmployee[] }>("/telegram/employees"),
  });
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
      assignedUserId,
    }: {
      id: string;
      status: string;
      amount?: number;
      assignedUserId?: string;
    }) =>
      updateLoss(id, {
        status,
        recovered_amount: amount,
        assigned_user_id: assignedUserId,
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

            <LossFunnel summary={data.data.summary} />

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
                  employees={employees.data?.items.filter((employee) => employee.is_active && employee.linked_user_id) || []}
                  onChange={(status, amount, assignedUserId) =>
                    change.mutate({ id: item.id, status, amount, assignedUserId })
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

function LossFunnel({ summary }: { summary: {stage_counts:Record<string,number>;stage_amounts:Record<string,string>} }) {
  const stages = ["response", "booking", "visit", "payment"];
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Где обрывается путь пациента</h2>
          <p>Все активные случаи, для которых истёк контрольный срок и не найдено следующее действие.</p>
        </div>
      </div>
      <div className="status-list">
        {stages.map((stage) => {
          const count = summary.stage_counts[stage] || 0;
          const amount = Number(summary.stage_amounts[stage] || 0);
          return (
            <span key={stage}>
              {stageLabel(stage)}
              <strong>{count} · {money(amount)}</strong>
            </span>
          );
        })}
      </div>
    </section>
  );
}

function LossCard({
  item,
  pending,
  employees,
  onChange,
}: {
  item: LossOpportunity;
  pending: boolean;
  employees: TelegramEmployee[];
  onChange: (status: string, amount?: number, assignedUserId?: string) => void;
}) {
  const [amount, setAmount] = useState(item.recovered_amount || "");
  const [assignedUserId, setAssignedUserId] = useState(item.assigned_user_id || "");
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
        <div className="loss-proof">
          <span>
            <small>Где оборвалась цепочка</small>
            <strong>{stageLabel(item.evidence.funnel_stage)}</strong>
          </span>
          <span>
            <small>Почему показано</small>
            <strong>{reasonLabel(item.evidence.reason_code)}</strong>
          </span>
          {typeof item.evidence.source === "string" && (
            <span>
              <small>Источник</small>
              <strong>{sourceLabel(item.evidence.source)}</strong>
            </span>
          )}
        </div>
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
              <>
                <select value={assignedUserId} onChange={(event) => setAssignedUserId(event.target.value)}>
                  <option value="">Выберите сотрудника</option>
                  {employees.map((employee) => (
                    <option key={employee.id} value={employee.linked_user_id || ""}>{employee.full_name}</option>
                  ))}
                </select>
                <button
                  disabled={pending || !assignedUserId}
                  onClick={() => onChange("in_progress", undefined, assignedUserId)}
                >
                  Назначить и отправить в Telegram
                </button>
              </>
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

type TelegramEmployee = {
  id: string;
  linked_user_id: string | null;
  full_name: string;
  is_active: boolean;
};

function statusLabel(status: LossOpportunity["status"]) {
  return {
    open: "Открыто",
    in_progress: "В работе",
    recovered: "Возвращено",
    dismissed: "Исключено",
  }[status];
}

function stageLabel(value: unknown) {
  return {
    response: "Ответ на обращение",
    booking: "Обращение → запись",
    visit: "Запись → визит",
    payment: "Лечение → оплата",
  }[String(value)] || "Требует проверки";
}

function reasonLabel(value: unknown) {
  return {
    missed_without_callback: "Не найден обратный звонок за 30 минут",
    whatsapp_unanswered_after_sla: "Нет ответа в WhatsApp более 30 минут",
    no_patient_or_appointment_after_14_days: "За 14 дней не появились пациент и запись",
    cancelled: "Отмена без последующей активной записи",
    no_show: "Неявка без последующей активной записи",
  }[String(value)] || "Есть подтверждённый обрыв воронки";
}

function sourceLabel(value: string) {
  return { kcell: "Kcell", whatsapp: "WhatsApp", meta: "Meta Ads" }[value] || value;
}
