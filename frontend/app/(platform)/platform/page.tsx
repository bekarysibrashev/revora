"use client";
// Служебная страница оператора платформы: создание новых клиник (тенантов).
// Намеренно ВНЕ /(app) — не использует useAuth()/AppLayout (те завязаны на
// per-tenant JWT конкретной клиники), не показана в боковой навигации.
// Доступ — отдельным статическим токеном (PLATFORM_ADMIN_TOKEN на backend),
// не связан с UserRole/RLS. См. backend/app/modules/tenancy/dependencies.py.
import { FormEvent, useEffect, useState } from "react";
import { PageHeader } from "@/shared/ui";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api/v1";
const TOKEN_KEY = "revora_platform_token";

type Tenant = { id: string; name: string; slug: string; is_active: boolean; created_at: string };
type CreateResult = { tenant: Tenant; owner_email: string; branch_code: string };

async function platformApi<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    let message = "Не удалось выполнить запрос";
    try {
      const body = await response.json();
      message = body.error?.message || message;
    } catch {}
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export default function PlatformPage() {
  const [token, setToken] = useState("");
  const [unlocked, setUnlocked] = useState(false);

  useEffect(() => {
    const saved = sessionStorage.getItem(TOKEN_KEY);
    if (saved) {
      setToken(saved);
      setUnlocked(true);
    }
  }, []);

  function unlock(e: FormEvent) {
    e.preventDefault();
    sessionStorage.setItem(TOKEN_KEY, token);
    setUnlocked(true);
  }

  function lock() {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setUnlocked(false);
  }

  if (!unlocked) {
    return (
      <main className="login-page">
        <section className="login-brand">
          <a className="brand" href="#">REVORA</a>
          <div>
            <p className="eyebrow">Служебный доступ</p>
            <h1>Управление клиниками платформы.</h1>
            <p>Здесь создаются новые клиники (тенанты) — это не рабочее пространство сотрудников клиник, а инструмент оператора платформы.</p>
          </div>
          <small>Требуется PLATFORM_ADMIN_TOKEN</small>
        </section>
        <section className="login-panel">
          <form className="login-card" onSubmit={unlock}>
            <div>
              <p className="eyebrow">Служебный вход</p>
              <h2>Токен платформы</h2>
              <p className="muted">Введите значение PLATFORM_ADMIN_TOKEN, заданное в переменных окружения backend.</p>
            </div>
            <label>Токен
              <input type="password" value={token} onChange={e => setToken(e.target.value)} required autoComplete="off" />
            </label>
            <button className="primary">Продолжить</button>
          </form>
        </section>
      </main>
    );
  }

  return <PlatformDashboard token={token} onLock={lock} />;
}

function PlatformDashboard({ token, onLock }: { token: string; onLock: () => void }) {
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CreateResult | null>(null);

  const [tenantName, setTenantName] = useState("");
  const [tenantSlug, setTenantSlug] = useState("");
  const [branchName, setBranchName] = useState("Главный филиал");
  const [branchCode, setBranchCode] = useState("main");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [ownerFullName, setOwnerFullName] = useState("");
  const [ownerPassword, setOwnerPassword] = useState("");

  async function loadTenants() {
    setLoadError("");
    try {
      const data = await platformApi<{ items: Tenant[]; total: number }>("/platform/tenants", token);
      setTenants(data.items);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Не удалось загрузить список клиник");
    }
  }

  useEffect(() => {
    loadTenants();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const data = await platformApi<CreateResult>("/platform/tenants", token, {
        method: "POST",
        body: JSON.stringify({
          tenant_name: tenantName,
          tenant_slug: tenantSlug,
          branch_name: branchName,
          branch_code: branchCode,
          owner_email: ownerEmail,
          owner_full_name: ownerFullName,
          owner_password: ownerPassword,
        }),
      });
      setResult(data);
      setTenantName("");
      setTenantSlug("");
      setOwnerEmail("");
      setOwnerFullName("");
      setOwnerPassword("");
      loadTenants();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать клинику");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", padding: "34px 24px 60px" }}>
      <PageHeader
        title="Клиники платформы"
        subtitle="Создание новых клиник (тенантов) и просмотр уже существующих"
        action={<button className="icon-button" title="Выйти из служебного режима" onClick={onLock}>↪ Выйти</button>}
      />

      <section className="panel">
        <h2>Новая клиника</h2>
        <form className="form-grid user-form" onSubmit={submit}>
          <label>Название клиники
            <input value={tenantName} onChange={e => setTenantName(e.target.value)} required />
          </label>
          <label>Код клиники (slug)
            <input value={tenantSlug} onChange={e => setTenantSlug(e.target.value.toLowerCase())} required pattern="[a-z0-9-]+" placeholder="например, dentaplus" />
          </label>
          <label>Филиал — название
            <input value={branchName} onChange={e => setBranchName(e.target.value)} required />
          </label>
          <label>Филиал — код
            <input value={branchCode} onChange={e => setBranchCode(e.target.value.toLowerCase())} required pattern="[a-z0-9-]+" />
          </label>
          <label>Почта владельца
            <input type="email" value={ownerEmail} onChange={e => setOwnerEmail(e.target.value)} required />
          </label>
          <label>Имя владельца
            <input value={ownerFullName} onChange={e => setOwnerFullName(e.target.value)} required />
          </label>
          <label>Пароль владельца
            <input type="password" minLength={8} value={ownerPassword} onChange={e => setOwnerPassword(e.target.value)} required />
          </label>
          <button className="primary small" disabled={busy}>{busy ? "Создаём…" : "Создать клинику"}</button>
        </form>
        {error && <div className="error-box">{error}</div>}
        {result && (
          <div className="success-box">
            Клиника «{result.tenant.name}» создана. Код клиники: <strong>{result.tenant.slug}</strong>, почта владельца: <strong>{result.owner_email}</strong>. Эти данные нужны для входа на экране /login (пароль нигде не сохраняется — сообщите его владельцу отдельно).
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Существующие клиники</h2>
        {loadError && (
          <div className="error-box">
            {loadError} — <a href="#" onClick={e => { e.preventDefault(); onLock(); }}>выйти и ввести токен заново</a>
          </div>
        )}
        <div className="table-wrap">
          <table>
            <thead><tr><th>Название</th><th>Код</th><th>Статус</th><th>Создана</th></tr></thead>
            <tbody>
              {tenants?.map(t => (
                <tr key={t.id}>
                  <td><strong>{t.name}</strong></td>
                  <td>{t.slug}</td>
                  <td><span className={t.is_active ? "badge active" : "badge"}>{t.is_active ? "Активна" : "Отключена"}</span></td>
                  <td>{new Date(t.created_at).toLocaleDateString("ru-RU")}</td>
                </tr>
              ))}
              {tenants && tenants.length === 0 && (
                <tr><td colSpan={4} className="empty">Пока нет ни одной клиники</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
