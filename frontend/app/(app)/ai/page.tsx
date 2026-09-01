"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBinary } from "@/shared/api-client";
import { DataState, Metric, PageHeader } from "@/shared/ui";

type Criterion = { name: string; weight: number; description: string };
type RuleSet = { id: string; version: number; name: string; success_definition: string; partial_success_definition: string; loss_definition: string; criteria: Criterion[]; loss_reasons: string[] };
type Status = { rule_set: RuleSet | null; calls_received: number; analyses_ready: number; integration_status: string; queued: number; processing: number; needs_review: number; failed: number };
type CallItem = { id: string; started_at: string; direction: string; employee: string | null; phone_masked: string | null; phone_number: string | null; duration_seconds: number | null; outcome: string | null; recording_url: string | null; analysis_status: string | null; score: number | null; result: string | null; summary: string | null; needs_review: boolean; error_code: string | null };
type Calls = {
  items: CallItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  available_extensions: string[];
  available_directions: string[];
  available_outcomes: string[];
};
type Evidence = { criterion: string; timestamp_from: number; timestamp_to: number; description: string };
type Analysis = { id:string;call_id:string;status:string;result:string|null;score:number|null;summary:string|null;criteria_scores:Array<{name:string;score:number;weight:number;explanation:string}>;strengths:string[];loss_reasons:string[];recommendations:string[];flags:Record<string,boolean>;evidence:Evidence[];languages:string[];mixed_language:boolean|null;confidence:number|null;needs_review:boolean;attempt_count:number;error_code:string|null;model_version:string|null;completed_at:string|null };
type Operators = { items:Array<{employee:string;calls_analyzed:number;average_score:number;successful_calls:number;success_rate:number;needs_review:number}> };
type ManualTest = { call_id:string;analysis_id:string;status:string };
type ContactItem = { phone_number:string;call_count:number;qualified_calls:number;first_call_at:string;last_call_at:string;first_call_duration_seconds:number|null;total_duration_seconds:number;last_outcome:string|null;extensions:string[];contact_type:"first"|"repeat" };
type Contacts = { items:ContactItem[];summary:{unique_contacts:number;first_only:number;repeat_contacts:number;total_calls:number;qualified_calls:number};total:number;page:number;page_size:number;pages:number };

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
const analysisLabel = (value: string | null) => ({ pending: "Ожидает", queued: "В очереди", retrying: "Повторная попытка", waiting_for_recording: "Ждёт запись", processing: "Анализируется", ready: "Готов", needs_review: "Нужна проверка", skipped_short: "Не длиннее 10 сек.", failed: "Ошибка" }[value || ""] || "Правила не заданы");
const durationLabel = (seconds: number | null) => seconds == null ? "—" : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export default function AiPage() {
  const client = useQueryClient();
  const [callPage, setCallPage] = useState(1);
  const [extension, setExtension] = useState("");
  const [direction, setDirection] = useState("");
  const [outcome, setOutcome] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [journalTab, setJournalTab] = useState<"calls"|"contacts">("calls");
  const [durationMin, setDurationMin] = useState("");
  const [durationMax, setDurationMax] = useState("");
  const [callSort, setCallSort] = useState("started_at:desc");
  const [contactPage, setContactPage] = useState(1);
  const [contactSearch, setContactSearch] = useState("");
  const [contactType, setContactType] = useState("");
  const [contactSort, setContactSort] = useState("last_call_at:desc");
  const callParams = new URLSearchParams({
    page: String(callPage),
    page_size: "10",
  });
  if (extension) callParams.set("extension", extension);
  if (direction) callParams.set("direction", direction);
  if (outcome) callParams.set("outcome", outcome);
  if (dateFrom) callParams.set("date_from", dateFrom);
  if (dateTo) callParams.set("date_to", dateTo);
  if (durationMin) callParams.set("duration_min", durationMin);
  if (durationMax) callParams.set("duration_max", durationMax);
  const [callSortBy, callSortOrder] = callSort.split(":");
  callParams.set("sort_by", callSortBy);
  callParams.set("sort_order", callSortOrder);
  const contactParams = new URLSearchParams({page:String(contactPage),page_size:"25"});
  if (dateFrom) contactParams.set("date_from", dateFrom);
  if (dateTo) contactParams.set("date_to", dateTo);
  if (contactSearch) contactParams.set("search", contactSearch);
  if (contactType) contactParams.set("contact_type", contactType);
  const [contactSortBy, contactSortOrder] = contactSort.split(":");
  contactParams.set("sort_by", contactSortBy);
  contactParams.set("sort_order", contactSortOrder);
  const status = useQuery({ queryKey: ["call-quality-status"], queryFn: () => api<Status>("/call-quality/status"), refetchInterval: 5000 });
  const calls = useQuery({
    queryKey: ["call-quality-calls", callParams.toString()],
    queryFn: () => api<Calls>(`/call-quality/calls?${callParams.toString()}`),
    refetchInterval: 5000,
  });
  const operators = useQuery({ queryKey:["call-quality-operators"], queryFn:()=>api<Operators>("/call-quality/operators"), refetchInterval:10000 });
  const contacts = useQuery({ queryKey:["call-contacts",contactParams.toString()], queryFn:()=>api<Contacts>(`/call-quality/contacts?${contactParams}`), refetchInterval:10000 });
  const current = status.data?.rule_set;
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<typeof defaults>(defaults);
  const [selectedCall, setSelectedCall] = useState<string|null>(null);
  const [audioFile, setAudioFile] = useState<File|null>(null);
  const [operatorName, setOperatorName] = useState("Тестовый оператор");
  const analysis = useQuery({ queryKey:["call-analysis",selectedCall], queryFn:()=>api<Analysis>(`/call-quality/calls/${selectedCall}/analysis`), enabled:Boolean(selectedCall), refetchInterval: query => ["queued","processing","retrying","pending"].includes(query.state.data?.status || "") ? 3000 : false });
  const save = useMutation({ mutationFn: () => api<RuleSet>("/call-quality/rule-sets", { method: "POST", body: JSON.stringify(form) }), onSuccess: () => { client.invalidateQueries({ queryKey: ["call-quality-status"] }); setEditing(false); } });
  const upload = useMutation({ mutationFn: () => {
    if (!audioFile) throw new Error("Выберите аудиофайл");
    return api<ManualTest>("/call-quality/manual-tests",{method:"POST",headers:{"Content-Type":audioFile.type || "audio/mpeg","X-Filename":encodeURIComponent(audioFile.name),"X-Operator-Name":encodeURIComponent(operatorName)},body:audioFile});
  },onSuccess:data=>{setSelectedCall(data.call_id);setAudioFile(null);client.invalidateQueries({queryKey:["call-quality-calls"]});client.invalidateQueries({queryKey:["call-quality-status"]});}});
  const reanalyze = useMutation({mutationFn:(callId:string)=>api<Analysis>(`/call-quality/calls/${callId}/reanalyze`,{method:"POST"}),onSuccess:data=>{setSelectedCall(data.call_id);client.invalidateQueries({queryKey:["call-analysis",data.call_id]});}});
  const begin = () => { setForm(current || defaults); setEditing(true); };
  async function exportContacts() {
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const response = await apiBinary(`/call-quality/contacts/export?${params}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "revora-callers.xlsx"; anchor.click();
    URL.revokeObjectURL(url);
  }

  return <>
    <PageHeader title="Контроль звонков" subtitle="Журнал Kcell и оценка работы администраторов" action={<button className="primary" onClick={begin}>{current ? "Изменить стандарт" : "Настроить стандарт"}</button>} />
    <DataState loading={status.isLoading} error={status.error}>
      <section className="metric-grid">
        <Metric label="Звонков получено" value={String(status.data?.calls_received || 0)} />
        <Metric label="ИИ проанализировал" value={String(status.data?.analyses_ready || 0)} />
        <Metric label="В очереди" value={String((status.data?.queued || 0)+(status.data?.processing || 0))} note={status.data?.needs_review ? `Проверить вручную: ${status.data.needs_review}` : undefined} />
        <Metric label="Интеграция Kcell" value={status.data?.integration_status === "connected" ? "Подключена" : "Ожидает подключения"} tone={status.data?.integration_status === "connected" ? "good" : undefined} />
      </section>
    </DataState>

    <section className="panel call-manual-test">
      <div className="panel-head"><div><h2>Ручная проверка AI</h2><p>Дополнительный режим для спорного звонка или тестовой MP3. Автоматические Kcell-звонки загружать не нужно.</p></div></div>
      <div className="call-upload-row">
        <label>Оператор<input value={operatorName} maxLength={150} onChange={event=>setOperatorName(event.target.value)} /></label>
        <label className="file-drop">Аудиозапись<input type="file" accept=".mp3,.m4a,.wav,.ogg,.webm,audio/*" onChange={event=>setAudioFile(event.target.files?.[0]||null)} /><span>{audioFile?.name || "Выберите MP3, M4A, WAV, OGG или WEBM"}</span></label>
        <button className="primary" disabled={!audioFile||upload.isPending} onClick={()=>upload.mutate()}>{upload.isPending?<><span className="spinner" aria-hidden="true"/>ИИ анализирует…</>:"Проверить звонок"}</button>
      </div>
      {upload.error&&<p className="error-box">{upload.error instanceof Error?upload.error.message:"Не удалось загрузить запись"}</p>}
      {upload.data&&<p className={upload.data.status==="failed"?"error-box":"success-box"}>{upload.data.status==="failed"?"Анализ завершился ошибкой — откройте отчёт для кода ошибки.":"Анализ завершён. Откройте сформированный отчёт."}</p>}
    </section>

    <div className="journal-tabs" role="tablist">
      <button className={journalTab==="calls"?"active":""} onClick={()=>setJournalTab("calls")}>Журнал звонков</button>
      <button className={journalTab==="contacts"?"active":""} onClick={()=>setJournalTab("contacts")}>База обращений</button>
    </div>

    {journalTab === "calls" && <section className="panel">
      <div className="panel-head"><div><h2>Последние звонки</h2><p>Автоматически получены из виртуальной АТС Kcell</p></div></div>
      <div className="call-filters">
        <label>Внутренний номер
          <select value={extension} onChange={(event) => { setExtension(event.target.value); setCallPage(1); }}>
            <option value="">Все номера</option>
            {calls.data?.available_extensions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label>Направление
          <select value={direction} onChange={(event) => { setDirection(event.target.value); setCallPage(1); }}>
            <option value="">Все</option>
            {calls.data?.available_directions.map((value) => <option key={value} value={value}>{directionLabel(value)}</option>)}
          </select>
        </label>
        <label>Результат
          <select value={outcome} onChange={(event) => { setOutcome(event.target.value); setCallPage(1); }}>
            <option value="">Все</option>
            {calls.data?.available_outcomes.map((value) => <option key={value} value={value}>{outcomeLabel(value)}</option>)}
          </select>
        </label>
        <label>С даты<input type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setCallPage(1); }} /></label>
        <label>По дату<input type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setCallPage(1); }} /></label>
        <label>Мин. длительность<input type="number" min="0" placeholder="сек." value={durationMin} onChange={(event)=>{setDurationMin(event.target.value);setCallPage(1);}} /></label>
        <label>Макс. длительность<input type="number" min="0" placeholder="сек." value={durationMax} onChange={(event)=>{setDurationMax(event.target.value);setCallPage(1);}} /></label>
        <label>Сортировка<select value={callSort} onChange={(event)=>{setCallSort(event.target.value);setCallPage(1);}}><option value="started_at:desc">Сначала новые</option><option value="started_at:asc">Сначала старые</option><option value="duration:desc">Самые долгие</option><option value="duration:asc">Самые короткие</option><option value="extension:asc">По внутреннему номеру</option></select></label>
        {(extension || direction || outcome || dateFrom || dateTo || durationMin || durationMax) && (
          <button className="quiet-button" onClick={() => { setExtension(""); setDirection(""); setOutcome(""); setDateFrom(""); setDateTo(""); setDurationMin(""); setDurationMax(""); setCallPage(1); }}>Сбросить</button>
        )}
      </div>
      <DataState loading={calls.isLoading} error={calls.error}>
        <div className="table-wrap"><table><thead><tr><th>Дата и время</th><th>Тип</th><th>Сотрудник</th><th>Клиент</th><th>Длительность</th><th>Результат</th><th>Запись</th><th>ИИ-анализ</th></tr></thead><tbody>
          {calls.data?.items.map(call => <tr key={call.id}>
            <td>{new Date(call.started_at).toLocaleString("ru-RU")}</td><td>{directionLabel(call.direction)}</td><td>{call.employee || "—"}</td><td>{call.phone_number || call.phone_masked || "Скрыт"}</td><td>{durationLabel(call.duration_seconds)}</td><td>{outcomeLabel(call.outcome)}</td>
            <td>{call.recording_url ? <a className="good" href={call.recording_url} target="_blank" rel="noreferrer">Прослушать</a> : "Нет записи"}</td>
            <td><button className={`analysis-status ${call.analysis_status||""}`} onClick={()=>setSelectedCall(call.id)}>{call.score != null ? `${call.score}/100 · ${analysisLabel(call.analysis_status)}` : analysisLabel(call.analysis_status)}</button></td>
          </tr>)}
          {!calls.data?.items.length && <tr><td className="empty" colSpan={8}>Звонки пока не получены</td></tr>}
        </tbody></table></div>
        {!!calls.data?.total && (
          <div className="pagination">
            <button disabled={callPage <= 1} onClick={() => setCallPage((value) => value - 1)}>← Назад</button>
            <span>Страница {calls.data.page} из {calls.data.pages} · {calls.data.total} звонков</span>
            <button disabled={callPage >= calls.data.pages} onClick={() => setCallPage((value) => value + 1)}>Дальше →</button>
          </div>
        )}
      </DataState>
    </section>}

    {journalTab === "contacts" && <>
      <section className="metric-grid call-contact-metrics">
        <Metric label="Уникальных номеров" value={String(contacts.data?.summary.unique_contacts||0)} note="Автоматически из Kcell" />
        <Metric label="Первые обращения" value={String(contacts.data?.summary.first_only||0)} note="Номер звонил один раз" />
        <Metric label="Повторные обращения" value={String(contacts.data?.summary.repeat_contacts||0)} note="Номер звонил 2+ раза" />
        <Metric label="Всего звонков" value={String(contacts.data?.summary.total_calls||0)} note={`Дольше 20 сек.: ${contacts.data?.summary.qualified_calls||0}`} />
      </section>
      <section className="panel">
        <div className="panel-head"><div><h2>Сохраняльщик обращений</h2><p>Каждый внешний номер и точное количество его звонков. Номера показываются полностью.</p></div><button className="primary small" onClick={exportContacts}>Выгрузить Excel</button></div>
        <div className="call-filters compact">
          <label>Поиск номера<input value={contactSearch} placeholder="87774548922" onChange={event=>{setContactSearch(event.target.value);setContactPage(1);}} /></label>
          <label>Тип<select value={contactType} onChange={event=>{setContactType(event.target.value);setContactPage(1);}}><option value="">Все обращения</option><option value="first">Первое</option><option value="repeat">Повторное</option></select></label>
          <label>Сортировка<select value={contactSort} onChange={event=>{setContactSort(event.target.value);setContactPage(1);}}><option value="last_call_at:desc">Недавно звонили</option><option value="call_count:desc">Больше звонков</option><option value="duration:desc">Больше минут</option><option value="phone:asc">По номеру</option></select></label>
        </div>
        <DataState loading={contacts.isLoading} error={contacts.error}><div className="table-wrap"><table><thead><tr><th>Номер</th><th>Звонков</th><th>Тип</th><th>Первый звонок</th><th>Последний звонок</th><th>Общая длительность</th><th>Внутренние номера</th></tr></thead><tbody>
          {contacts.data?.items.map(item=><tr key={item.phone_number}><td><strong>{item.phone_number}</strong></td><td><span className="call-count-badge">{item.call_count} раза</span></td><td><span className={`health-badge ${item.contact_type==="repeat"?"warning":"ready"}`}>{item.contact_type==="repeat"?"Повторное":"Первое"}</span></td><td>{new Date(item.first_call_at).toLocaleString("ru-RU")}</td><td>{new Date(item.last_call_at).toLocaleString("ru-RU")}</td><td>{durationLabel(item.total_duration_seconds)}</td><td>{item.extensions.join(", ")||"—"}</td></tr>)}
          {!contacts.data?.items.length&&<tr><td colSpan={7} className="empty">В выбранном периоде внешних номеров нет</td></tr>}
        </tbody></table></div></DataState>
        {!!contacts.data?.total&&<div className="pagination"><button disabled={contactPage<=1} onClick={()=>setContactPage(value=>value-1)}>← Назад</button><span>Страница {contacts.data.page} из {contacts.data.pages} · {contacts.data.total} номеров</span><button disabled={contactPage>=contacts.data.pages} onClick={()=>setContactPage(value=>value+1)}>Дальше →</button></div>}
      </section>
    </>}

    <section className="panel">
      <div className="panel-head"><div><h2>Успеваемость операторов</h2><p>Рейтинг строится только по завершённым AI-отчётам</p></div></div>
      <DataState loading={operators.isLoading} error={operators.error}><div className="table-wrap"><table><thead><tr><th>Оператор</th><th>Звонков</th><th>Средняя оценка</th><th>Успешных</th><th>Конверсия</th><th>Проверить</th></tr></thead><tbody>
        {operators.data?.items.map(item=><tr key={item.employee}><td>{item.employee}</td><td>{item.calls_analyzed}</td><td>{item.average_score}/100</td><td>{item.successful_calls}</td><td>{item.success_rate}%</td><td>{item.needs_review}</td></tr>)}
        {!operators.data?.items.length&&<tr><td className="empty" colSpan={6}>Готовых отчётов пока нет</td></tr>}
      </tbody></table></div></DataState>
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
      <button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? <><span className="spinner" aria-hidden="true"/>Сохраняем…</> : "Сохранить новую версию"}</button>
    </section></div>}

    {selectedCall&&<div className="modal-backdrop"><section className="panel modal call-report"><div className="page-header"><div><h2>AI-отчёт по звонку</h2><p>Полная расшифровка не сохраняется</p></div><button className="icon-button" onClick={()=>setSelectedCall(null)}>×</button></div>
      <DataState loading={analysis.isLoading} error={analysis.error}>{analysis.data&&<>
        <div className="call-report-head"><strong>{analysis.data.score==null?"—":`${analysis.data.score}/100`}</strong><div><span className={`health-badge ${analysis.data.needs_review?"warning":"ready"}`}>{analysisLabel(analysis.data.status)}</span><p>{analysis.data.summary||"Отчёт ещё формируется"}</p></div></div>
        {analysis.data.languages.length>0&&<p className="hint">Языки: {analysis.data.languages.join(", ")}{analysis.data.mixed_language?" · смешанная речь":""} · уверенность: {analysis.data.confidence==null?"—":`${Math.round(analysis.data.confidence*100)}%`}</p>}
        {analysis.data.criteria_scores.length>0&&<div className="call-criteria">{analysis.data.criteria_scores.map(item=><article key={item.name}><div><strong>{item.name}</strong><b>{item.score}/100</b></div><small>Вес {item.weight}%</small><p>{item.explanation}</p></article>)}</div>}
        <div className="two-col"><div><h3>Сильные стороны</h3><ul>{analysis.data.strengths.map(item=><li key={item}>{item}</li>)}</ul></div><div><h3>Что улучшить</h3><ul>{analysis.data.recommendations.map(item=><li key={item}>{item}</li>)}</ul></div></div>
        {analysis.data.evidence.length>0&&<div><h3>Основания оценки</h3><div className="call-evidence">{analysis.data.evidence.map((item,index)=><article key={`${item.criterion}-${index}`}><strong>{durationLabel(Math.round(item.timestamp_from))}–{durationLabel(Math.round(item.timestamp_to))} · {item.criterion}</strong><p>{item.description}</p></article>)}</div></div>}
        {analysis.data.error_code&&<p className="error-box">Код ошибки: {analysis.data.error_code}</p>}
        {calls.data?.items.find(item=>item.id===selectedCall)?.recording_url&&<button className="primary small" disabled={reanalyze.isPending} onClick={()=>reanalyze.mutate(selectedCall)}>{reanalyze.isPending?<><span className="spinner" aria-hidden="true"/>Ставим в очередь…</>:"Проверить повторно"}</button>}
      </>}</DataState>
    </section></div>}
  </>;
}
