"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Role, useAuth } from "@/modules/auth";
import { api } from "@/shared/api-client";

type Branch = { id: string; name: string; code: string; is_active: boolean };
const items: { href: string; label: string; mark: string; roles: Role[] }[] = [
  { href: "/dashboard", label: "Обзор", mark: "О", roles: ["owner", "manager", "administrator"] },
  { href: "/finance/pnl", label: "Прибыли и убытки", mark: "₸", roles: ["owner", "manager"] },
  { href: "/finance/cashflow", label: "Движение денег", mark: "↕", roles: ["owner", "manager"] },
  { href: "/sales", label: "Продажи", mark: "С", roles: ["owner", "manager", "administrator", "sales_manager"] },
  { href: "/doctors", label: "Врачи", mark: "В", roles: ["owner", "manager", "administrator"] },
  { href: "/marketing", label: "Маркетинг", mark: "М", roles: ["owner", "manager"] },
  { href: "/reports", label: "Отчёты", mark: "Р", roles: ["owner", "manager"] },
  { href: "/ai", label: "AI-аналитик", mark: "✦", roles: ["owner", "manager"] },
  { href: "/admin", label: "Настройки", mark: "Н", roles: ["owner"] },
];
export default function AppLayout({ children }: { children: React.ReactNode }) { const { user, ready, logout } = useAuth(); const router = useRouter(); const path = usePathname(); const search = useSearchParams(); const [open, setOpen] = useState(false); const branches = useQuery({ queryKey: ["branches"], queryFn: () => api<{items: Branch[]}>("/admin/branches"), enabled: !!user && user.role !== "sales_manager" }); useEffect(() => { if (ready && !user) router.replace("/login"); }, [ready, user, router]); const allowed = useMemo(() => items.filter(i => user && i.roles.includes(user.role)), [user]); useEffect(() => { if (user && allowed.length && !allowed.some(i => path.startsWith(i.href))) router.replace(allowed[0].href); }, [user, allowed, path, router]); if (!ready || !user) return <div className="center-state">Загружаем рабочее пространство…</div>; function chooseBranch(value: string) { const p = new URLSearchParams(search.toString()); value ? p.set("branch_id", value) : p.delete("branch_id"); router.push(`${path}?${p.toString()}`); } return <div className="app-shell"><aside className={open ? "sidebar open" : "sidebar"}><div className="side-head"><Link href={allowed[0]?.href || "/sales"} className="brand">REVORA</Link><button className="icon-button mobile-only" onClick={() => setOpen(false)}>×</button></div><nav>{allowed.map(i => <Link key={i.href} href={i.href} onClick={() => setOpen(false)} className={path.startsWith(i.href) ? "active" : ""}><span>{i.mark}</span>{i.label}</Link>)}</nav><div className="side-foot"><div className="avatar">{user.full_name.slice(0, 1).toUpperCase()}</div><div><strong>{user.full_name}</strong><small>{roleLabel(user.role)}</small></div><button className="icon-button" title="Выйти" onClick={logout}>↪</button></div></aside>{open && <button className="backdrop" onClick={() => setOpen(false)} aria-label="Закрыть меню" />}<section className="workspace"><header className="topbar"><button className="icon-button mobile-only" onClick={() => setOpen(true)}>☰</button><div className="top-title"><strong>{items.find(i => path.startsWith(i.href))?.label || "Revora"}</strong><small>Управленческая аналитика</small></div>{branches.data && branches.data.items.filter(b => b.is_active).length > 1 && <select aria-label="Филиал" value={search.get("branch_id") || ""} onChange={e => chooseBranch(e.target.value)}><option value="">Все филиалы</option>{branches.data.items.filter(b => b.is_active && (user.role !== "administrator" || user.branch_ids.includes(b.id))).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}<span className="status"><i />Данные подключены</span></header><main className="content">{children}</main></section></div>; }
function roleLabel(role: Role) { return ({ owner: "Владелец", manager: "Управляющий", administrator: "Администратор", sales_manager: "Менеджер продаж" })[role]; }
