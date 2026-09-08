"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/shared/api-client";
import { DataState } from "@/shared/ui";

// Which employee owns a Kcell extension decides who a lead is credited
// to. Until this screen existed the mapping could only be set through a
// CLI on the server, and the clinic's hosting plan has no shell -- so in
// practice it was never set, and every Kcell lead was created with no
// responsible employee.

type Assignment = {
  external_user: string;
  status: "assigned" | "ambiguous" | "unresolved";
  assigned_user_id: string | null;
  assigned_user_email: string | null;
  assigned_user_name: string | null;
  calls_total: number;
  leads_total: number;
  leads_without_owner: number;
};
type AssignmentList = { items: Assignment[]; total: number; configured: number; unresolved: number };
type User = { id: string; email: string; full_name: string; role: string; is_active: boolean };
type Preview = {
  leads_without_owner: number;
  leads_resolvable: number;
  leads_ambiguous: number;
  extensions_configured: number;
  extensions_unresolved: number;
};
type BackfillResult = { leads_updated: number; leads_ambiguous: number; leads_untouched: number; extensions_applied: number; finished_at: string };
type AuditEntry = {
  external_user: string;
  action: string;
  changed_by_email: string | null;
  details: Record<string, number> | null;
  created_at: string;
};

const STATUS_LABEL: Record<Assignment["status"], string> = {
  assigned: "Назначен",
  ambiguous: "Неоднозначно",
  unresolved: "Не настроено",
};
const ACTION_LABEL: Record<string, string> = {
  set: "назначен сотрудник",
  mark_ambiguous: "отмечено как неоднозначное",
  delete: "сопоставление удалено",
  backfill: "запущен исторический backfill",
};

export function KcellAssignments() {
  const qc = useQueryClient();
  const assignments = useQuery({ queryKey: ["kcell-assignments"], queryFn: () => api<AssignmentList>("/kcell/assignments") });
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api<{ items: User[] }>("/admin/users") });
  const preview = useQuery({ queryKey: ["kcell-backfill-preview"], queryFn: () => api<Preview>("/kcell/assignments/backfill/preview") });
  const audit = useQuery({ queryKey: ["kcell-audit"], queryFn: () => api<{ items: AuditEntry[] }>("/kcell/assignments/audit?limit=25") });

  const [draft, setDraft] = useState<Record<string, string>>({});
  const [result, setResult] = useState<BackfillResult | null>(null);
  const [error, setError] = useState("");

  function refresh() {
    setError("");
    qc.invalidateQueries({ queryKey: ["kcell-assignments"] });
    qc.invalidateQueries({ queryKey: ["kcell-backfill-preview"] });
    qc.invalidateQueries({ queryKey: ["kcell-audit"] });
  }
  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : "Не удалось сохранить сопоставление");
  }

  const assign = useMutation({
    mutationFn: ({ ext, userId }: { ext: string; userId: string }) =>
      api<Assignment>(`/kcell/assignments/${encodeURIComponent(ext)}`, {
        method: "PUT",
        body: JSON.stringify({ assigned_user_id: userId }),
      }),
    onSuccess: refresh,
    onError: fail,
  });
  const markAmbiguous = useMutation({
    mutationFn: (ext: string) => api<Assignment>(`/kcell/assignments/${encodeURIComponent(ext)}/ambiguous`, { method: "POST" }),
    onSuccess: refresh,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (ext: string) => api<void>(`/kcell/assignments/${encodeURIComponent(ext)}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: fail,
  });
  const runBackfill = useMutation({
    mutationFn: () => api<BackfillResult>("/kcell/assignments/backfill", { method: "POST" }),
    onSuccess: (x) => { setResult(x); refresh(); },
    onError: fail,
  });

  const staff = (users.data?.items || []).filter((x) => x.is_active);
  const list = assignments.data;

  return (
    <div className="admin-stack">
      <section className="panel">
        <h2>Сопоставление внутренних номеров Kcell с сотрудниками</h2>
        <p className="muted">
          Пока внутренний номер не сопоставлен, все лиды с его звонков создаются без ответственного —
          и в живом приёме, и в историческом backfill. «Неоднозначно» — это осознанное решение
          (например, общая стойка регистратуры), «Не настроено» — задача, которую ещё нужно закрыть.
        </p>
        {list && (
          <p className="muted">
            Настроено: <strong>{list.configured}</strong> · Требует настройки: <strong>{list.unresolved}</strong>
          </p>
        )}
        {error && <p className="error">{error}</p>}
        <DataState loading={assignments.isLoading} error={assignments.error}>
          <div className="table-wrap"><table>
            <thead>
              <tr>
                <th>Внутренний номер</th>
                <th>Статус</th>
                <th>Ответственный</th>
                <th>Звонков</th>
                <th>Лидов</th>
                <th>Без ответственного</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {(list?.items || []).map((item) => (
                <tr key={item.external_user}>
                  <td><code>{item.external_user}</code></td>
                  <td><span className={`badge ${item.status}`}>{STATUS_LABEL[item.status]}</span></td>
                  <td>{item.assigned_user_name || item.assigned_user_email || "—"}</td>
                  <td>{item.calls_total}</td>
                  <td>{item.leads_total}</td>
                  <td>{item.leads_without_owner}</td>
                  <td>
                    <select
                      value={draft[item.external_user] || item.assigned_user_id || ""}
                      onChange={(e) => setDraft({ ...draft, [item.external_user]: e.target.value })}
                    >
                      <option value="">— выбрать сотрудника —</option>
                      {staff.map((x) => (
                        <option key={x.id} value={x.id}>{x.full_name || x.email}</option>
                      ))}
                    </select>
                    <button
                      disabled={!draft[item.external_user] || assign.isPending}
                      onClick={() => assign.mutate({ ext: item.external_user, userId: draft[item.external_user] })}
                    >
                      Назначить
                    </button>
                    <button disabled={markAmbiguous.isPending} onClick={() => markAmbiguous.mutate(item.external_user)}>
                      Неоднозначно
                    </button>
                    {item.status !== "unresolved" && (
                      <button className="small" disabled={remove.isPending} onClick={() => remove.mutate(item.external_user)}>
                        Удалить
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {list && list.items.length === 0 && (
                <tr><td colSpan={7} className="muted">Kcell ещё не прислал ни одного звонка с внутренним номером.</td></tr>
              )}
            </tbody>
          </table></div>
        </DataState>
      </section>

      <section className="panel">
        <h2>Исторический backfill</h2>
        <p className="muted">
          Проставляет ответственного тем лидам, у которых его сейчас нет. Никогда не перезаписывает уже
          назначенного сотрудника, не трогает выигранные лиды и не угадывает: если звонки лида приходили
          с номеров разных сотрудников, лид остаётся без изменений.
        </p>
        <DataState loading={preview.isLoading} error={preview.error}>
          {preview.data && (
            <ul className="muted">
              <li>Лидов без ответственного: <strong>{preview.data.leads_without_owner}</strong></li>
              <li>Из них будут заполнены: <strong>{preview.data.leads_resolvable}</strong></li>
              <li>Неоднозначных (останутся без изменений): <strong>{preview.data.leads_ambiguous}</strong></li>
              <li>Номеров без настройки: <strong>{preview.data.extensions_unresolved}</strong></li>
            </ul>
          )}
        </DataState>
        <button
          className="primary small"
          disabled={runBackfill.isPending || !preview.data?.leads_resolvable}
          onClick={() => runBackfill.mutate()}
        >
          {runBackfill.isPending ? "Выполняется…" : "Запустить backfill"}
        </button>
        {result && (
          <p className="muted">
            Обновлено лидов: <strong>{result.leads_updated}</strong> · Неоднозначных пропущено:{" "}
            <strong>{result.leads_ambiguous}</strong> · Осталось без ответственного:{" "}
            <strong>{result.leads_untouched}</strong> · Завершено:{" "}
            {new Date(result.finished_at).toLocaleString("ru-RU")}
          </p>
        )}
      </section>

      <section className="panel">
        <h2>История изменений</h2>
        <p className="muted">Кто и когда менял сопоставление. Номера телефонов здесь не хранятся.</p>
        <DataState loading={audit.isLoading} error={audit.error}>
          <div className="table-wrap"><table>
            <thead>
              <tr><th>Когда</th><th>Кто</th><th>Внутренний номер</th><th>Действие</th><th>Детали</th></tr>
            </thead>
            <tbody>
              {(audit.data?.items || []).map((item, index) => (
                <tr key={`${item.created_at}-${index}`}>
                  <td>{new Date(item.created_at).toLocaleString("ru-RU")}</td>
                  <td>{item.changed_by_email || "—"}</td>
                  <td><code>{item.external_user}</code></td>
                  <td>{ACTION_LABEL[item.action] || item.action}</td>
                  <td className="muted">
                    {item.details
                      ? Object.entries(item.details).map(([key, value]) => `${key}: ${value}`).join(", ")
                      : "—"}
                  </td>
                </tr>
              ))}
              {audit.data && audit.data.items.length === 0 && (
                <tr><td colSpan={5} className="muted">Изменений пока не было.</td></tr>
              )}
            </tbody>
          </table></div>
        </DataState>
      </section>
    </div>
  );
}
