"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { api, apiBinary } from "@/shared/api-client";
import { DataState, DateFilters, PageHeader, queryString } from "@/shared/ui";

type Source = "" | "kcell" | "whatsapp";
type ContactItem = {
  id: string;
  phone_number: string | null;
  first_contact_at: string;
  source: "kcell" | "whatsapp";
  last_contact_at: string;
  inbound_count: number;
  call_count: number;
  message_count: number;
};
type ContactResponse = {
  summary: {
    total: number;
    from_kcell: number;
    from_whatsapp: number;
    existing_patients_contacted: number;
    data_as_of: string | null;
  };
  items: ContactItem[];
  page: number;
  page_size: number;
  total_pages: number;
};

const sourceLabel = { kcell: "Kcell", whatsapp: "WhatsApp" };

export default function ContactsPage() {
  const search = useSearchParams();
  const [source, setSource] = useState<Source>("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const baseQuery = queryString(search);
  const params = new URLSearchParams(baseQuery);
  params.set("page", String(page));
  params.set("page_size", "50");
  if (source) params.set("source", source);

  const contacts = useQuery({
    queryKey: ["new-contacts", params.toString()],
    queryFn: () => api<ContactResponse>(`/contacts/new?${params.toString()}`),
  });

  async function downloadExcel() {
    setExporting(true);
    setExportError("");
    try {
      const exportParams = new URLSearchParams(baseQuery);
      if (source) exportParams.set("source", source);
      const response = await apiBinary(`/contacts/new/export?${exportParams.toString()}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "revora-new-contacts.xlsx";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "Не удалось выгрузить Excel");
    } finally {
      setExporting(false);
    }
  }

  return <>
    <PageHeader
      title="Новые обращения"
      subtitle="Номера из Kcell и WhatsApp, которых нет среди пациентов 1С"
      action={<DateFilters />}
    />

    <section className="metric-grid contact-metrics">
      <article className="metric"><p>Всего новых</p><strong>{contacts.data?.summary.total ?? "—"}</strong><small>Не найдены в 1С</small></article>
      <article className="metric"><p>Из Kcell</p><strong>{contacts.data?.summary.from_kcell ?? "—"}</strong><small>Первый контакт — звонок</small></article>
      <article className="metric"><p>Из WhatsApp</p><strong>{contacts.data?.summary.from_whatsapp ?? "—"}</strong><small>Первый контакт — сообщение</small></article>
      <article className="metric"><p>Уже были в 1С</p><strong>{contacts.data?.summary.existing_patients_contacted ?? "—"}</strong><small>Не включены в список</small></article>
    </section>

    {exportError && <div className="error-box">{exportError}</div>}
    <section className="panel">
      <div className="contact-list-actions">
        <label>
          Источник
          <select value={source} onChange={(event) => { setSource(event.target.value as Source); setPage(1); }}>
            <option value="">Все источники</option>
            <option value="kcell">Kcell</option>
            <option value="whatsapp">WhatsApp</option>
          </select>
        </label>
        <button className="primary" onClick={downloadExcel} disabled={exporting || contacts.isLoading}>
          {exporting ? "Готовим Excel…" : "Выгрузить в Excel"}
        </button>
      </div>

      <DataState loading={contacts.isLoading} error={contacts.error}>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Номер</th><th>Первое обращение</th><th>Источник</th><th>Последний контакт</th><th>Всего</th><th>Звонки</th><th>WhatsApp</th><th>Сверка с 1С</th></tr></thead>
            <tbody>
              {contacts.data?.items.map((item) => <tr key={item.id}>
                <td><strong>{item.phone_number || "Номер недоступен"}</strong></td>
                <td>{new Date(item.first_contact_at).toLocaleString("ru-RU")}</td>
                <td><span className={`contact-source ${item.source}`}>{sourceLabel[item.source]}</span></td>
                <td>{new Date(item.last_contact_at).toLocaleString("ru-RU")}</td>
                <td>{item.inbound_count}</td>
                <td>{item.call_count}</td>
                <td>{item.message_count}</td>
                <td><span className="contact-new-status">Не найден в 1С</span></td>
              </tr>)}
              {contacts.data && !contacts.data.items.length && <tr><td colSpan={8} className="empty">За выбранный период новых обращений нет</td></tr>}
            </tbody>
          </table>
        </div>
        {contacts.data && contacts.data.total_pages > 1 && <div className="pagination">
          <span>Страница {contacts.data.page} из {contacts.data.total_pages}</span>
          <button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Назад</button>
          <button disabled={page >= contacts.data.total_pages} onClick={() => setPage((value) => value + 1)}>Дальше</button>
        </div>}
      </DataState>
    </section>
  </>;
}
