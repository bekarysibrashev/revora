"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/shared/api-client";
import { DataState, Metric, PageHeader } from "@/shared/ui";

type Criterion = { name: string; weight: number; description: string };
type RuleSet = { id: string; version: number; name: string; success_definition: string; partial_success_definition: string; loss_definition: string; criteria: Criterion[]; loss_reasons: string[] };
type Status = { rule_set: RuleSet | null; calls_received: number; analyses_ready: number; integration_status: string };
type CallItem = { id: string; started_at: string; direction: string; employee: string | null; phone_masked: string | null; duration_seconds: number | null; outcome: string | null; recording_url: string | null; analysis_status: string | null; score: number | null };
type Calls = { items: CallItem[]; total: number };

const defaults = {
  name: "Стандарт обработки звонков",
  success_definition: "Пациент записан на конкретные дату и время.",
  partial_success_definition: "Согласован следующий шаг: обратный звонок, отправка информации или решение пациента в согласованный срок.",
  loss_definition: "Пациент не записан и следующий шаг не согласован.",
  criteria: [
    { name: "Приветствие и контакт", weight: 10, description: "Сотрудник представился и доброжелательно начал разговор." },
    { name: "Выявление потребности", weight: 20, description: "Уточнил проблему, услугу и срочность." },
    { name: "Работа с ценой", weight: 20, description: "Объяснил ценность и ответил на вопрос о стоимости." },
    { name: "Работа с возражениями", weight: 20, description: "Не оставил возражение без ответа." },
    { name: "Предложение записи", weight: 20, description: "Предложил конкретные варианты даты и времени." },
    { name: "Следующий шаг", weight: 10, description: "Зафиксировал результат и завершил разговор." },
  ],
  loss_reasons: ["Не предложили запись", "Не отработали цену", "Не предложили альтернативное время", "Нет согласованного следующего шага"],
};

const directionLabel = (value: string) => value === "in" ? "Входящий" : value === "out" ? "Исходящий" : value;
const outcomeLabel = (value: string | null) => ({ Success: "Состоялся", Missed: "Пропущен", Cancel: "Отменён", Busy: "Занято", NotAvailable: "Недоступен", NotAllowed: "Запрещён", NotFound: "Не найден" }[value || ""] || value || "—");
const analysisLabel = (value: string | null) => ({ pending: "Ожидает анализа", processing: "Анализируется", ready: "Готов", failed: "Ошибка" }[value || ""] || "Правила не заданы");
const durationLabel = (seconds: number | null) => seconds == null ? "—" : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export default function AiPage() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["call-quality-status"], queryFn: () => api<Status>("/call-quality/status") });
  const calls = useQuery({ queryKey: ["call-quality-calls"], queryFn: () => api<Calls>("/call-quality/calls?limit=100") });
  const current = status.data?.rule_set;
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<typeof defaults>(defaults);
  const save = useMutation({ mutationFn: () => api<RuleSet>("/call-quality/rule-sets", { method: "POST", body: JSON.stringify(form) }), onSuccess: () => { client.invalidateQueries({ queryKey: ["call-quality-status"] }); setEditing(false); } });
  const begin = () => { setForm(current || defaults); setEditing(true); };

  return <>
    <PageHeader title="Контроль звонков" subtitle="Журнал Kcell и оценка работы администраторов" action={<button className="primary" onClick={begin}>{current ? "Изменить стандарт" : "Настроить стандарт"}</button>} />
    <DataState loading={status.isLoading} error={status.error}>
      <section className="metric-grid three">
        <Metric label="Звонков получено" value={String(status.data?.calls_received || 0)} />
        <Metric label="ИИ проанализировал" value={String(status.data?.analyses_ready || 0)} />
        <Metric label="Интеграция Kcell" value={status.data?.integration_status === "connected" ? "Подключена" : "Ожидает подключения"} tone={status.data?.integration_status === "connected" ? "good" : undefined} />
      </section>
    </DataState>

    <section className="panel">
      <div className="panel-head"><div><h2>Последние звонки</h2><p>Автоматически получены из виртуальной АТС Kcell</p></div></div>
      <DataState loading={calls.isLoading} error={calls.error}>
        <div className="table-wrap"><table><thead><tr><th>Дата и время</th><th>Тип</th><th>Сотрудник</th><th>Клиент</th><th>Длительность</th><th>Результат</th><th>Запись</th><th>ИИ-анализ</th></tr></thead><tbody>
          {calls.data?.items.map(call => <tr key={call.id}>
            <td>{new Date(call.started_at).toLocaleString("ru-RU")}</td><td>{directionLabel(call.direction)}</td><td>{call.employee || "—"}</td><td>{call.phone_masked || "Скрыт"}</td><td>{durationLabel(call.duration_seconds)}</td><td>{outcomeLabel(call.outcome)}</td>
            <td>{call.recording_url ? <a className="good" href={call.recording_url} target="_blank" rel="noreferrer">Прослушать</a> : "Нет записи"}</td>
            <td>{call.score != null ? `${call.score}/100` : analysisLabel(call.analysis_status)}</td>
          </tr>)}
          {!calls.data?.items.length && <tr><td className="empty" colSpan={8}>Звонки пока не получены</td></tr>}
        </tbody></table></div>
      </DataState>
    </section>

    {current && <section className="panel"><p className="eyebrow">Активна версия {current.version}</p><h2>{current.name}</h2><p><strong>Успешный звонок:</strong> {current.success_definition}</p><div className="table-wrap"><table><thead><tr><th>Критерий</th><th>Вес</th><th>Что проверяет ИИ</th></tr></thead><tbody>{current.criteria.map(item => <tr key={item.name}><td>{item.name}</td><td>{item.weight}%</td><td>{item.description}</td></tr>)}</tbody></table></div></section>}
    {!current && <section className="panel"><h2>Правила оценки ещё не заданы</h2><p>Нажми «Настроить стандарт», чтобы подготовить звонки к будущему ИИ-анализу.</p></section>}

    {editing && <div className="modal-backdrop"><section className="panel modal"><div className="page-header"><div><h2>Стандарт оценки звонков</h2><p>Сохранение создаст новую версию и не изменит старые оценки.</p></div><button className="icon-button" onClick={() => setEditing(false)}>×</button></div>
      <label>Название<input value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label>
      <label>Успешный звонок<textarea value={form.success_definition} onChange={event => setForm({ ...form, success_definition: event.target.value })} /></label>
      <label>Частично успешный звонок<textarea value={form.partial_success_definition} onChange={event => setForm({ ...form, partial_success_definition: event.target.value })} /></label>
      <label>Потерянный звонок<textarea value={form.loss_definition} onChange={event => setForm({ ...form, loss_definition: event.target.value })} /></label>
      <h3>Критерии — сумма весов {form.criteria.reduce((sum, item) => sum + Number(item.weight), 0)}%</h3>
      {form.criteria.map((item, index) => <div className="quality-criterion" key={index}><input value={item.name} onChange={event => { const criteria = [...form.criteria]; criteria[index] = { ...item, name: event.target.value }; setForm({ ...form, criteria }); }} /><input type="number" min="1" max="100" value={item.weight} onChange={event => { const criteria = [...form.criteria]; criteria[index] = { ...item, weight: Number(event.target.value) }; setForm({ ...form, criteria }); }} /><textarea value={item.description} onChange={event => { const criteria = [...form.criteria]; criteria[index] = { ...item, description: event.target.value }; setForm({ ...form, criteria }); }} /></div>)}
      <label>Причины потери — каждая с новой строки<textarea value={form.loss_reasons.join("\n")} onChange={event => setForm({ ...form, loss_reasons: event.target.value.split("\n").map(value => value.trim()).filter(Boolean) })} /></label>
      {save.error && <p className="error-box">{save.error instanceof Error ? save.error.message : "Не удалось сохранить"}</p>}
      <button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Сохраняем…" : "Сохранить новую версию"}</button>
    </section></div>}
  </>;
}
