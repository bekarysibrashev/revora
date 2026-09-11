"use client";

import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/modules/auth";
import { api, apiBinary } from "@/shared/api-client";
import { DataState, Metric, PageHeader } from "@/shared/ui";

type Status = {
  configured: boolean; test_mode: boolean; ai_provider: string; auto_send: boolean;
  embedded_signup_ready: boolean; meta_app_id: string | null;
  embedded_signup_config_id: string | null; connection_missing: string[];
  monthly_budget_kzt: number; estimated_spend_kzt: string; channels: number;
  open_conversations: number; waiting_for_human: number;
  knowledge_total: number; knowledge_approved: number;
};
type Conversation = {
  id: string; channel_name: string; contact_masked: string; contact_full: string; state: string;
  language: string; handoff_reason: string | null; last_message_at: string;
  unread_count: number; assigned_user_id: string | null;
};
type Message = {
  id: string; direction: string; sender_kind: string; body: string | null;
  status: string; is_draft: boolean; created_at: string; message_type: string;
  media_available: boolean; media_filename: string | null; media_mime_type: string | null;
  transcript: string | null; transcription_status: string | null; transcription_error: string | null;
  delivery_attempts: number; last_delivery_error: string | null;
};
type Detail = { conversation: Conversation; messages: Message[] };
type Knowledge = {
  id: string; category: string; title: string; content_ru: string | null;
  content_kk: string | null; risk_level: string; source: string;
  is_approved: boolean; created_at: string;
};
type Simulation = {
  conversation_id: string; state: string; reply: string | null; handoff: boolean;
  handoff_reason: string | null; provider: string; cost_kzt: string;
};
type QrStatus = {
  configured: boolean; state: string; connected: boolean;
  qr_data_url: string | null; phone: string | null; message: string | null;
  last_heartbeat_at: string | null; last_message_at: string | null; last_history_sync_at: string | null;
  messages_forwarded: number; history_messages_forwarded: number; reconnect_count: number;
  last_error: string | null; stale: boolean;
};
type Analytics = {
  date_from:string; date_to:string; conversations:number; messages_total:number;
  incoming_messages:number; outgoing_messages:number; bot_messages:number; human_messages:number;
  history_messages:number; media_messages:number; voice_messages:number; transcribed_voice_messages:number;
  waiting_for_human:number; unanswered_conversations:number; average_first_response_seconds:number|null;
  new_contacts:number; existing_patient_contacts:number;
};
type GatewayLog = { id:string; level:string; event:string; message:string; occurred_at:string };
type KnowledgeDraft = {
  id?: string; category: string; title: string; content_ru: string;
  content_kk: string; risk_level: "safe" | "review" | "human_only";
};
type KnowledgeSheet = {
  connected: boolean; service_account_email: string | null; sheet_url: string | null;
  sheet_names: string[]; is_enabled: boolean; last_synced_at: string | null; last_sync_status: string | null;
  last_sync_error: string | null; last_sync_imported: number; last_sync_updated: number;
  last_sync_auto_approved: number; last_sync_review_required: number; last_sync_human_only: number;
};
const emptyKnowledge: KnowledgeDraft = {
  category: "FAQ", title: "", content_ru: "", content_kk: "", risk_level: "review",
};

const stateLabels: Record<string, string> = {
  bot_active: "ИИ активен",
  human_requested: "Нужен администратор",
  human_active: "Администратор",
  closed: "Закрыт",
};

export default function WhatsAppPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"dialogs" | "test" | "knowledge" | "analytics" | "system">("test");
  const today = new Date().toISOString().slice(0, 10);
  const initialFrom = new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10);
  const [analyticsFrom, setAnalyticsFrom] = useState(initialFrom);
  const [analyticsTo, setAnalyticsTo] = useState(today);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const [selected, setSelected] = useState("");
  const [testMessage, setTestMessage] = useState("");
  const [lastTestMessage, setLastTestMessage] = useState("");
  const [testContact, setTestContact] = useState(() => `simulator-${Date.now()}`);
  const [humanMessage, setHumanMessage] = useState("");
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [importResult, setImportResult] = useState("");
  const [sheetUrlInput, setSheetUrlInput] = useState("");
  const [sheetNamesInput, setSheetNamesInput] = useState("");
  const [connectMessage, setConnectMessage] = useState("");
  const [knowledgeDraft, setKnowledgeDraft] = useState<KnowledgeDraft>(emptyKnowledge);
  const [knowledgeEditorOpen, setKnowledgeEditorOpen] = useState(false);
  const status = useQuery({ queryKey: ["wa-status"], queryFn: () => api<Status>("/whatsapp/status") });
  const qrStatus = useQuery({
    queryKey: ["wa-qr-status"],
    queryFn: () => api<QrStatus>("/whatsapp/qr/status"),
    enabled: user?.role === "owner",
    refetchInterval: 3000,
  });
  const conversations = useQuery({
    queryKey: ["wa-conversations"],
    queryFn: () => api<{ items: Conversation[] }>("/whatsapp/conversations"),
    refetchInterval: tab === "dialogs" ? 5000 : false,
  });
  const detail = useQuery({
    queryKey: ["wa-conversation", selected],
    queryFn: () => api<Detail>(`/whatsapp/conversations/${selected}`),
    enabled: Boolean(selected),
    refetchInterval: selected ? 3000 : false,
  });
  const knowledge = useQuery({
    queryKey: ["wa-knowledge"],
    queryFn: () => api<{ items: Knowledge[] }>("/whatsapp/knowledge"),
  });
  const knowledgeSheet = useQuery({
    queryKey: ["wa-knowledge-sheet"],
    queryFn: () => api<KnowledgeSheet>("/whatsapp/knowledge/google-sheet"),
    enabled: user?.role === "owner",
  });
  const analytics = useQuery({
    queryKey: ["wa-analytics", analyticsFrom, analyticsTo],
    queryFn: () => api<Analytics>(`/whatsapp/analytics?date_from=${analyticsFrom}&date_to=${analyticsTo}`),
    enabled: tab === "analytics",
  });
  const gatewayLogs = useQuery({
    queryKey: ["wa-gateway-logs"],
    queryFn: () => api<{items:GatewayLog[]}>("/whatsapp/gateway/logs?limit=100"),
    enabled: tab === "system" && user?.role === "owner",
    refetchInterval: tab === "system" ? 15000 : false,
  });
  useEffect(() => {
    if (knowledgeSheet.data?.connected) setSheetNamesInput(knowledgeSheet.data.sheet_names.join(", "));
  }, [knowledgeSheet.data?.connected, knowledgeSheet.data?.sheet_names.join(",")]);
  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["wa-status"] }),
      qc.invalidateQueries({ queryKey: ["wa-conversations"] }),
      qc.invalidateQueries({ queryKey: ["wa-conversation", selected] }),
    ]);
  };
  const simulate = useMutation({
    mutationFn: (message: string) => api<Simulation>("/whatsapp/simulator/messages", {
      method: "POST",
      body: JSON.stringify({ message, contact_id: testContact }),
    }),
    onSuccess: async (result, message) => {
      setSimulation(result);
      setLastTestMessage(message);
      setTestMessage("");
      await refresh();
    },
  });
  const transition = useMutation({
    mutationFn: (action: "takeover" | "release") =>
      api<Detail>(`/whatsapp/conversations/${selected}/${action}`, { method: "POST" }),
    onSuccess: refresh,
  });
  const sendHuman = useMutation({
    mutationFn: (message: string) =>
      api<Message>(`/whatsapp/conversations/${selected}/messages`, {
        method: "POST", body: JSON.stringify({ message }),
      }),
    onSuccess: async () => { setHumanMessage(""); await refresh(); },
  });
  const approval = useMutation({
    mutationFn: ({ item, approved }: { item: Knowledge; approved: boolean }) =>
      api<Knowledge>(`/whatsapp/knowledge/${item.id}`, {
        method: "PATCH", body: JSON.stringify({ approved }),
      }),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["wa-knowledge"] }),
        qc.invalidateQueries({ queryKey: ["wa-status"] }),
      ]);
    },
  });
  const saveKnowledge = useMutation({
    mutationFn: (draft: KnowledgeDraft) => api<Knowledge>(
      draft.id ? `/whatsapp/knowledge/${draft.id}` : "/whatsapp/knowledge",
      {
        method: draft.id ? "PATCH" : "POST",
        body: JSON.stringify({
          category: draft.category,
          title: draft.title,
          content_ru: draft.content_ru || null,
          content_kk: draft.content_kk || null,
          risk_level: draft.risk_level,
        }),
      },
    ),
    onSuccess: async () => {
      setKnowledgeDraft(emptyKnowledge);
      setKnowledgeEditorOpen(false);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["wa-knowledge"] }),
        qc.invalidateQueries({ queryKey: ["wa-status"] }),
      ]);
    },
  });
  const connectQr = useMutation({
    mutationFn: () => api<QrStatus>("/whatsapp/qr/connect", { method: "POST" }),
    onMutate: () => {
      setConnectMessage("Запускаем QR-шлюз. Бесплатный Render может просыпаться до минуты…");
    },
    onSuccess: async (result) => {
      setConnectMessage(result.message || "QR-шлюз запущен");
      await qc.invalidateQueries({ queryKey: ["wa-qr-status"] });
    },
    onError: (error) => {
      setConnectMessage(error instanceof Error ? error.message : "QR-шлюз недоступен");
    },
  });
  const botMode = useMutation({
    mutationFn: (autoSend:boolean) => api<Status>("/whatsapp/bot-mode", {
      method:"PATCH", body:JSON.stringify({auto_send:autoSend}),
    }),
    onSuccess: result => qc.setQueryData(["wa-status"], result),
  });
  const retryMessage = useMutation({
    mutationFn: (messageId:string) => api<{status:string}>(`/whatsapp/messages/${messageId}/retry`, {method:"POST"}),
    onSuccess: refresh,
  });

  const connectSheet = useMutation({
    mutationFn: (vars: { sheetUrl: string; sheetNames: string[] }) => api<KnowledgeSheet>("/whatsapp/knowledge/google-sheet", {
      method: "PUT", body: JSON.stringify({ sheet_url: vars.sheetUrl, sheet_names: vars.sheetNames }),
    }),
    onSuccess: async (result) => {
      setSheetUrlInput("");
      qc.setQueryData(["wa-knowledge-sheet"], result);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["wa-knowledge"] }),
        qc.invalidateQueries({ queryKey: ["wa-status"] }),
      ]);
    },
  });
  const syncSheet = useMutation({
    mutationFn: () => api<KnowledgeSheet>("/whatsapp/knowledge/google-sheet/sync", { method: "POST" }),
    onSuccess: async (result) => {
      qc.setQueryData(["wa-knowledge-sheet"], result);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["wa-knowledge"] }),
        qc.invalidateQueries({ queryKey: ["wa-status"] }),
      ]);
    },
  });

  async function uploadKnowledge(file: File) {
    setImportResult("");
    try {
      const result = await api<{ imported: number; auto_approved: number; review_required: number; human_only: number }>(
        "/whatsapp/knowledge/import",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "X-Filename": encodeURIComponent(file.name),
          },
          body: file,
        },
      );
      setImportResult(`Импортировано: ${result.imported}. Одобрено автоматически: ${result.auto_approved}. Требует ручной проверки: ${result.human_only}.`);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["wa-knowledge"] }),
        qc.invalidateQueries({ queryKey: ["wa-status"] }),
      ]);
    } catch (error) {
      setImportResult(error instanceof Error ? error.message : "Не удалось импортировать файл");
    }
  }

  async function downloadExport() {
    setExporting(true); setExportError("");
    try {
      const response = await apiBinary(`/whatsapp/export?date_from=${analyticsFrom}&date_to=${analyticsTo}`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = `revora-whatsapp-${analyticsFrom}-${analyticsTo}.xlsx`; link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "Не удалось выгрузить переписки");
    } finally { setExporting(false); }
  }

  async function downloadMedia(message: Message) {
    try {
      const response = await apiBinary(`/whatsapp/messages/${message.id}/media`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = message.media_filename || `whatsapp-${message.id}`; link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "Не удалось скачать вложение");
    }
  }

  return (
    <>
      <PageHeader title="WhatsApp AI" subtitle="Безопасный бот, очередь администраторов и база знаний клиники" />
      <DataState loading={status.isLoading} error={status.error}>
        {status.data && <>
          <section className="metric-grid">
            <Metric label="Режим" value={status.data.test_mode ? "Тестовый" : "WhatsApp"} note={status.data.auto_send ? "Автоответы включены" : "Только черновики"} />
            <Metric label="Диалоги" value={`${status.data.open_conversations}`} note={`Ждут человека: ${status.data.waiting_for_human}`} />
            <Metric label="База знаний" value={`${status.data.knowledge_approved}/${status.data.knowledge_total}`} note="Одобрено владельцем" />
            <Metric label="Бюджет ИИ" value={`${Number(status.data.estimated_spend_kzt).toLocaleString("ru-RU")} ₸`} note={`Лимит: ${status.data.monthly_budget_kzt.toLocaleString("ru-RU")} ₸`} />
          </section>
          <section className="panel">
            {user?.role === "owner" && <div className="wa-connect">
              <div>
                <strong>Подключение WhatsApp Business через QR</strong>
                <p>На основном телефоне откройте WhatsApp Business → Связанные устройства → Привязка устройства.</p>
                <small>{connectMessage || qrStatus.data?.message || "Нажмите кнопку, чтобы получить QR-код."}</small>
                {qrStatus.data?.connected && <small>Подключён номер: {qrStatus.data.phone?.startsWith("+") || qrStatus.data.phone?.startsWith("*") ? qrStatus.data.phone : `+${qrStatus.data.phone}`}</small>}
                {qrStatus.data?.last_heartbeat_at && <small>Последняя связь с Baileys: {new Date(qrStatus.data.last_heartbeat_at).toLocaleString("ru-RU")}</small>}
                {qrStatus.data?.last_error && <small className="bad">Последняя ошибка: {qrStatus.data.last_error}</small>}
              </div>
              <div className="inline-actions">
                {qrStatus.data?.qr_data_url && <img
                  src={qrStatus.data.qr_data_url}
                  alt="QR-код для подключения WhatsApp Business"
                  width={260}
                  height={260}
                  style={{ background: "white", borderRadius: 12 }}
                />}
                {!qrStatus.data?.connected && <button
                  className="primary"
                  disabled={connectQr.isPending || qrStatus.data?.configured === false}
                  onClick={() => connectQr.mutate()}
                >
                  {connectQr.isPending ? <><span className="spinner" aria-hidden="true"/>Запускаем…</> : qrStatus.data?.qr_data_url ? "Обновить QR" : "Получить QR-код"}
                </button>}
                {qrStatus.data?.connected && <button
                  className={status.data.auto_send ? "danger" : "primary"}
                  disabled={botMode.isPending}
                  onClick={() => botMode.mutate(!status.data.auto_send)}
                >{botMode.isPending?"Сохраняем…":status.data.auto_send?"Остановить автоответы":"Включить автоответы"}</button>}
              </div>
            </div>}
            <div className="tabs">
              <button className={tab === "test" ? "active" : ""} onClick={() => setTab("test")}>Симулятор</button>
              <button className={tab === "dialogs" ? "active" : ""} onClick={() => setTab("dialogs")}>Диалоги</button>
              <button className={tab === "analytics" ? "active" : ""} onClick={() => setTab("analytics")}>Аналитика</button>
              <button className={tab === "knowledge" ? "active" : ""} onClick={() => setTab("knowledge")}>База знаний</button>
              {user?.role === "owner" && <button className={tab === "system" ? "active" : ""} onClick={() => setTab("system")}>Состояние</button>}
            </div>
            {tab === "test" && <div className="wa-test">
              <div className="info-panel"><span>i</span><div>
                <strong>Тест ничего не отправляет в WhatsApp и стоит 0 ₸</strong>
                <p>Пишите от имени пациента. Бот использует только одобренные материалы.</p>
              </div></div>
              <div className="wa-phone">
                <div className="wa-phone-head">Тестовый пациент</div>
                {simulation?.reply && <>
                  <div className="wa-bubble patient">{lastTestMessage}</div>
                  <div className="wa-bubble bot">{simulation.reply}</div>
                  <small>{simulation.provider} · {simulation.cost_kzt} ₸{simulation.handoff ? ` · Передано: ${simulation.handoff_reason}` : ""}</small>
                </>}
                {simulation?.handoff && <button type="button" onClick={() => {
                  setTestContact(`simulator-${Date.now()}`);
                  setSimulation(null);
                  setLastTestMessage("");
                }}>Начать новый тест</button>}
                <form className="wa-composer" onSubmit={(event: FormEvent) => {
                  event.preventDefault(); if (testMessage.trim()) simulate.mutate(testMessage.trim());
                }}>
                  <textarea value={testMessage} onChange={(event) => setTestMessage(event.target.value)} placeholder="Например: Сколько стоит лечение одного зуба?" rows={3} />
                  <button className="primary" disabled={simulate.isPending}>{simulate.isPending ? <><span className="spinner" aria-hidden="true"/>Проверяем…</> : "Отправить"}</button>
                </form>
                {simulate.isError && <div className="error-box">{simulate.error.message}</div>}
              </div>
            </div>}
            {tab === "dialogs" && <div className="wa-layout">
              <aside className="wa-dialog-list">
                {conversations.data?.items.map((item) => <button key={item.id} className={selected === item.id ? "active" : ""} onClick={() => setSelected(item.id)}>
                  <strong>{item.contact_full}</strong>
                  <small>{item.channel_name} · {stateLabels[item.state] || item.state}</small>
                </button>)}
                {!conversations.data?.items.length && <p>Диалогов пока нет.</p>}
              </aside>
              <div className="wa-chat">
                {!selected && <div className="center-state">Выберите диалог</div>}
                {detail.data && <>
                  <header><div><strong>{detail.data.conversation.contact_full}</strong><small>{stateLabels[detail.data.conversation.state] || detail.data.conversation.state}</small></div>
                    {detail.data.conversation.state === "human_active"
                      ? <button onClick={() => transition.mutate("release")}>Вернуть ИИ</button>
                      : <button onClick={() => transition.mutate("takeover")}>Забрать диалог</button>}
                  </header>
                  <div className="wa-messages">{detail.data.messages.map((message) =>
                    <div key={message.id} className={`wa-bubble ${message.direction === "in" ? "patient" : "bot"}`}>
                      {message.body}
                      {message.transcript && <small>Расшифровка: {message.transcript}</small>}
                      {message.transcription_status === "processing" || message.transcription_status === "queued" || message.transcription_status === "retrying" ? <small>Расшифровываем голосовое…</small> : null}
                      {message.media_available && <button type="button" className="small" onClick={() => void downloadMedia(message)}>Скачать {message.media_filename || "вложение"}</button>}
                      {message.is_draft && <small>Черновик — не отправлен</small>}
                      {message.status === "queued" || message.status === "retrying" || message.status === "sending" ? <small>Отправляется… попытка {message.delivery_attempts}</small> : null}
                      {message.status === "failed" && <small>Не отправлено: {message.last_delivery_error}</small>}
                      {(message.status === "failed" || message.is_draft) && <button type="button" className="small" disabled={retryMessage.isPending} onClick={()=>retryMessage.mutate(message.id)}>Отправить сейчас</button>}
                    </div>)}</div>
                  <form className="wa-composer" onSubmit={(event) => {
                    event.preventDefault(); if (humanMessage.trim()) sendHuman.mutate(humanMessage.trim());
                  }}>
                    <textarea value={humanMessage} onChange={(event) => setHumanMessage(event.target.value)} rows={2} placeholder="Ответ администратора" />
                    <button className="primary">Отправить</button>
                  </form>
                </>}
              </div>
            </div>}
            {tab === "analytics" && <div>
              <div className="panel-head"><div><h2>Аналитика WhatsApp</h2><p>Отчёт строится прямо по сохранённым сообщениям — предварительная выгрузка не нужна.</p></div>
                <div className="inline-actions"><input type="date" value={analyticsFrom} onChange={e=>setAnalyticsFrom(e.target.value)}/><input type="date" value={analyticsTo} onChange={e=>setAnalyticsTo(e.target.value)}/><button className="primary" disabled={exporting} onClick={()=>void downloadExport()}>{exporting?"Готовим Excel…":"Выгрузить Excel"}</button></div>
              </div>
              {exportError&&<div className="error-box">{exportError}</div>}
              <DataState loading={analytics.isLoading} error={analytics.error}>{analytics.data&&<>
                <section className="metric-grid">
                  <Metric label="Диалоги" value={String(analytics.data.conversations)} note={`${analytics.data.messages_total} сообщений`}/>
                  <Metric label="Входящие" value={String(analytics.data.incoming_messages)} note={`${analytics.data.unanswered_conversations} без ответа`}/>
                  <Metric label="Ответы" value={String(analytics.data.outgoing_messages)} note={`ИИ: ${analytics.data.bot_messages} · сотрудники: ${analytics.data.human_messages}`}/>
                  <Metric label="Первый ответ" value={analytics.data.average_first_response_seconds===null?"—":`${Math.round(analytics.data.average_first_response_seconds)} сек.`} note={`Ждут администратора: ${analytics.data.waiting_for_human}`}/>
                </section>
                <section className="metric-grid three">
                  <Metric label="Новые обращения" value={String(analytics.data.new_contacts)} note="Номера, которых нет среди пациентов 1С"/>
                  <Metric label="Пациенты 1С" value={String(analytics.data.existing_patient_contacts)} note="Уже известные клинике номера"/>
                  <Metric label="История" value={String(analytics.data.history_messages)} note="Получено при синхронизации"/>
                  <Metric label="Вложения" value={String(analytics.data.media_messages)} note={`Голосовых: ${analytics.data.voice_messages}`}/>
                  <Metric label="Расшифровано" value={String(analytics.data.transcribed_voice_messages)} note="Голосовые для анализа"/>
                </section>
              </>}</DataState>
            </div>}
            {tab === "system" && user?.role === "owner" && <div>
              <div className="panel-head"><div><h2>Состояние WhatsApp</h2><p>Baileys работает как внутренняя часть Revora. На компьютер клиники ничего устанавливать не нужно.</p></div></div>
              <section className="metric-grid">
                <Metric label="Соединение" value={qrStatus.data?.connected?"Онлайн":qrStatus.data?.stale?"Нет связи":"Не подключено"} note={qrStatus.data?.state||"—"}/>
                <Metric label="Последний heartbeat" value={qrStatus.data?.last_heartbeat_at?new Date(qrStatus.data.last_heartbeat_at).toLocaleTimeString("ru-RU"):"—"} note={qrStatus.data?.last_heartbeat_at?new Date(qrStatus.data.last_heartbeat_at).toLocaleDateString("ru-RU"):"Данных ещё нет"}/>
                <Metric label="Передано сообщений" value={String(qrStatus.data?.messages_forwarded||0)} note={`Из истории: ${qrStatus.data?.history_messages_forwarded||0}`}/>
                <Metric label="Переподключения" value={String(qrStatus.data?.reconnect_count||0)} note={qrStatus.data?.last_message_at?`Последнее сообщение: ${new Date(qrStatus.data.last_message_at).toLocaleString("ru-RU")}`:"Сообщений ещё нет"}/>
              </section>
              {qrStatus.data?.last_error&&<div className="error-box">{qrStatus.data.last_error}</div>}
              <div className="table-wrap"><table><thead><tr><th>Время</th><th>Уровень</th><th>Событие</th><th>Описание</th></tr></thead><tbody>
                {gatewayLogs.data?.items.map(item=><tr key={item.id}><td>{new Date(item.occurred_at).toLocaleString("ru-RU")}</td><td>{item.level}</td><td>{item.event}</td><td>{item.message}</td></tr>)}
                {!gatewayLogs.data?.items.length&&<tr><td colSpan={4} className="empty">Журнал пока пуст</td></tr>}
              </tbody></table></div>
            </div>}
            {tab === "knowledge" && <div>
              {user?.role === "owner" ? <>
                <div className="wa-knowledge-actions">
                  <button className="primary" onClick={() => { setKnowledgeDraft(emptyKnowledge); setKnowledgeEditorOpen(true); }}>Добавить ответ</button>
                  <label className="file-drop"><strong>Загрузить Excel со скриптами</strong><span>Строки одобряются автоматически и сразу используются ботом — редактируйте сам файл перед загрузкой. Рекламные/только для администратора строки всегда остаются на ручной проверке.</span>
                    <input type="file" accept=".xlsx" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadKnowledge(file); }} />
                  </label>
                </div>
                <div className="panel wa-sheet-connect">
                  <div className="panel-head"><div>
                    <h2>Google Таблица со скриптами</h2>
                    <p>Подключается только на чтение — Revora никогда не изменяет вашу таблицу. Обновляется сама каждые ~20 минут, плюс можно синхронизировать вручную в любой момент.</p>
                  </div></div>
                  {knowledgeSheet.data?.service_account_email && <div className="info-panel"><span>i</span><div>
                    <strong>Перед подключением откройте доступ к таблице</strong>
                    <p>В таблице: Файл → Поделиться → добавьте <code>{knowledgeSheet.data.service_account_email}</code> с ролью «Читатель» — и только после этого вставляйте ссылку ниже.</p>
                  </div></div>}
                  <form onSubmit={(event) => {
                    event.preventDefault();
                    if (!sheetUrlInput.trim()) return;
                    connectSheet.mutate({
                      sheetUrl: sheetUrlInput.trim(),
                      sheetNames: sheetNamesInput.split(",").map((name) => name.trim()).filter(Boolean),
                    });
                  }}>
                    <div className="inline-actions">
                      <input style={{ flex: 1 }} placeholder="Ссылка на таблицу Google Sheets" value={sheetUrlInput} onChange={(event) => setSheetUrlInput(event.target.value)} />
                    </div>
                    <label>Какие вкладки использовать (через запятую)
                      <input placeholder="например: Имплантация, Ортопедия, FAQ_Другое — пусто = все вкладки, кроме рекламных" value={sheetNamesInput} onChange={(event) => setSheetNamesInput(event.target.value)} />
                    </label>
                    <div className="inline-actions">
                      <button className="primary" disabled={connectSheet.isPending || !sheetUrlInput.trim()}>{connectSheet.isPending ? <><span className="spinner" aria-hidden="true"/>Подключаем…</> : knowledgeSheet.data?.connected ? "Сохранить" : "Подключить"}</button>
                    </div>
                  </form>
                  {connectSheet.isError && <div className="error-box">{connectSheet.error.message}</div>}
                  {knowledgeSheet.data?.connected && <>
                    <small>Подключена: {knowledgeSheet.data.sheet_url}</small>
                    <small>Вкладки: {knowledgeSheet.data.sheet_names.length ? knowledgeSheet.data.sheet_names.join(", ") : "все, кроме рекламных/служебных"}</small>
                    <small>
                      {knowledgeSheet.data.last_synced_at
                        ? `Последняя синхронизация: ${new Date(knowledgeSheet.data.last_synced_at).toLocaleString("ru-RU")} — ${knowledgeSheet.data.last_sync_status === "success" ? "успешно" : "ошибка"}`
                        : "Ещё не синхронизировалась"}
                    </small>
                    {knowledgeSheet.data.last_sync_status === "success" && <small>Новых строк: {knowledgeSheet.data.last_sync_imported}, обновлено: {knowledgeSheet.data.last_sync_updated}, одобрено автоматически: {knowledgeSheet.data.last_sync_auto_approved}, только для администратора: {knowledgeSheet.data.last_sync_human_only}.</small>}
                    {knowledgeSheet.data.last_sync_status === "error" && <div className="error-box">{knowledgeSheet.data.last_sync_error}</div>}
                    <div className="inline-actions">
                      <button onClick={() => syncSheet.mutate()} disabled={syncSheet.isPending}>{syncSheet.isPending ? <><span className="spinner" aria-hidden="true"/>Синхронизация…</> : "Синхронизировать сейчас"}</button>
                    </div>
                  </>}
                </div>
                {knowledgeEditorOpen && <form className="knowledge-editor panel" onSubmit={(event) => {
                  event.preventDefault(); saveKnowledge.mutate(knowledgeDraft);
                }}>
                  <div className="panel-head"><div><h2>{knowledgeDraft.id ? "Редактирование ответа" : "Новый ответ бота"}</h2><p>После сохранения материал останется выключенным до вашего одобрения.</p></div></div>
                  <div className="two-col">
                    <label>Категория<input required minLength={2} value={knowledgeDraft.category} onChange={e => setKnowledgeDraft({...knowledgeDraft, category:e.target.value})}/></label>
                    <label>Режим<select value={knowledgeDraft.risk_level} onChange={e => setKnowledgeDraft({...knowledgeDraft, risk_level:e.target.value as KnowledgeDraft["risk_level"]})}><option value="review">Проверить перед включением</option><option value="safe">Безопасный FAQ</option><option value="human_only">Только администратору</option></select></label>
                  </div>
                  <label>Вопрос или название<input required minLength={2} value={knowledgeDraft.title} onChange={e => setKnowledgeDraft({...knowledgeDraft, title:e.target.value})}/></label>
                  <label>Ответ на русском<textarea rows={4} value={knowledgeDraft.content_ru} onChange={e => setKnowledgeDraft({...knowledgeDraft, content_ru:e.target.value})}/></label>
                  <label>Ответ на казахском<textarea rows={4} value={knowledgeDraft.content_kk} onChange={e => setKnowledgeDraft({...knowledgeDraft, content_kk:e.target.value})}/></label>
                  {saveKnowledge.isError && <div className="error-box">{saveKnowledge.error.message}</div>}
                  <div className="inline-actions"><button type="button" onClick={() => setKnowledgeEditorOpen(false)}>Отмена</button><button className="primary" disabled={saveKnowledge.isPending || (!knowledgeDraft.content_ru.trim() && !knowledgeDraft.content_kk.trim())}>{saveKnowledge.isPending ? <><span className="spinner" aria-hidden="true"/>Сохраняем…</> : "Сохранить черновик"}</button></div>
                </form>}
              </> : <div className="info-panel"><span>i</span><div><strong>Базой знаний управляет владелец</strong><p>Администраторы видят утверждённые материалы, но не могут менять ответы бота.</p></div></div>}
              {importResult && <div className="success-box">{importResult}</div>}
              <div className="wa-knowledge">{knowledge.data?.items.map((item) =>
                <article key={item.id}><div><span>{item.category}</span><strong>{item.title}</strong><p>{item.content_ru}</p>
                  <small>{item.risk_level === "human_only" ? "Только администратору" : item.is_approved ? "Одобрено" : "Требует проверки"}</small>
                </div>{user?.role === "owner" && <div className="knowledge-card-actions"><button className="small" onClick={() => { setKnowledgeDraft({id:item.id,category:item.category,title:item.title,content_ru:item.content_ru||"",content_kk:item.content_kk||"",risk_level:item.risk_level as KnowledgeDraft["risk_level"]}); setKnowledgeEditorOpen(true); }}>Изменить</button>{item.risk_level !== "human_only" && <button className={item.is_approved ? "danger small" : "primary small"} onClick={() => approval.mutate({ item, approved: !item.is_approved })}>{item.is_approved ? "Отключить" : "Одобрить"}</button>}</div>}</article>)}
              </div>
            </div>}
          </section>
        </>}
      </DataState>
    </>
  );
}
