"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Role, useAuth } from "@/modules/auth";
import { api } from "@/shared/api-client";

type Branch = { id: string; name: string; code: string; is_active: boolean };
type DataQuality = {
  summary: { score: number; status: "good" | "warning" | "critical" };
  generated_at: string;
};
type NavItem = { href: string; label: string; mark: string; roles: Role[] };
type NavGroup = { label: string; mark: string; items: NavItem[] };

const coreItems: NavItem[] = [
  { href: "/dashboard", label: "Обзор", mark: "О", roles: ["owner", "manager", "administrator"] },
  { href: "/contacts", label: "Новые обращения", mark: "НО", roles: ["owner", "manager", "administrator"] },
  { href: "/sales", label: "Продажи", mark: "С", roles: ["owner", "manager", "administrator", "sales_manager"] },
  { href: "/doctors", label: "Врачи", mark: "В", roles: ["owner", "manager", "administrator"] },
  { href: "/marketing", label: "Маркетинг", mark: "М", roles: ["owner", "manager"] },
  { href: "/analyst", label: "ИИ-аналитик", mark: "AI", roles: ["owner", "manager", "administrator", "sales_manager"] },
];

const groups: NavGroup[] = [
  {
    label: "Финансы",
    mark: "₸",
    items: [
      { href: "/finance/pnl", label: "Прибыли и убытки", mark: "P&L", roles: ["owner", "manager"] },
      { href: "/finance/cashflow", label: "Движение денег", mark: "↕", roles: ["owner", "manager"] },
      { href: "/reports", label: "Отчёты", mark: "Р", roles: ["owner", "manager"] },
    ],
  },
  {
    label: "Коммуникации",
    mark: "К",
    items: [
      { href: "/whatsapp", label: "WhatsApp AI", mark: "WA", roles: ["owner", "manager", "administrator", "sales_manager"] },
      { href: "/ai", label: "Контроль звонков", mark: "✦", roles: ["owner"] },
    ],
  },
  {
    label: "Инструменты",
    mark: "⋯",
    items: [
      { href: "/analytics", label: "Контроль данных", mark: "К", roles: ["owner", "manager"] },
      { href: "/losses", label: "Карта потерь", mark: "₸", roles: ["owner", "manager", "administrator"] },
      { href: "/data-science", label: "ML-исследования", mark: "ML", roles: ["owner", "manager"] },
    ],
  },
];

const settingsItem: NavItem = {
  href: "/admin",
  label: "Настройки",
  mark: "Н",
  roles: ["owner"],
};
const allItems = [...coreItems, ...groups.flatMap((group) => group.items), settingsItem];

function NavLink({
  item,
  active,
  close,
}: {
  item: NavItem;
  active: boolean;
  close(): void;
}) {
  return (
    <Link href={item.href} onClick={close} className={active ? "active" : ""}>
      <span>{item.mark}</span>
      {item.label}
    </Link>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, ready, logout } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const search = useSearchParams();
  const [open, setOpen] = useState(false);
  const branches = useQuery({
    queryKey: ["branches"],
    queryFn: () => api<{ items: Branch[] }>("/admin/branches"),
    enabled: !!user && user.role !== "sales_manager",
  });
  const quality = useQuery({
    queryKey: ["topbar-data-quality", user?.role],
    queryFn: () => {
      const today = new Date();
      const start = new Date(today);
      start.setDate(start.getDate() - 29);
      const params = new URLSearchParams({
        date_from: start.toISOString().slice(0, 10),
        date_to: today.toISOString().slice(0, 10),
      });
      return api<DataQuality>(`/analytics/quality?${params.toString()}`);
    },
    enabled: user?.role === "owner" || user?.role === "manager",
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  const allowed = useMemo(
    () => allItems.filter((item) => user && item.roles.includes(user.role)),
    [user],
  );
  const visibleCore = coreItems.filter((item) => user && item.roles.includes(user.role));
  const visibleGroups = groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => user && item.roles.includes(user.role)),
    }))
    .filter((group) => group.items.length);
  const showSettings = !!user && settingsItem.roles.includes(user.role);

  useEffect(() => {
    if (user && allowed.length && !allowed.some((item) => path.startsWith(item.href))) {
      router.replace(allowed[0].href);
    }
  }, [user, allowed, path, router]);

  if (!ready || !user) {
    return <div className="center-state">Загружаем рабочее пространство…</div>;
  }

  function chooseBranch(value: string) {
    const params = new URLSearchParams(search.toString());
    value ? params.set("branch_id", value) : params.delete("branch_id");
    router.push(`${path}?${params.toString()}`);
  }

  return (
    <div className="app-shell">
      <aside className={open ? "sidebar open" : "sidebar"}>
        <div className="side-head">
          <Link href={allowed[0]?.href || "/sales"} className="brand">
            REVORA
          </Link>
          <button className="icon-button mobile-only" onClick={() => setOpen(false)}>
            ×
          </button>
        </div>
        <nav>
          <div className="nav-primary">
            {visibleCore.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                active={path.startsWith(item.href)}
                close={() => setOpen(false)}
              />
            ))}
          </div>
          <div className="nav-groups">
            {visibleGroups.map((group) => {
              const isActive = group.items.some((item) => path.startsWith(item.href));
              return (
                <details key={group.label} className="nav-group" open={isActive || undefined}>
                  <summary className={isActive ? "active" : ""}>
                    <span>{group.mark}</span>
                    {group.label}
                    <b>⌄</b>
                  </summary>
                  <div>
                    {group.items.map((item) => (
                      <NavLink
                        key={item.href}
                        item={item}
                        active={path.startsWith(item.href)}
                        close={() => setOpen(false)}
                      />
                    ))}
                  </div>
                </details>
              );
            })}
          </div>
          {showSettings && (
            <div className="nav-settings">
              <NavLink
                item={settingsItem}
                active={path.startsWith(settingsItem.href)}
                close={() => setOpen(false)}
              />
            </div>
          )}
        </nav>
        <div className="side-foot">
          <div className="avatar">{user.full_name.slice(0, 1).toUpperCase()}</div>
          <div>
            <strong>{user.full_name}</strong>
            <small>{roleLabel(user.role)}</small>
          </div>
          <button className="icon-button" title="Выйти" onClick={logout}>
            ↪
          </button>
        </div>
      </aside>
      {open && (
        <button className="backdrop" onClick={() => setOpen(false)} aria-label="Закрыть меню" />
      )}
      <section className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-only" onClick={() => setOpen(true)}>
            ☰
          </button>
          <div className="top-title">
            <strong>{allItems.find((item) => path.startsWith(item.href))?.label || "Revora"}</strong>
            <small>Управленческая аналитика</small>
          </div>
          {branches.data && branches.data.items.filter((branch) => branch.is_active).length > 1 && (
            <select
              aria-label="Филиал"
              value={search.get("branch_id") || ""}
              onChange={(event) => chooseBranch(event.target.value)}
            >
              <option value="">Все филиалы</option>
              {branches.data.items
                .filter(
                  (branch) =>
                    branch.is_active &&
                    (user.role !== "administrator" || user.branch_ids.includes(branch.id)),
                )
                .map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name}
                  </option>
                ))}
            </select>
          )}
          {(user.role === "owner" || user.role === "manager") ? (
            <Link
              href="/analytics"
              className={`status data-${quality.data?.summary.status || "loading"}`}
              title={quality.data ? `Качество данных: ${quality.data.summary.score}/100` : "Проверяем качество данных"}
            >
              <i />
              {quality.isLoading
                ? "Проверяем данные"
                : quality.isError
                  ? "Статус недоступен"
                  : quality.data?.summary.status === "good"
                    ? `Данные готовы · ${quality.data.summary.score}%`
                    : quality.data?.summary.status === "warning"
                      ? `Есть ограничения · ${quality.data.summary.score}%`
                      : `Нужны данные · ${quality.data?.summary.score || 0}%`}
            </Link>
          ) : (
            <span className="status"><i />Рабочее пространство</span>
          )}
        </header>
        <main className="content">{children}</main>
      </section>
    </div>
  );
}

function roleLabel(role: Role) {
  return {
    owner: "Владелец",
    manager: "Управляющий",
    administrator: "Администратор",
    sales_manager: "Менеджер продаж",
  }[role];
}
