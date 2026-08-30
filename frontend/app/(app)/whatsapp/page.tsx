"use client";

import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/modules/auth";
import { api } from "@/shared/api-client";
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
  status: string; is_draft: boolean; created_at: string;
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
};
type KnowledgeDraft = {
  id?: string; category: string; title: string; content_ru: string;
  content_kk: string; risk_level: "safe" | "review" | "human_only";
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
  const [tab, setTab] = useState<"dialogs" | "test" | "knowledge">("test");
  const [selected, setSelected] = useState("");
  const [testMessage, setTestMessage] = useState("");
  const [lastTestMessage, setLastTestMessage] = useState("");
  const [testContact, setTestContact] = useState(() => `simulator-${Date.now()}`);
  const [humanMessage, setHumanMessage] = useState("");
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [importResult, setImportResult] = useState("");
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
  });
  const detail = useQuery({
    queryKey: ["wa-conversation", selected],
    queryFn: () => api<Detail>(`/whatsapp/conversations/${selected}`),
    enabled: Boolean(selected),
  });
  const knowledge = useQuery({
    queryKey: ["wa-knowledge"],
    queryFn: () => api<{ items: Knowledge[] }>("/whatsapp/knowledge"),
  });
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
                {qrStatus.data?.connected && <small>Подключён номер: +{qrStatus.data.phone}</small>}
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
                  {connectQr.isPending ? "Запускаем…" : qrStatus.data?.qr_data_url ? "Обновить QR" : "Получить QR-код"}
                </button>}
              </div>
            </div>}
            <div className="tabs">
              <button className={tab === "test" ? "active" : ""} onClick={() => setTab("test")}>Симулятор</button>
              <button className={tab === "dialogs" ? "active" : ""} onClick={() => setTab("dialogs")}>Диалоги</button>
              <button className={tab === "knowledge" ? "active" : ""} onClick={() => setTab("knowledge")}>База знаний</button>
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
                  <button className="primary" disabled={simulate.isPending}>{simulate.isPending ? "Проверяем…" : "Отправить"}</button>
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
                      {message.body}{message.is_draft && <small>Черновик — не отправлен</small>}
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
            {tab === "knowledge" && <div>
              {user?.role === "owner" ? <>
                <div className="wa-knowledge-actions">
                  <button className="primary" onClick={() => { setKnowledgeDraft(emptyKnowledge); setKnowledgeEditorOpen(true); }}>Добавить ответ</button>
                  <label className="file-drop"><strong>Загрузить Excel со скриптами</strong><span>Строки одобряются автоматически и сразу используются ботом — редактируйте сам файл перед загрузкой. Рекламные/только для администратора строки всегда остаются на ручной проверке.</span>
                    <input type="file" accept=".xlsx" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadKnowledge(file); }} />
                  </label>
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
                  <div className="inline-actions"><button type="button" onClick={() => setKnowledgeEditorOpen(false)}>Отмена</button><button className="primary" disabled={saveKnowledge.isPending || (!knowledgeDraft.content_ru.trim() && !knowledgeDraft.content_kk.trim())}>{saveKnowledge.isPending ? "Сохраняем…" : "Сохранить черновик"}</button></div>
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
