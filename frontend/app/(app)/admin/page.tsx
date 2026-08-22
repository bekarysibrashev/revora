"use client";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_URL, api, apiBinary } from "@/shared/api-client";
import { PageHeader } from "@/shared/ui";

type Branch = { id:string; name:string; code:string; address:string|null; is_active:boolean };
type User = { id:string; email:string; full_name:string; role:string; branch_ids:string[]; is_active:boolean };
type Connection = { id:string; name:string; provider:string; status:string; settings?:Record<string,unknown> };
type Profile = { id:string; source_entity:string; target_entity:string; version:number; is_active:boolean; rules:Record<string,unknown> };
type OneCToken = { connection_id:string; token:string; allowed_entities:string[] };
type OneCStatus = { connection_id:string; status:string; last_synced_at:string|null; last_entity:string|null; total_records:number; pending_records:number; normalized_records:number; quarantined_records:number; entities:{entity:string;records:number}[]; branch_mappings:{structural_unit_key:string;structural_unit_name:string;branch_code:string}[] };
type OneCNormalize = { connection_id:string; reset:number; processed:number; normalized:number; quarantined:number; remaining:number };
type OneCMetadataProperty = { name:string; type:string; nullable:boolean|null };
type OneCMetadataEntity = { name:string; entity_type:string; properties:OneCMetadataProperty[]; navigation_properties:{name:string;relationship:string|null;target_type:string|null}[] };
type OneCMetadata = { schema_version:string; entities:OneCMetadataEntity[] };
const example = JSON.stringify({
  external_id:{source_fields:["ID","Код пациента"],required:true,transform:"string"},
  full_name:{source_fields:["ФИО","Пациент"],required:true,transform:"string"},
  phone:{source_fields:["Телефон","Мобильный"],transform:"string"}
}, null, 2);

export default function AdminPage() {
  const [tab,setTab]=useState<"data"|"branches"|"users">("data");
  return <><PageHeader title="Настройки" subtitle="Источники данных, филиалы и доступ сотрудников"/>
    <div className="tabs"><button className={tab==="data"?"active":""} onClick={()=>setTab("data")}>Импорт данных</button><button className={tab==="branches"?"active":""} onClick={()=>setTab("branches")}>Филиалы</button><button className={tab==="users"?"active":""} onClick={()=>setTab("users")}>Пользователи</button></div>
    {tab==="data"&&<DataImport/>}{tab==="branches"&&<Branches/>}{tab==="users"&&<Users/>}</>;
}

function DataImport() {
  const qc=useQueryClient();
  const connections=useQuery({queryKey:["connections"],queryFn:()=>api<{items:Connection[]}>("/integrations/connections")});
  const [name,setName]=useState("Основная выгрузка"),[connection,setConnection]=useState("");
  const [source,setSource]=useState("patients"),[target,setTarget]=useState("patient"),[rules,setRules]=useState(example),[profile,setProfile]=useState("");
  const [file,setFile]=useState<File|null>(null),[result,setResult]=useState<Record<string,number|string>|null>(null),[error,setError]=useState(""),[isUploading,setIsUploading]=useState(false);
  const [stage,setStage]=useState(0);
  const stageTimers=useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(()=>()=>{stageTimers.current.forEach(clearTimeout)},[]);
  const profiles=useQuery({queryKey:["mappings",connection],queryFn:()=>api<{items:Profile[]}>(`/integrations/connections/${connection}/mappings`),enabled:!!connection});
  useEffect(()=>{const current=profiles.data?.items.find(x=>x.is_active);if(current&&!profile){setProfile(current.id);setSource(current.source_entity);setTarget(current.target_entity);const definition=current.rules as {fields?:unknown};if(definition.fields)setRules(JSON.stringify(definition.fields,null,2))}},[profiles.data,profile]);
  const createConnection=useMutation({mutationFn:()=>api<Connection>("/integrations/connections",{method:"POST",body:JSON.stringify({provider:"tabular",name,settings:{}})}),onSuccess:x=>{setConnection(x.id);qc.invalidateQueries({queryKey:["connections"]})}});
  const deleteProfile=useMutation({mutationFn:(id:string)=>api<void>(`/integrations/connections/${connection}/mappings/${id}`,{method:"DELETE"}),onSuccess:()=>{setProfile("");setRules(example);qc.invalidateQueries({queryKey:["mappings",connection]})}});
  async function saveMapping(){setError("");try{const x=await api<{id:string}>(`/integrations/connections/${connection}/mappings`,{method:"POST",body:JSON.stringify({source_entity:source,target_entity:target,fields:JSON.parse(rules)})});setProfile(x.id);qc.invalidateQueries({queryKey:["mappings",connection]})}catch(e){setError(e instanceof Error?e.message:"Ошибка настройки")}}
  async function upload(){
    if(!file)return;
    setError("");setResult(null);setIsUploading(true);setStage(0);
    stageTimers.current.forEach(clearTimeout);
    stageTimers.current=[setTimeout(()=>setStage(1),900),setTimeout(()=>setStage(2),2200)];
    try{
      const p=new URLSearchParams({mapping_profile_id:profile,filename:file.name,source_entity:source});
      const r=await apiBinary(`/integrations/connections/${connection}/ingest?${p}`,{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});
      setResult(await r.json());
    }catch(e){
      setError(e instanceof Error?e.message:"Ошибка загрузки");
    }finally{
      stageTimers.current.forEach(clearTimeout);
      setIsUploading(false);setStage(0);
    }
  }
  return <div className="admin-stack">
    <OneCIntegration/>
    <section className="panel"><Step n="1" title="Источник" text="Создайте подключение для таблиц этой клиники."/>
      {connections.data?.items.length?<label>Подключение<select value={connection} onChange={e=>{setConnection(e.target.value);setProfile("")}}><option value="">Выберите источник</option>{connections.data.items.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>:null}
      <div className="inline-form"><input value={name} onChange={e=>setName(e.target.value)} placeholder="Название источника"/><button onClick={()=>createConnection.mutate()} disabled={createConnection.isPending}>Добавить источник</button></div>
    </section>
    <section className="panel"><Step n="2" title="Правила преобразования" text="Свяжите колонки клиники с единой структурой Revora."/>
      {profiles.data?.items.length?<label>Сохранённый профиль<div className="inline-form"><select value={profile} onChange={e=>{const p=profiles.data?.items.find(x=>x.id===e.target.value);setProfile(e.target.value);if(p){setSource(p.source_entity);setTarget(p.target_entity);const r=p.rules as {fields?:unknown};if(r.fields)setRules(JSON.stringify(r.fields,null,2))}}}><option value="">Новый профиль</option>{profiles.data.items.map(x=><option key={x.id} value={x.id}>{x.source_entity} → {x.target_entity}, версия {x.version}{x.is_active?" · активен":""}</option>)}</select>{profile&&<button type="button" className="danger small" onClick={()=>{if(confirm("Удалить этот профиль маппинга? Уже загруженные записи не пострадают, но профиль пропадёт из списка."))deleteProfile.mutate(profile)}} disabled={deleteProfile.isPending}>{deleteProfile.isPending?"Удаление…":"Удалить"}</button>}</div></label>:null}
      <div className="form-grid"><label>Тип исходных данных<input value={source} onChange={e=>setSource(e.target.value)}/></label><label>Куда загрузить<select value={target} onChange={e=>setTarget(e.target.value)}>{targets.map(x=><option key={x[0]} value={x[0]}>{x[1]}</option>)}</select></label></div>
      <label>Соответствие колонок (JSON)<textarea rows={10} value={rules} onChange={e=>setRules(e.target.value)} spellCheck={false}/></label>
      <button className="primary small" onClick={saveMapping} disabled={!connection}>Сохранить новую версию правил</button>{profile&&<p className="success-box">Профиль готов к загрузке: {profile}</p>}
    </section>
    <section className="panel"><Step n="3" title="Загрузка файла" text="CSV/XLSX до 50 МБ. Исходные строки сохраняются, ошибки изолируются."/>
      <label className="file-drop"><input type="file" accept=".csv,.xls,.xlsx" onChange={e=>setFile(e.target.files?.[0]||null)} disabled={isUploading}/><strong>{file?file.name:"Выберите CSV или XLSX"}</strong><span>до 50 МБ</span></label>
      <button className="primary small" onClick={upload} disabled={!file||!profile||isUploading}>{isUploading?<><span className="spinner" aria-hidden="true"/>Загружаем и проверяем файл…</>:"Проверить и загрузить"}</button>
      {isUploading&&<UploadProgress stage={stage}/>}
      {result&&<div className="import-result"><strong>Импорт завершён</strong><span>Прочитано: {result.records_read}</span><span>Загружено: {result.records_normalized}</span><span>Ошибок: {result.records_quarantined}</span><span>Дубликатов: {result.records_duplicate}</span></div>}{error&&<div className="error-box">{error}</div>}
    </section>
  </div>;
}

const oneCEntityLabels:Record<string,string>={
  "AccumulationRegister_Выручка_RecordType":"Выручка",
  "AccumulationRegister_ДенежныеСредства_RecordType":"Денежные средства",
  "AccumulationRegister_Затраты_RecordType":"Затраты",
  "AccumulationRegister_НарядЗаказы_RecordType":"Наряд-заказы",
  "AccumulationRegister_Продажи_RecordType":"Продажи",
  "AccumulationRegister_ПродажиСебестоимость_RecordType":"Себестоимость продаж",
  "AccumulationRegister_РабочееВремяСотрудников_RecordType":"Рабочее время",
  "AccumulationRegister_РасчетыСПерсоналом_RecordType":"Расчёты с персоналом",
  "Catalog_СтруктурныеЕдиницы":"Филиалы 1С",
  "Document_НачислениеЗарплаты":"Начисление зарплаты"
};

function OneCIntegration(){
  const qc=useQueryClient();
  const connections=useQuery({queryKey:["connections"],queryFn:()=>api<{items:Connection[]}>('/integrations/connections')});
  const oneCConnections=(connections.data?.items||[]).filter(x=>x.provider==="1c_odata_push");
  const [connectionId,setConnectionId]=useState("");
  const [token,setToken]=useState<OneCToken|null>(null);
  const [copied,setCopied]=useState(false);
  const [normalizing,setNormalizing]=useState(false);
  const [normalizeProgress,setNormalizeProgress]=useState<{processed:number;normalized:number;quarantined:number;remaining:number}|null>(null);
  const [normalizeError,setNormalizeError]=useState("");
  const [showMetadata,setShowMetadata]=useState(false);
  const [metadataSearch,setMetadataSearch]=useState("");
  useEffect(()=>{if(!connectionId&&oneCConnections[0])setConnectionId(oneCConnections[0].id)},[connectionId,oneCConnections]);
  const create=useMutation({
    mutationFn:()=>api<Connection>("/integrations/connections",{method:"POST",body:JSON.stringify({provider:"1c_odata_push",name:"1С Stoma",settings:{}})}),
    onSuccess:x=>{setConnectionId(x.id);qc.invalidateQueries({queryKey:["connections"]})}
  });
  const rotate=useMutation({
    mutationFn:()=>api<OneCToken>(`/integrations/connections/${connectionId}/connector-token`,{method:"POST"}),
    onSuccess:x=>{setToken(x);setCopied(false);qc.invalidateQueries({queryKey:["connections"]})}
  });
  const sync=useQuery({
    queryKey:["one-c-sync",connectionId],
    queryFn:()=>api<OneCStatus>(`/integrations/connections/${connectionId}/sync-status`),
    enabled:!!connectionId,
    refetchInterval:15000
  });
  const metadata=useQuery({
    queryKey:["one-c-metadata",connectionId],
    queryFn:()=>api<OneCMetadata>(`/integrations/connections/${connectionId}/1c-metadata`),
    enabled:!!connectionId&&showMetadata
  });
  const status=sync.data;
  const visibleMetadata=(metadata.data?.entities||[]).filter(entity=>{
    const query=metadataSearch.trim().toLocaleLowerCase("ru-RU");
    return !query||entity.name.toLocaleLowerCase("ru-RU").includes(query)||entity.properties.some(property=>property.name.toLocaleLowerCase("ru-RU").includes(query));
  });
  async function copyToken(){if(!token)return;await navigator.clipboard.writeText(token.token);setCopied(true)}
  function downloadMetadata(){
    if(!metadata.data)return;
    const blob=new Blob([JSON.stringify(metadata.data,null,2)],{type:"application/json;charset=utf-8"});
    const url=URL.createObjectURL(blob);
    const link=document.createElement("a");
    link.href=url;link.download="revora-1c-odata-metadata.json";link.click();
    URL.revokeObjectURL(url);
  }
  async function normalizeExisting(resetExisting=false){
    if(!connectionId||normalizing)return;
    if(resetExisting&&!confirm("Пересчитать канонические показатели 1С за последние 90 дней? Исходные данные не удаляются."))return;
    setNormalizing(true);setNormalizeError("");
    let totals={processed:0,normalized:0,quarantined:0,remaining:status?.pending_records||0};
    setNormalizeProgress(totals);
    try{
      let first=true;
      for(;;){
        const batch=await api<OneCNormalize>(`/integrations/connections/${connectionId}/normalize-1c`,{method:"POST",body:JSON.stringify({history_days:90,batch_size:500,reset_existing:resetExisting&&first})});
        first=false;
        totals={processed:totals.processed+batch.processed,normalized:totals.normalized+batch.normalized,quarantined:totals.quarantined+batch.quarantined,remaining:batch.remaining};
        setNormalizeProgress(totals);
        if(batch.remaining===0||batch.processed===0)break;
      }
      await qc.invalidateQueries({queryKey:["one-c-sync",connectionId]});
    }catch(e){setNormalizeError(e instanceof Error?e.message:"Не удалось обработать данные 1С")}
    finally{setNormalizing(false)}
  }
  return <section className="panel">
    <Step n="1С" title="Автоматическая синхронизация 1С" text="OData остаётся на localhost. Локальный коннектор отправляет в Revora только разрешённые финансовые регистры по HTTPS."/>
    {!oneCConnections.length?<button className="primary small" onClick={()=>create.mutate()} disabled={create.isPending}>{create.isPending?"Создаём…":"Создать безопасное подключение 1С"}</button>:<>
      {oneCConnections.length>1&&<label>Подключение<select value={connectionId} onChange={e=>{setConnectionId(e.target.value);setToken(null)}}>{oneCConnections.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>}
      <div className="integration-health">
        <span className={status?.status==="connected"?"badge active":"badge"}>{status?.status==="connected"?"Подключено":"Ожидает первого запуска"}</span>
        <span>Записей: <strong>{status?.total_records||0}</strong></span>
        <span>Последняя синхронизация: <strong>{status?.last_synced_at?new Date(status.last_synced_at).toLocaleString("ru-RU"):"ещё не было"}</strong></span>
      </div>
      {status&&<div className="integration-health">
        <span>В аналитике за 90 дней: <strong>{status.normalized_records||0}</strong></span>
        <span>Ожидают обработки: <strong>{status.pending_records||0}</strong></span>
        <span>Нужна проверка: <strong>{status.quarantined_records||0}</strong></span>
      </div>}
      {status&&<div className="setup-steps">
        <p><strong>Разделение 1С по филиалам:</strong></p>
        {status.branch_mappings.length===2
          ? <p className="success-box">{status.branch_mappings.map(x=>`${x.structural_unit_name} → ${x.branch_code}`).join(" · ")}</p>
          : <p className="error-box">Ожидаются два сопоставленных филиала. Сначала синхронизируйте справочник «Структурные единицы» из 1С.</p>}
      </div>}
      {!!status?.pending_records&&<div className="setup-steps">
        <p><strong>Сырые строки уже сохранены, но ещё не участвуют в дашбордах.</strong> Revora безопасно сопоставит выручку, продажи, затраты и движение денег за последние 90 дней. Неоднозначные строки не попадут в суммы.</p>
        <button className="primary small" onClick={()=>normalizeExisting(false)} disabled={normalizing}>{normalizing?"Обрабатываем данные 1С…":"Добавить данные 1С в аналитику"}</button>
        {normalizeProgress&&<p className="hint">Обработано: {normalizeProgress.processed}. Добавлено в аналитику: {normalizeProgress.normalized}. Нужна проверка: {normalizeProgress.quarantined}. Осталось: {normalizeProgress.remaining}.</p>}
        {normalizeError&&<div className="error-box">{normalizeError}</div>}
      </div>}
      <div className="setup-steps">
        <p><strong>Пересчёт после обновления правил аналитики.</strong> Повторно сопоставляет уже загруженные строки 1С за 90 дней, не удаляя исходные данные.</p>
        <button className="small" onClick={()=>normalizeExisting(true)} disabled={normalizing}>{normalizing?"Пересчитываем…":"Пересчитать аналитику 1С"}</button>
        {normalizeProgress&&<p className="hint">Обработано: {normalizeProgress.processed}. Добавлено в аналитику: {normalizeProgress.normalized}. Нужна проверка: {normalizeProgress.quarantined}. Осталось: {normalizeProgress.remaining}.</p>}
        {normalizeError&&<div className="error-box">{normalizeError}</div>}
      </div>
      {(create.isError||rotate.isError||sync.isError)&&<div className="error-box">{(create.error||rotate.error||sync.error)?.message||"Не удалось выполнить запрос"}</div>}
      {status?.entities.length?<div className="table-wrap"><table><thead><tr><th>Данные 1С</th><th>Сохранено строк</th></tr></thead><tbody>{status.entities.map(x=><tr key={x.entity}><td>{oneCEntityLabels[x.entity]||x.entity}</td><td>{x.records}</td></tr>)}</tbody></table></div>:null}
      <div className="setup-steps">
        <div className="inline-form">
          <button type="button" className="small" onClick={()=>setShowMetadata(value=>!value)}>{showMetadata?"Скрыть структуру OData":"Показать структуру OData"}</button>
          {metadata.data&&<button type="button" className="small" onClick={downloadMetadata}>Скачать структуру JSON</button>}
        </div>
        {showMetadata&&metadata.isLoading&&<p className="hint">Загружаем структуру 1С…</p>}
        {showMetadata&&metadata.isError&&<div className="error-box">{metadata.error.message}</div>}
        {metadata.data&&<>
          <p className="hint">Опубликовано сущностей: <strong>{metadata.data.entities.length}</strong>. Здесь только названия таблиц и полей, без данных пациентов.</p>
          <input value={metadataSearch} onChange={event=>setMetadataSearch(event.target.value)} placeholder="Поиск таблицы или поля"/>
          <div className="table-wrap"><table><thead><tr><th>Таблица OData</th><th>Поля</th></tr></thead><tbody>{visibleMetadata.map(entity=><tr key={entity.name}><td><strong>{entity.name}</strong></td><td><details><summary>{entity.properties.length} полей</summary><div className="hint">{entity.properties.map(property=>`${property.name} (${property.type})`).join(", ")}</div></details></td></tr>)}</tbody></table></div>
        </>}
      </div>
      <div className="inline-form">
        <button className="primary small" onClick={()=>rotate.mutate()} disabled={rotate.isPending}>{rotate.isPending?"Создаём ключ…":token?"Перевыпустить ключ":"Получить ключ коннектора"}</button>
        <a className="button-link" href="/revora-1c-odata.ps1" download>Скачать коннектор PowerShell</a>
      </div>
      {token&&<div className="success-box">
        <strong>Скопируйте ключ сейчас — повторно он не показывается.</strong>
        <textarea rows={3} readOnly value={token.token} spellCheck={false}/>
        <button className="small" onClick={copyToken}>{copied?"Скопировано ✓":"Копировать ключ"}</button>
      </div>}
      <div className="setup-steps">
        <p><strong>На серверном компьютере клиники:</strong></p>
        <ol>
          <li>Скачайте скрипт и положите его в отдельную папку.</li>
          <li>Откройте PowerShell под тем Windows-пользователем, от которого будет идти синхронизация.</li>
          <li>Выполните настройку; скрипт сам запросит логин 1С, пароль и ключ Revora.</li>
        </ol>
        <pre>{`.\\revora-1c-odata.ps1 -Setup -RevoraApiUrl "${API_URL}"`}</pre>
        <p>Проверка доступа к 1С:</p>
        <pre>{`& "$env:LOCALAPPDATA\\Revora\\revora-1c-odata.ps1" -TestConnection`}</pre>
        <p>Первая синхронизация за последние 90 дней:</p>
        <pre>{`& "$env:LOCALAPPDATA\\Revora\\revora-1c-odata.ps1" -FullSync`}</pre>
        <p>Установка задачи Планировщика Windows каждые 3 часа:</p>
        <pre>{`& "$env:LOCALAPPDATA\\Revora\\revora-1c-odata.ps1" -InstallTask`}</pre>
        <p className="hint">Пароль 1С и ключ сохраняются через Windows DPAPI для текущего пользователя Windows. Пароль 1С не передаётся в Revora. Коннектор читает OData только с localhost.</p>
      </div>
    </>}
  </section>
}
const targets: [string,string][]=[["patient","Пациенты"],["doctor","Врачи"],["doctor_rating","Рейтинги врачей"],["service_direction","Направления"],["lead","Лиды"],["appointment","Записи"],["revenue_fact","Выручка"],["expense_fact","Расходы"],["cash_flow_fact","Движение денег"],["account_balance","Остатки"],["marketing_spend_fact","Затраты на маркетинг"],["attribution_fact","Атрибуция рекламы"]];
function Step({n,title,text}:{n:string;title:string;text:string}){return <div className="step-title"><span>{n}</span><div><h2>{title}</h2><p>{text}</p></div></div>}

const uploadStages=["Читаем файл","Проверяем и сопоставляем данные","Сохраняем в базу данных"];
function UploadProgress({stage}:{stage:number}){
  return <div className="upload-progress" role="status" aria-live="polite">
    <div className="upload-progress-bar"><div className="upload-progress-fill"/></div>
    <ul className="upload-progress-steps">
      {uploadStages.map((label,i)=>{
        const state=i<stage?"done":i===stage?"active":"pending";
        return <li key={label} className={state}>
          <span className="upload-progress-dot">{state==="done"?"✓":i+1}</span>
          <span>{label}{state==="active"?"…":""}</span>
        </li>;
      })}
    </ul>
    <p className="hint">Большие файлы (десятки тысяч строк) могут обрабатываться до минуты — не закрывайте страницу.</p>
  </div>;
}

function Branches(){const qc=useQueryClient(),d=useQuery({queryKey:["branches"],queryFn:()=>api<{items:Branch[]}>("/admin/branches")});const[name,setName]=useState(""),[code,setCode]=useState("");async function submit(e:FormEvent){e.preventDefault();await api("/admin/branches",{method:"POST",body:JSON.stringify({name,code})});setName("");setCode("");qc.invalidateQueries({queryKey:["branches"]})}return <section className="panel"><h2>Филиалы клиники</h2><form className="inline-form" onSubmit={submit}><input placeholder="Название" value={name} onChange={e=>setName(e.target.value)} required/><input placeholder="Код, например center" value={code} onChange={e=>setCode(e.target.value)} required pattern="[a-z0-9-]+"/><button>Добавить</button></form><div className="table-wrap"><table><thead><tr><th>Название</th><th>Код</th><th>Адрес</th><th>Статус</th></tr></thead><tbody>{d.data?.items.map(x=><tr key={x.id}><td><strong>{x.name}</strong></td><td>{x.code}</td><td>{x.address||"—"}</td><td><span className={x.is_active?"badge active":"badge"}>{x.is_active?"Активен":"Отключён"}</span></td></tr>)}</tbody></table></div></section>}
function Users(){const qc=useQueryClient();const users=useQuery({queryKey:["users"],queryFn:()=>api<{items:User[]}>("/admin/users")});const branches=useQuery({queryKey:["branches"],queryFn:()=>api<{items:Branch[]}>("/admin/branches")});const[email,setEmail]=useState(""),[full,setFull]=useState(""),[password,setPassword]=useState(""),[role,setRole]=useState("manager"),[branch,setBranch]=useState("");async function submit(e:FormEvent){e.preventDefault();await api("/admin/users",{method:"POST",body:JSON.stringify({email,full_name:full,password,role,branch_ids:branch?[branch]:[]})});setEmail("");setFull("");setPassword("");qc.invalidateQueries({queryKey:["users"]})}return <section className="panel"><h2>Доступ сотрудников</h2><form className="form-grid user-form" onSubmit={submit}><label>Имя<input value={full} onChange={e=>setFull(e.target.value)} required/></label><label>Почта<input type="email" value={email} onChange={e=>setEmail(e.target.value)} required/></label><label>Пароль<input type="password" minLength={8} value={password} onChange={e=>setPassword(e.target.value)} required/></label><label>Роль<select value={role} onChange={e=>setRole(e.target.value)}><option value="manager">Управляющий</option><option value="administrator">Администратор</option><option value="sales_manager">Менеджер продаж</option></select></label><label>Филиал<select value={branch} onChange={e=>setBranch(e.target.value)}><option value="">Все / не назначен</option>{branches.data?.items.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><button className="primary small">Добавить пользователя</button></form><div className="table-wrap"><table><thead><tr><th>Сотрудник</th><th>Почта</th><th>Роль</th><th>Статус</th></tr></thead><tbody>{users.data?.items.map(x=><tr key={x.id}><td><strong>{x.full_name}</strong></td><td>{x.email}</td><td>{({owner:"Владелец",manager:"Управляющий",administrator:"Администратор",sales_manager:"Менеджер продаж"}as Record<string,string>)[x.role]}</td><td><span className={x.is_active?"badge active":"badge"}>{x.is_active?"Активен":"Отключён"}</span></td></tr>)}</tbody></table></div></section>}
