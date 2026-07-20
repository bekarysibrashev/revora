// Дизайн-токены (цвет/типографика/отступы) из 05_frontend_revora.md, раздел 4
// заводятся здесь на шаге "frontend" (Этап 7). Сейчас — плейсхолдер конфига.
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./modules/**/*.{ts,tsx}", "./shared/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // TODO(Этап 7, шаг frontend): bg-canvas, bg-surface, border-subtle,
      // text-primary/secondary, accent-brand, signal-positive/negative
    },
  },
  plugins: [],
};
export default config;
