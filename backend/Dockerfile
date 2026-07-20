FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system revora && adduser --system --ingroup revora revora

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS development
COPY --chown=revora:revora . .
USER revora
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
COPY --chown=revora:revora . .
USER revora
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
