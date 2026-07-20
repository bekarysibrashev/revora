# Revora V1

Revora — мультиклиентская платформа управленческой аналитики для клиник. SAN Dental является первым пилотом, но архитектура, роли, загрузка данных и изоляция tenant-данных рассчитаны на разные клиники.

## Что готово в V1

- вход по клинике, JWT-сессия, обновление токена и четыре роли;
- филиалы и пользователи с ограничением доступа;
- загрузка CSV/XLSX, неизменяемые сырые строки, дедупликация, карантин ошибок и lineage;
- версионируемые правила преобразования любых колонок клиники в единую каноническую модель;
- пациенты, лиды, записи, врачи, выручка, расходы, остатки и маркетинг;
- Dashboard, P&L, Cash Flow, продажи, врачи и маркетинг с периодом и филиалом;
- экспорт P&L и Cash Flow в Excel/PDF;
- ежедневные автоматические инсайты: убыток, конверсия, неявки, ROAS и риск кассового разрыва;
- адаптивный интерфейс на Next.js.

AI-чат и Telegram-рассылка намеренно относятся к следующей версии. Раздел AI в V1 показывает этот статус, а автоматические инсайты уже работают.

## Запуск через Docker

Требуются Docker Desktop и Docker Compose.

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

Миграции выполняются автоматически при старте backend. Затем создайте первую клинику и владельца:

```powershell
docker compose exec backend python -m app.cli.create_initial_owner --tenant-name "Demo Clinic" --tenant-slug demo --branch-name "Главный филиал" --branch-code main --email owner@example.com --full-name "Владелец клиники" --password "ChangeMe123!"
```

Откройте `http://localhost:8080` и войдите с кодом клиники `demo`, почтой и паролем из команды.

Полезные адреса:

- приложение: `http://localhost:8080`;
- OpenAPI: `http://localhost:8080/api/v1/docs`;
- health-check: `http://localhost:8080/health`;
- Flower: `docker compose --profile dev up -d flower`, затем `http://localhost:5555`.

Остановка без удаления данных: `docker compose down`. Том PostgreSQL удаляется только явной командой `docker compose down -v`.

## Проверки

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
```

Архитектура и продуктовые решения находятся в [docs/00_master_kontekst_revora.md](docs/00_master_kontekst_revora.md).
