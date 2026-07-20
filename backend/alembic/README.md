# Revora database migrations

Run from `backend/` with `DATABASE_URL` configured:

```bash
alembic upgrade head
alembic current
alembic downgrade -1
```

Never edit an applied revision. Create the next change with
`alembic revision --autogenerate -m "description"` and review the generated SQL.
