"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/modules/auth";

export default function LoginPage() {
  const { login, user, ready } = useAuth();
  const router = useRouter();
  const [tenant, setTenant] = useState("demo");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && user) {
      router.replace(user.role === "sales_manager" ? "/sales" : "/dashboard");
    }
  }, [ready, user, router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login({ tenant_slug: tenant, email, password });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Ошибка входа");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-brand">
        <span className="brand">REVORA</span>
        <div>
          <p className="eyebrow">Управление клиникой на основе данных</p>
          <h1>Вся картина бизнеса — в одном месте.</h1>
          <p>Финансы, продажи, врачи и маркетинг собраны в единую понятную систему.</p>
        </div>
        <small>Защищённое рабочее пространство</small>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <div>
            <p className="eyebrow">Добро пожаловать</p>
            <h2>Войти в Revora</h2>
            <p className="muted">Введите данные, выданные администратором клиники.</p>
          </div>
          <label>
            Код клиники
            <input value={tenant} onChange={(event) => setTenant(event.target.value)} required minLength={2} autoComplete="organization" />
          </label>
          <label>
            Рабочая почта
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required autoComplete="email" />
          </label>
          <label>
            Пароль
            <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required minLength={8} autoComplete="current-password" />
          </label>
          {error && <div className="error-box">{error}</div>}
          <button className="primary" disabled={busy}>{busy ? "Входим…" : "Войти"}</button>
          <small className="login-security-note">После 5 неверных паролей вход блокируется на 15 минут.</small>
        </form>
      </section>
    </main>
  );
}
