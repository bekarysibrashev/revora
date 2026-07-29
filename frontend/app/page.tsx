"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const whatsappHref =
  "https://wa.me/77774345295?text=Здравствуйте!%20Хочу%20узнать%20больше%20о%20Revora";

const capabilities = [
  {
    mark: "01",
    title: "Финансы без слепых зон",
    text: "ОПиУ, движение денег, расходы, остатки и кассовые разрывы — по каждому филиалу и всей сети.",
    tags: ["P&L", "Cash Flow", "Excel / PDF"],
  },
  {
    mark: "02",
    title: "Продажи и записи",
    text: "Весь путь пациента: от первого обращения до записи, визита и фактической оплаты.",
    tags: ["Воронка", "Конверсия", "No-show"],
  },
  {
    mark: "03",
    title: "Эффективность команды",
    text: "Нагрузка, завершённые приёмы, выручка, рейтинг и правила вознаграждения каждого врача.",
    tags: ["Врачи", "ФОТ", "План-факт"],
  },
  {
    mark: "04",
    title: "Маркетинг до выручки",
    text: "Расходы, лиды, кампании и ROAS в одной цепочке — чтобы видеть, какая реклама приносит деньги.",
    tags: ["Meta Ads", "Атрибуция", "ROAS"],
  },
  {
    mark: "05",
    title: "Карта потерь",
    text: "Revora находит лиды без ответа, неявки, просадки конверсии и другие точки возврата денег.",
    tags: ["AI-инсайты", "Алерты", "Приоритет"],
  },
  {
    mark: "06",
    title: "Контроль звонков",
    text: "AI оценивает качество разговора, соблюдение скрипта, работу с возражениями и следующий шаг.",
    tags: ["Kcell", "Скоринг", "Рекомендации"],
  },
  {
    mark: "07",
    title: "WhatsApp AI",
    text: "Безопасный помощник отвечает по базе знаний клиники, готовит черновики и передаёт диалог сотруднику.",
    tags: ["Cloud API", "База знаний", "Очередь"],
  },
  {
    mark: "08",
    title: "Контроль качества данных",
    text: "Система показывает свежесть и полноту источников, ошибки загрузки и происхождение каждой цифры.",
    tags: ["CSV / XLSX", "Lineage", "Дедупликация"],
  },
];

const future = [
  "Ежедневный AI-отчёт в Telegram к 08:00",
  "Прогноз выручки, лидов и других показателей",
  "Самостоятельный онбординг новых клиник",
  "Новые адаптеры МИС, банков и рекламных каналов",
  "Бенчмаркинг филиалов и клиник сети",
  "Мобильное приложение и white-label",
  "SSO / SCIM, DWH, on-premise и SLA",
  "Маркетплейс готовых интеграций",
];

export default function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const reveal = () => {
      document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((node) => {
        if (node.getBoundingClientRect().top < window.innerHeight - 80) {
          node.classList.add("is-visible");
        }
      });
    };
    reveal();
    window.addEventListener("scroll", reveal, { passive: true });
    return () => window.removeEventListener("scroll", reveal);
  }, []);

  return (
    <main className="landing">
      <header className="landing-nav">
        <a className="landing-logo" href="#top" aria-label="Revora — на главную">
          REVORA
        </a>
        <button
          className="landing-menu"
          type="button"
          aria-label="Открыть меню"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(!menuOpen)}
        >
          <span />
          <span />
        </button>
        <nav className={menuOpen ? "is-open" : ""} aria-label="Основная навигация">
          <a href="#product" onClick={() => setMenuOpen(false)}>Возможности</a>
          <a href="#how" onClick={() => setMenuOpen(false)}>Как работает</a>
          <a href="#roadmap" onClick={() => setMenuOpen(false)}>Roadmap</a>
          <a href="#contact" onClick={() => setMenuOpen(false)}>Контакты</a>
        </nav>
        <a className="nav-cta" href={whatsappHref} target="_blank" rel="noreferrer">
          Обсудить внедрение <span>↗</span>
        </a>
      </header>

      <section className="landing-hero" id="top">
        <div className="hero-copy" data-reveal>
          <p className="landing-kicker"><i /> AI-платформа для управления клиникой</p>
          <h1>
            Клиника под контролем.
            <span>Каждый день.</span>
          </h1>
          <p className="hero-lead">
            Revora собирает финансы, продажи, маркетинг и работу команды в одну
            систему — и показывает, где клиника зарабатывает, а где теряет деньги.
          </p>
          <div className="hero-actions">
            <a className="landing-primary" href={whatsappHref} target="_blank" rel="noreferrer">
              Получить консультацию <span>↗</span>
            </a>
            <a className="landing-secondary" href="#product">Посмотреть возможности ↓</a>
          </div>
          <div className="hero-trust">
            <span><b>01</b> Реальные цифры</span>
            <span><b>02</b> По каждому филиалу</span>
            <span><b>03</b> Без ручных сводок</span>
          </div>
        </div>

        <div className="hero-product" aria-label="Пример дашборда Revora" data-reveal>
          <div className="mock-window">
            <div className="mock-sidebar">
              <strong>REVORA</strong>
              {["Обзор", "Прибыль", "Продажи", "Врачи", "Маркетинг"].map((x, i) => (
                <span className={i === 0 ? "active" : ""} key={x}><i>{i + 1}</i>{x}</span>
              ))}
              <small>Данные подключены</small>
            </div>
            <div className="mock-main">
              <div className="mock-head">
                <div><small>ОБЗОР КЛИНИКИ</small><strong>Сегодня всё под контролем</strong></div>
                <span>Все филиалы⌄</span>
              </div>
              <div className="mock-metrics">
                <article><small>ВЫРУЧКА</small><strong>38,4 млн ₸</strong><b>↑ 12,8%</b></article>
                <article><small>ЧИСТАЯ ПРИБЫЛЬ</small><strong>9,7 млн ₸</strong><b>25,3% маржа</b></article>
                <article><small>КОНВЕРСИЯ</small><strong>42,6%</strong><b>↑ 4,1 п.п.</b></article>
              </div>
              <div className="mock-grid">
                <article className="mock-chart">
                  <header><strong>Динамика выручки</strong><small>30 дней</small></header>
                  <div className="chart-bars">
                    {[38, 54, 46, 67, 62, 78, 72, 91, 86, 100].map((h, i) => (
                      <i key={i} style={{ height: `${h}%` }} />
                    ))}
                  </div>
                  <div className="chart-labels"><span>01 июл</span><span>15 июл</span><span>29 июл</span></div>
                </article>
                <article className="mock-insights">
                  <header><strong>AI-инсайты</strong><b>3</b></header>
                  <div><i className="warn">!</i><span><strong>Возврат 680 000 ₸</strong><small>14 лидов ждут ответа</small></span></div>
                  <div><i>↑</i><span><strong>ROAS вырос</strong><small>Кампания «Имплантация»</small></span></div>
                  <div><i>✓</i><span><strong>План выполняется</strong><small>Филиал на Сейфуллина</small></span></div>
                </article>
              </div>
            </div>
          </div>
          <div className="floating-card">
            <span>ПОТЕНЦИАЛ ВОЗВРАТА</span>
            <strong>+2,1 млн ₸</strong>
            <small>Revora нашла 7 точек роста</small>
          </div>
        </div>
      </section>

      <section className="landing-proof" aria-label="Ключевые преимущества">
        <p>Одна управленческая картина вместо</p>
        <div><span>1С и МИС</span><i>+</i><span>банков</span><i>+</i><span>рекламных кабинетов</span><i>+</i><span>таблиц</span></div>
      </section>

      <section className="landing-section problem-section" id="product">
        <div className="section-heading" data-reveal>
          <div>
            <p className="landing-kicker">Возможности платформы</p>
            <h2>Всё важное — <em>в одной системе</em></h2>
          </div>
          <p>
            Revora превращает разрозненные данные клиники в понятные решения
            для собственника, управляющего, администратора и отдела продаж.
          </p>
        </div>
        <div className="capability-grid">
          {capabilities.map((item) => (
            <article key={item.mark} data-reveal>
              <div className="capability-top"><span>{item.mark}</span><i>↗</i></div>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
              <footer>{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</footer>
            </article>
          ))}
        </div>
      </section>

      <section className="intelligence-section">
        <div className="intelligence-copy" data-reveal>
          <p className="landing-kicker light"><i /> Не просто дашборд</p>
          <h2>Revora сама находит, <em>что требует внимания</em></h2>
          <p>
            Фоновые алгоритмы регулярно проверяют показатели и поднимают только
            важные сигналы: финансовые риски, потери лидов, просадки команды,
            аномалии расходов и рекламы.
          </p>
          <ul>
            <li><span>01</span>Цифры считает проверяемый код, а не языковая модель</li>
            <li><span>02</span>Каждый инсайт привязан к источнику данных</li>
            <li><span>03</span>Рекомендации отсортированы по влиянию на деньги</li>
          </ul>
        </div>
        <div className="insight-stack" data-reveal>
          <article>
            <div><span className="severity high">Высокий приоритет</span><small>сегодня, 09:40</small></div>
            <h3>Лиды остаются без ответа</h3>
            <p>14 новых обращений не получили звонка или записи в течение 24 часов.</p>
            <footer><span>Потенциал возврата</span><strong>680 000 ₸</strong></footer>
          </article>
          <article>
            <div><span className="severity">Точка роста</span><small>сегодня, 08:15</small></div>
            <h3>Конверсия филиала ниже средней</h3>
            <p>Разница с лучшим филиалом сети — 8,4 процентного пункта.</p>
            <footer><span>Рекомендация</span><strong>Проверить 12 звонков →</strong></footer>
          </article>
          <article>
            <div><span className="severity good">Положительная динамика</span><small>вчера</small></div>
            <h3>Кампания окупается лучше</h3>
            <p>ROAS направления «Имплантация» вырос до 5,8×.</p>
          </article>
        </div>
      </section>

      <section className="landing-section how-section" id="how">
        <div className="section-heading" data-reveal>
          <div>
            <p className="landing-kicker">Как это работает</p>
            <h2>От источников — <em>к решению</em></h2>
          </div>
          <p>Revora адаптируется к текущим системам клиники и сохраняет единую логику показателей.</p>
        </div>
        <div className="flow">
          <article data-reveal><span>01</span><i>↘</i><h3>Подключаем данные</h3><p>МИС / 1С, банки, Meta Ads, 2ГИС, Kcell, WhatsApp, CSV и XLSX.</p></article>
          <article data-reveal><span>02</span><i>↘</i><h3>Приводим к единой модели</h3><p>Проверяем, очищаем, убираем дубли и сохраняем происхождение данных.</p></article>
          <article data-reveal><span>03</span><i>✓</i><h3>Показываем действие</h3><p>Дашборды, отчёты, AI-инсайты и конкретные точки возврата денег.</p></article>
        </div>
        <div className="integration-band" data-reveal>
          {["1С / МИС", "KASPI", "HALYK", "META ADS", "2GIS", "KCELL", "WHATSAPP", "CSV / XLSX"].map((x) => <span key={x}>{x}</span>)}
        </div>
      </section>

      <section className="roles-section">
        <div data-reveal>
          <p className="landing-kicker light">Доступ по ролям и филиалам</p>
          <h2>Каждому — только <em>нужная картина</em></h2>
        </div>
        <div className="role-list">
          <article data-reveal><span>СОБСТВЕННИК</span><h3>Прибыль, деньги и точки роста</h3><p>Вся сеть и каждый филиал — в одной управленческой картине.</p></article>
          <article data-reveal><span>УПРАВЛЯЮЩИЙ</span><h3>Операционка и команда</h3><p>План-факт, качество данных, врачи, продажи и маркетинг.</p></article>
          <article data-reveal><span>АДМИНИСТРАТОР</span><h3>Записи и пациенты</h3><p>Лиды, неявки, WhatsApp-диалоги и задачи, требующие реакции.</p></article>
          <article data-reveal><span>ОТДЕЛ ПРОДАЖ</span><h3>Воронка и конверсия</h3><p>Новые обращения, причины потерь и следующий шаг по каждому лиду.</p></article>
        </div>
      </section>

      <section className="landing-section roadmap-section" id="roadmap">
        <div className="section-heading" data-reveal>
          <div>
            <p className="landing-kicker">Развитие Revora</p>
            <h2>Платформа растёт <em>вместе с клиникой</em></h2>
          </div>
          <p>Фундамент уже рассчитан на сети клиник, новые источники и корпоративные сценарии.</p>
        </div>
        <div className="roadmap-layout">
          <article className="roadmap-now" data-reveal>
            <span className="status-pill"><i /> Revora сегодня</span>
            <h3>Управленческий центр клиники</h3>
            <p>Финансы, продажи, команда, маркетинг, карта потерь, контроль звонков, WhatsApp AI и проверяемые AI-инсайты.</p>
            <div><b>V1</b><span>Готова к пилотному внедрению</span></div>
          </article>
          <div className="future-grid">
            {future.map((item, index) => (
              <div key={item} data-reveal><span>{String(index + 1).padStart(2, "0")}</span><p>{item}</p></div>
            ))}
          </div>
        </div>
      </section>

      <section className="contact-section" id="contact">
        <div className="contact-orbit" aria-hidden="true"><span>R</span></div>
        <div data-reveal>
          <p className="landing-kicker light">Следующий шаг</p>
          <h2>Давайте найдём, где ваша клиника <em>теряет деньги</em></h2>
          <p>Покажем Revora на ваших задачах, обсудим источники данных и соберём план внедрения.</p>
          <div className="contact-actions">
            <a className="contact-primary" href={whatsappHref} target="_blank" rel="noreferrer">
              Написать в WhatsApp <span>↗</span>
            </a>
            <a className="contact-phone" href="tel:+77774345295">+7 777 434 52 95</a>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <a className="landing-logo" href="#top">REVORA</a>
        <p>AI-платформа управленческой аналитики для клиник</p>
        <div><a href="tel:+77774345295">+7 777 434 52 95</a><a href={whatsappHref} target="_blank" rel="noreferrer">WhatsApp ↗</a></div>
        <small>© {new Date().getFullYear()} Revora</small>
        <Link href="/login">Вход в систему →</Link>
      </footer>
    </main>
  );
}
