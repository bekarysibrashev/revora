import type { Metadata } from "next";
import "@/styles/globals.css";
import { AppProviders } from "@/modules/auth";
import { Suspense } from "react";

export const metadata: Metadata = { title: "Revora — аналитика клиники", description: "Единая управленческая аналитика для клиник" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ru"><body><AppProviders><Suspense fallback={<div className="center-state">Загружаем Revora…</div>}>{children}</Suspense></AppProviders></body></html>;
}
