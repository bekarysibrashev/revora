"use client";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { api } from "@/shared/api-client";
import { PageHeader } from "@/shared/ui";

type Source={tool:string;label:string;date_from:string;date_to:string;branch_id:string|null;data_as_of:string|null};
type Message={id:string;role:"user"|"assistant";content:string;sources:Source[];tool_calls:string[];model:string|null;created_at:string};
type Session={id:string;title:string;branch_id:string|null;last_message_at:string|null;created_at:string};
type Turn={user_message:Message;assistant_message:Message};
const suggestions=["Почему изменилась прибыль за последние 30 дней?","Как сейчас работает воронка продаж?","Какие врачи показывают лучший результат?","Окупается ли маркетинг?"];

export default function AnalystPage(){
  const client=useQueryClient(),search=useSearchParams(),bottom=useRef<HTMLDivElement>(null);
  const [active,setActive]=useState<string|null>(null),[text,setText]=useState(""),[error,setError]=useState("");
  const sessions=useQuery({queryKey:["analyst-sessions"],queryFn:()=>api<{items:Session[]}>("/ai/analyst/sessions")});
  const messages=useQuery({queryKey:["analyst-messages",active],queryFn:()=>api<{items:Message[]}>(`/ai/analyst/sessions/${active}/messages`),enabled:!!active});
  useEffect(()=>{if(!active&&sessions.data?.items.length)setActive(sessions.data.items[0].id)},[active,sessions.data]);
  useEffect(()=>{bottom.current?.scrollIntoView({behavior:"smooth"})},[messages.data]);
  const create=useMutation({mutationFn:()=>api<Session>("/ai/analyst/sessions",{method:"POST",body:JSON.stringify({title:"Новый анализ",branch_id:search.get("branch_id")||null})}),onSuccess:item=>{client.invalidateQueries({queryKey:["analyst-sessions"]});setActive(item.id);setText("")},onError:e=>setError(e instanceof Error?e.message:"Не удалось создать диалог")});
  const send=useMutation({mutationFn:({sessionId,content}:{sessionId:string;content:string})=>api<Turn>(`/ai/analyst/sessions/${sessionId}/messages`,{method:"POST",body:JSON.stringify({content})}),onSuccess:()=>{setText("");setError("");client.invalidateQueries({queryKey:["analyst-messages",active]});client.invalidateQueries({queryKey:["analyst-sessions"]})},onError:e=>setError(e instanceof Error?e.message:"AI-аналитик временно недоступен")});
  async function submit(e:FormEvent){e.preventDefault();const content=text.trim();if(!content||send.isPending)return;let sessionId=active;if(!sessionId){try{const item=await api<Session>("/ai/analyst/sessions",{method:"POST",body:JSON.stringify({title:content.slice(0,80),branch_id:search.get("branch_id")||null})});sessionId=item.id;setActive(item.id)}catch(e){setError(e instanceof Error?e.message:"Не удалось создать диалог");return}}send.mutate({sessionId,content})}
  function chooseSuggestion(value:string){setText(value)}
  return <><PageHeader title="ИИ-аналитик" subtitle="Задавайте вопросы по 1С, продажам, финансам, врачам и маркетингу — ответы строятся только по проверяемым данным Revora" action={<button className="primary" onClick={()=>create.mutate()} disabled={create.isPending}>{create.isPending?<><span className="spinner" aria-hidden="true"/>Создаём…</>:"Новый анализ"}</button>}/>
    <div className="analyst-layout"><aside className="analyst-sessions"><div className="analyst-side-title"><strong>История</strong><span>{sessions.data?.items.length||0}</span></div>{sessions.isLoading&&<div className="skeleton-block"><div className="skeleton skeleton-line" /><div className="skeleton skeleton-line medium" /></div>}{sessions.data?.items.map(item=><button key={item.id} className={active===item.id?"active":""} onClick={()=>setActive(item.id)}><strong>{item.title}</strong><small>{new Date(item.last_message_at||item.created_at).toLocaleDateString("ru-RU")}</small></button>)}{!sessions.isLoading&&!sessions.data?.items.length&&<p>Диалогов пока нет</p>}</aside>
      <section className="analyst-chat"><header><div className="analyst-mark">AI</div><div><strong>Revora AI</strong><small><i/>Только агрегированные данные</small></div></header><div className="analyst-messages">
        {!active&&!messages.data?.items.length&&<div className="analyst-welcome"><div className="analyst-orbit">AI</div><h2>Что вы хотите узнать о клинике?</h2><p>Я обращусь только к разрешённым показателям вашей роли и покажу период и актуальность источников.</p><div className="analyst-suggestions">{suggestions.map(item=><button key={item} onClick={()=>chooseSuggestion(item)}>{item}</button>)}</div></div>}
        {active&&messages.isLoading&&<div className="center-state"><span className="loading-dots" aria-hidden="true"><i/><i/><i/></span>Загружаем диалог…</div>}
        {messages.data?.items.map(item=><article key={item.id} className={`analyst-message ${item.role}`}><div className="analyst-message-label">{item.role==="user"?"Вы":"Revora AI"}</div><div className="analyst-bubble">{item.content}</div>{item.sources.length>0&&<div className="analyst-sources"><strong>Источники ответа</strong>{item.sources.map((source,index)=><div key={`${source.tool}-${index}`}><span>{source.label}</span><small>{new Date(source.date_from).toLocaleDateString("ru-RU")} — {new Date(source.date_to).toLocaleDateString("ru-RU")} · данные на {source.data_as_of?new Date(source.data_as_of).toLocaleString("ru-RU"):"не указано"}</small></div>)}</div>}</article>)}
        {send.isPending&&<article className="analyst-message assistant"><div className="analyst-message-label">Revora AI</div><div className="analyst-thinking"><i/><i/><i/><span>Проверяю показатели…</span></div></article>}<div ref={bottom}/>
      </div><form className="analyst-composer" onSubmit={submit}>{error&&<div className="error-box">{error}</div>}<div><textarea value={text} onChange={e=>setText(e.target.value)} placeholder="Например: почему снизилась прибыль в этом месяце?" maxLength={4000} rows={2} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();e.currentTarget.form?.requestSubmit()}}}/><button className="primary" disabled={!text.trim()||send.isPending}>Отправить</button></div><small>AI может ошибаться в объяснениях. Цифры сверяются с аналитическими инструментами Revora.</small></form></section></div></>;
}
