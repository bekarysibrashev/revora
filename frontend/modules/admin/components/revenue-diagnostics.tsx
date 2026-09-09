"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/shared/api-client";

// Разрез выручки по врачам и итог клиники приходят из разных вычислений, и
// на реальных данных расходятся. Расширение 1С v18.3 перестало прятать эту
// разницу и присылает вместе со снимком строку ИТОГО штатного отчёта
// целиком. Панель ниже показывает эти поля и говорит прямо, какая из двух
// возможных причин подтвердилась, — иначе диагностика лежала бы в JSONB и
// её никто бы не увидел.

type Summary = Record<string, unknown>;
type ReportItem = {
  id: string;
  report_type: string;
  report_label: string;
  period_from: string;
  period_to: string;
  summary: Summary;
  imported_at: string;
};

function num(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) {
    return Number(value);
  }
  return null;
}

function money(value: unknown): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return parsed.toLocaleString("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function RevenueReconciliationDiagnostics() {
  const reports = useQuery({
    queryKey: ["official-1c-reports"],
    queryFn: () => api<{ items: ReportItem[] }>("/reports/official-1c"),
  });

  const revenue = (reports.data?.items || []).filter((x) => x.report_type === "service_revenue");
  // Контрольный снимок периода (period_from != period_to) информативнее
  // дневного: именно его итог руководитель сверяет глазами.
  const control = revenue.filter((x) => x.period_from !== x.period_to);
  const report = (control.length ? control : revenue).sort((a, b) =>
    b.imported_at.localeCompare(a.imported_at),
  )[0];

  if (!report) return null;

  const s = report.summary;
  const columns = num(s.total_row_numeric_columns);
  const taken = num(s.total_row_column_taken);
  const numbers = Array.isArray(s.total_row_numbers) ? (s.total_row_numbers as unknown[]) : null;
  const difference = num(s.clinic_total_difference);
  const doctorDiff = num(s.doctor_accrual_reconciliation_diff);
  const version = typeof s.extension_version === "string" ? s.extension_version : null;

  if (columns === null && difference === null) {
    return (
      <section className="panel">
        <h2>Диагностика сверки выручки</h2>
        <p className="muted">
          Последний снимок <code>service_revenue</code> за {report.period_from} — {report.period_to}
          {version ? ` (расширение ${version})` : ""} пришёл без диагностических полей. Они
          появляются начиная с версии расширения 1.8.3.0 — переустановите расширение и повторите
          синхронизацию.
        </p>
      </section>
    );
  }

  // Скрейп берёт «второе число» строки ИТОГО, считая первое количеством, а
  // второе стоимостью. Больше двух числовых колонок означает, что это
  // предположение для данной конфигурации неверно.
  const wrongColumnLikely = columns !== null && columns > 2;
  const totalsAgree = difference !== null && Math.abs(difference) < 0.005;

  return (
    <section className="panel">
      <h2>Диагностика сверки выручки</h2>
      <p className="muted">
        Снимок <code>service_revenue</code> за {report.period_from} — {report.period_to}
        {version ? `, расширение ${version}` : ""}. Загружен{" "}
        {new Date(report.imported_at).toLocaleString("ru-RU")}.
      </p>

      <div className="table-wrap">
        <table>
          <tbody>
            <tr>
              <td>Итог клиники — строка ИТОГО штатного отчёта</td>
              <td>
                <strong>{money(s.clinic_total_report)}</strong>
              </td>
            </tr>
            <tr>
              <td>Сумма строк прямого запроса (по ней считаются разрезы)</td>
              <td>
                <strong>{money(s.clinic_total_query)}</strong>
              </td>
            </tr>
            <tr>
              <td>Разница между ними</td>
              <td>
                <strong className={totalsAgree ? "good" : "bad"}>
                  {money(s.clinic_total_difference)}
                </strong>
              </td>
            </tr>
            <tr>
              <td>Расхождение разреза начислений по врачам с итогом</td>
              <td>
                <strong className={doctorDiff !== null && Math.abs(doctorDiff) < 0.005 ? "good" : "bad"}>
                  {money(s.doctor_accrual_reconciliation_diff)}
                </strong>
              </td>
            </tr>
            <tr>
              <td>Числовых колонок в строке ИТОГО</td>
              <td>
                <strong className={wrongColumnLikely ? "bad" : ""}>{columns ?? "—"}</strong>
              </td>
            </tr>
            <tr>
              <td>Взята колонка №</td>
              <td>
                <strong>{taken ?? "—"}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {numbers && (
        <>
          <p className="muted">Все числа строки ИТОГО по порядку:</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {numbers.map((_, index) => (
                    <th key={index}>№{index + 1}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {numbers.map((value, index) => (
                    <td key={index}>
                      <strong className={index === 1 ? "bad" : ""}>{money(value)}</strong>
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="muted">Выделено число, которое расширение берёт как итог выручки.</p>
        </>
      )}

      {wrongColumnLikely ? (
        <p className="error">
          В строке ИТОГО {columns} числовых колонок, а расширение берёт вторую — исходя из
          предположения, что первое число это количество, а второе стоимость. Для этой
          конфигурации предположение неверно. Посмотрите на числа выше: если стоимость стоит не
          во второй колонке, причина расхождения найдена, и лечится она сменой правила выбора
          колонки, а не разбором документов.
        </p>
      ) : totalsAgree ? (
        <p className="muted">
          Итог штатного отчёта и сумма строк прямого запроса совпадают. Расхождение разреза по
          врачам, если оно осталось, приходит не отсюда.
        </p>
      ) : (
        <p className="error">
          В строке ИТОГО ровно {columns ?? "?"} числовых колонок, и взята та, что и
          предполагалась. Значит скрейп читает верное число, а штатный отчёт и регистр
          «Продажи» расходятся по существу. Дальше нужно смотреть состав документов: возвраты,
          сторно, отменённые документы, отборы самой СКД и строки без сотрудника.
        </p>
      )}
    </section>
  );
}
