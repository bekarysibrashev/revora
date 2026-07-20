# Revora Backend

Асинхронный FastAPI-монолит с PostgreSQL, tenant RLS, Redis/Celery и модульными вертикальными срезами.

Основные API: `auth`, `admin`, `integrations`, `dashboard`, `finance`, `sales`, `doctors`, `marketing`. Универсальный ingestion сохраняет raw-слой, применяет версионируемый mapping, помещает неверные строки в карантин и записывает происхождение канонической записи.

## Локальная разработка

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

PostgreSQL и Redis должны соответствовать `DATABASE_URL` и `REDIS_URL`. Для полного локального запуска проще использовать корневой `docker-compose.yml`.

Первая учётная запись создаётся командой `python -m app.cli.create_initial_owner --help`. Тесты: `.\.venv\Scripts\python.exe -m pytest -q`.
