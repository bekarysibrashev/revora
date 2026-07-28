"use client";

import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  ApiError,
  AUTH_EXPIRED_EVENT,
} from "@/shared/api-client";

export type Role =
  | "owner"
  | "manager"
  | "administrator"
  | "sales_manager";

export type User = {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: Role;
  branch_ids: string[];
};

type LoginValues = {
  tenant_slug: string;
  email: string;
  password: string;
};

type AuthContextValue = {
  user: User | null;
  ready: boolean;
  login(v: LoginValues): Promise<void>;
  logout(): Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function clearStoredSession() {
  sessionStorage.removeItem("revora_session");
  sessionStorage.removeItem("revora_user");
}

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();

  useEffect(() => {
    const rawUser = sessionStorage.getItem("revora_user");
    const rawSession = sessionStorage.getItem("revora_session");

    try {
      setUser(rawUser && rawSession ? JSON.parse(rawUser) : null);
      if (!rawUser || !rawSession) clearStoredSession();
    } catch {
      clearStoredSession();
      setUser(null);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    function handleExpiredSession() {
      clearStoredSession();
      queryClient.clear();
      setUser(null);
      router.replace("/login");
    }

    window.addEventListener(AUTH_EXPIRED_EVENT, handleExpiredSession);
    return () =>
      window.removeEventListener(AUTH_EXPIRED_EVENT, handleExpiredSession);
  }, [queryClient, router]);

  async function login(values: LoginValues) {
    const data = await api<{
      access_token: string;
      refresh_token: string;
      user: User;
    }>("/auth/login", {
      method: "POST",
      body: JSON.stringify(values),
    });

    sessionStorage.setItem("revora_session", JSON.stringify(data));
    sessionStorage.setItem("revora_user", JSON.stringify(data.user));
    setUser(data.user);
    router.replace(
      data.user.role === "sales_manager" ? "/sales" : "/dashboard",
    );
  }

  async function logout() {
    const raw = sessionStorage.getItem("revora_session");
    try {
      const token = raw && JSON.parse(raw).refresh_token;
      if (token) {
        await api("/auth/logout", {
          method: "POST",
          body: JSON.stringify({ refresh_token: token }),
        });
      }
    } catch {}

    clearStoredSession();
    queryClient.clear();
    setUser(null);
    router.replace("/login");
  }

  return (
    <AuthContext.Provider value={{ user, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: (failureCount, error) =>
              !(error instanceof ApiError && error.status === 401) &&
              failureCount < 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider missing");
  return value;
}
