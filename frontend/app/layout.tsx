import type { Metadata } from "next";
import "@/styles/globals.css";
import { AppProviders } from "@/modules/auth";
import { Suspense } from "react";

export const metadata: Metadata = {
  metadataBase: new URL("https://revora.kz"),
  title: "Revora — AI-платформа управления клиникой",
  description:
    "Финансы, продажи, маркетинг, команда и AI-инсайты клиники в одной системе. Найдите потери и принимайте решения на реальных данных.",
  keywords: [
    "аналитика клиники",
    "управление стоматологией",
    "BI для клиник",
    "Revora",
    "AI аналитика",
  ],
  openGraph: {
    title: "Revora — клиника под контролем. Каждый день.",
    description:
      "Единая управленческая аналитика для собственников и управляющих клиник.",
    type: "website",
    locale: "ru_KZ",
    images: [{ url: "/og.png", width: 1733, height: 909, alt: "Revora — клиника под контролем" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Revora — клиника под контролем. Каждый день.",
    description: "Финансы, продажи, маркетинг и AI-инсайты в одной системе.",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ru"><body><AppProviders><Suspense fallback={<div className="center-state">Загружаем Revora…</div>}>{children}</Suspense></AppProviders></body></html>;
}
