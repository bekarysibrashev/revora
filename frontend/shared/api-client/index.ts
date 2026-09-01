const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api/v1";

export const AUTH_EXPIRED_EVENT = "revora:auth-expired";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Session = {
  access_token: string;
  refresh_token: string;
};

let refreshInFlight: Promise<boolean> | null = null;

function session(): Session | null {
  if (typeof window === "undefined") return null;

  const raw = sessionStorage.getItem("revora_session");
  try {
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export const SESSION_EXPIRED_REASON_KEY = "revora_session_expired_reason";

function expireSession(reason?: string) {
  if (typeof window === "undefined") return;

  sessionStorage.removeItem("revora_session");
  sessionStorage.removeItem("revora_user");
  if (reason) sessionStorage.setItem(SESSION_EXPIRED_REASON_KEY, reason);
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

async function refresh(): Promise<boolean> {
  const current = session();
  if (!current?.refresh_token) return false;

  try {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: current.refresh_token }),
      cache: "no-store",
    });

    if (!response.ok) return false;

    const data = await response.json();
    sessionStorage.setItem("revora_session", JSON.stringify(data));
    sessionStorage.setItem("revora_user", JSON.stringify(data.user));
    return true;
  } catch {
    return false;
  }
}

async function recoverUnauthorized(): Promise<boolean> {
  refreshInFlight ||= refresh().finally(() => {
    refreshInFlight = null;
  });

  const refreshed = await refreshInFlight;
  if (!refreshed) expireSession();
  return refreshed;
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const current = session();
  const headers = new Headers(init.headers);
  const binaryBody =
    typeof Blob !== "undefined" && init.body instanceof Blob;

  if (!(init.body instanceof FormData) && !binaryBody) {
    headers.set("Content-Type", "application/json");
  }
  if (current?.access_token) {
    headers.set("Authorization", `Bearer ${current.access_token}`);
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (response.status === 401 && current) {
    if (retry && current.refresh_token && (await recoverUnauthorized())) {
      return api<T>(path, init, false);
    }
    expireSession("Сессия истекла. Войдите снова, чтобы продолжить.");
  }

  if (!response.ok) {
    let message = "Не удалось выполнить запрос";
    try {
      const body = await response.json();
      message = body.detail || body.error?.message || message;
    } catch {}
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

export async function apiBinary(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<Response> {
  const current = session();
  const headers = new Headers(init.headers);

  if (current?.access_token) {
    headers.set("Authorization", `Bearer ${current.access_token}`);
  }

  const response = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (response.status === 401 && current) {
    if (retry && current.refresh_token && (await recoverUnauthorized())) {
      return apiBinary(path, init, false);
    }
    expireSession("Сессия истекла. Войдите снова, чтобы продолжить.");
  }

  if (!response.ok) {
    throw new ApiError(response.status, "Не удалось получить файл");
  }
  return response;
}

export { API_URL };
