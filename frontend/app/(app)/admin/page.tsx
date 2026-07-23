"use client";
import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBinary } from "@/shared/api-client";
import { PageHeader } from "@/shared/ui";

type Branch = { id:string; name:string; code:string; address:string|null; is_active:boolean };
type User = { id:string; email:string; full_name:string; role:string; branch_ids:string[]; is_active:boolean };
type Connection = { id:string; name:string; provider:string; status:string };
type Profile = { id:string; source_entity:string; target_entity:string; version:number; is_active:boolean; rules:Record<string,unknown> };
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
  const profiles=useQuery({queryKey:["mappings",connection],queryFn:()=>api<{items:Profile[]}>(`/integrations/connections/${connection}/mappings`),enabled:!!connection});
  useEffect(()=>{const current=profiles.data?.items.find(x=>x.is_active);if(current&&!profile){setProfile(current.id);setSource(current.source_entity);setTarget(current.target_entity);const definition=current.rules as {fields?:unknown};if(definition.fields)setRules(JSON.stringify(definition.fields,null,2))}},[profiles.data,profile]);
  const createConnection=useMutation({mutationFn:()=>api<Connection>("/integrations/connections",{method:"POST",body:JSON.stringify({provider:"tabular",name,settings:{}})}),onSuccess:x=>{setConnection(x.id);qc.invalidateQueries({queryKey:["connections"]})}});
  const deleteProfile=useMutation({mutationFn:(id:string)=>api<void>(`/integrations/connections/${connection}/mappings/${id}`,{method:"DELETE"}),onSuccess:()=>{setProfile("");setRules(example);qc.invalidateQueries({queryKey:["mappings",connection]})}});
  async function saveMapping(){setError("");try{const x=await api<{id:string}>(`/integrations/connections/${connection}/mappings`,{method:"POST",body:JSON.stringify({source_entity:source,target_entity:target,fields:JSON.parse(rules)})});setProfile(x.id);qc.invalidateQueries({queryKey:["mappings",connection]})}catch(e){setError(e instanceof Error?e.message:"Ошибка настройки")}}
  async function upload(){if(!file)return;setError("");setResult(null);setIsUploading(true);try{const p=new URLSearchParams({mapping_profile_id:profile,filename:file.name,source_entity:source});const r=await apiBinary(`/integrations/connections/${connection}/ingest?${p}`,{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});setResult(await r.json())}catch(e){setError(e instanceof Error?e.message:"Ошибка загрузки")}finally{setIsUploading(false)}}
  return <div className="admin-stack">
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
      {isUploading&&<p className="hint">Большие файлы (десятки тысяч строк) могут обрабатываться до минуты — не закрывайте страницу.</p>}
      {result&&<div className="import-result"><strong>Импорт завершён</strong><span>Прочитано: {result.records_read}</span><span>Загружено: {result.records_normalized}</span><span>Ошибок: {result.records_quarantined}</span><span>Дубликатов: {result.records_duplicate}</span></div>}{error&&<div className="error-box">{error}</div>}
    </section>
  </div>;
}
const targets: [string,string][]=[["patient","Пациенты"],["doctor","Врачи"],["doctor_rating","Рейтинги врачей"],["service_direction","Направления"],["lead","Лиды"],["appointment","Записи"],["revenue_fact","Выручка"],["expense_fact","Расходы"],["cash_flow_fact","Движение денег"],["account_balance","Остатки"],["marketing_spend_fact","Затраты на маркетинг"],["attribution_fact","Атрибуция рекламы"]];
function Step({n,title,text}:{n:string;title:string;text:string}){return <div className="step-title"><span>{n}</span><div><h2>{title}</h2><p>{text}</p></div></div>}

function Branches(){const qc=useQueryClient(),d=useQuery({queryKey:["branches"],queryFn:()=>api<{items:Branch[]}>("/admin/branches")});const[name,setName]=useState(""),[code,setCode]=useState("");async function submit(e:FormEvent){e.preventDefault();await api("/admin/branches",{method:"POST",body:JSON.stringify({name,code})});setName("");setCode("");qc.invalidateQueries({queryKey:["branches"]})}return <section className="panel"><h2>Филиалы клиники</h2><form className="inline-form" onSubmit={submit}><input placeholder="Название" value={name} onChange={e=>setName(e.target.value)} required/><input placeholder="Код, например center" value={code} onChange={e=>setCode(e.target.value)} required pattern="[a-z0-9-]+"/><button>Добавить</button></form><div className="table-wrap"><table><thead><tr><th>Название</th><th>Код</th><th>Адрес</th><th>Статус</th></tr></thead><tbody>{d.data?.items.map(x=><tr key={x.id}><td><strong>{x.name}</strong></td><td>{x.code}</td><td>{x.address||"—"}</td><td><span className={x.is_active?"badge active":"badge"}>{x.is_active?"Активен":"Отключён"}</span></td></tr>)}</tbody></table></div></section>}
function Users(){const qc=useQueryClient();const users=useQuery({queryKey:["users"],queryFn:()=>api<{items:User[]}>("/admin/users")});const branches=useQuery({queryKey:["branches"],queryFn:()=>api<{items:Branch[]}>("/admin/branches")});const[email,setEmail]=useState(""),[full,setFull]=useState(""),[password,setPassword]=useState(""),[role,setRole]=useState("manager"),[branch,setBranch]=useState("");async function submit(e:FormEvent){e.preventDefault();await api("/admin/users",{method:"POST",body:JSON.stringify({email,full_name:full,password,role,branch_ids:branch?[branch]:[]})});setEmail("");setFull("");setPassword("");qc.invalidateQueries({queryKey:["users"]})}return <section className="panel"><h2>Доступ сотрудников</h2><form className="form-grid user-form" onSubmit={submit}><label>Имя<input value={full} onChange={e=>setFull(e.target.value)} required/></label><label>Почта<input type="email" value={email} onChange={e=>setEmail(e.target.value)} required/></label><label>Пароль<input type="password" minLength={8} value={password} onChange={e=>setPassword(e.target.value)} required/></label><label>Роль<select value={role} onChange={e=>setRole(e.target.value)}><option value="manager">Управляющий</option><option value="administrator">Администратор</option><option value="sales_manager">Менеджер продаж</option></select></label><label>Филиал<select value={branch} onChange={e=>setBranch(e.target.value)}><option value="">Все / не назначен</option>{branches.data?.items.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><button className="primary small">Добавить пользователя</button></form><div className="table-wrap"><table><thead><tr><th>Сотрудник</th><th>Почта</th><th>Роль</th><th>Статус</th></tr></thead><tbody>{users.data?.items.map(x=><tr key={x.id}><td><strong>{x.full_name}</strong></td><td>{x.email}</td><td>{({owner:"Владелец",manager:"Управляющий",administrator:"Администратор",sales_manager:"Менеджер продаж"}as Record<string,string>)[x.role]}</td><td><span className={x.is_active?"badge active":"badge"}>{x.is_active?"Активен":"Отключён"}</span></td></tr>)}</tbody></table></div></section>}
