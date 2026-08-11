"use client";

import { PageHeader } from "@/shared/ui";

export default function DataSciencePage() {
  return <>
    <PageHeader
      title="Data Science Lab"
      subtitle="Прогнозы и ML-модели для клиники"
    />
    <section className="panel ds-coming-soon">
      <div className="coming-orbit" aria-hidden="true"><span>DS</span></div>
      <p className="eyebrow">Следующий этап Revora</p>
      <h2>Модуль в разработке</h2>
      <p>Для честного обучения моделей необходимы данные пациентов, записей, врачей и результатов лечения из 1С. Пока Revora не будет строить прогнозы на неполной выборке.</p>
      <div className="coming-roadmap">
        <span><b>01</b> Прогноз неявок</span>
        <span><b>02</b> Риск потери пациента</span>
        <span><b>03</b> Прогноз загрузки врачей</span>
      </div>
    </section>
  </>;
}
