"""Точка входа FastAPI-приложения Revora."""

import argparse
from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.core.errors import AppError
from app.core.database import AsyncSessionFactory
from app.cli.create_initial_owner import ensure_initial_owner
from app.modules.admin.router import router as admin_router
from app.modules.analytics.router import router as analytics_router
from app.modules.auth.router import router as auth_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.ai.call_quality.router import router as call_quality_router
from app.modules.ai.call_quality.embedded_worker import EmbeddedCallWorker
from app.modules.ai.analyst.router import router as analyst_router
from app.modules.contacts.router import router as contacts_router
from app.modules.kcell.router import router as kcell_router
from app.modules.losses.router import router as losses_router
from app.modules.ml.router import router as ml_router
from app.modules.doctors.router import router as doctors_router
from app.modules.finance.router import router as finance_router
from app.modules.integrations.router import router as integrations_router
from app.modules.marketing.router import router as marketing_router
from app.modules.marketing.embedded_worker import EmbeddedMetaSyncWorker
from app.modules.sales.router import router as sales_router
from app.modules.reports.router import router as reports_router
from app.modules.tenancy.router import router as tenancy_router
from app.modules.telegram.router import router as telegram_router
from app.modules.whatsapp.router import router as whatsapp_router
from app.modules.whatsapp.router import webhook_router as whatsapp_webhook_router
from app.modules.whatsapp.router import qr_webhook_router as whatsapp_qr_webhook_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    call_worker = EmbeddedCallWorker(settings)
    meta_sync_worker = EmbeddedMetaSyncWorker(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting %s in %s", settings.app_name, settings.app_env)
        owner_email = settings.initial_owner_email.strip()
        owner_password = settings.initial_owner_password.get_secret_value()
        if owner_email and owner_password:
            created = await ensure_initial_owner(
                argparse.Namespace(
                    tenant_name=settings.initial_tenant_name,
                    tenant_slug=settings.initial_tenant_slug,
                    branch_name=settings.initial_branch_name,
                    branch_code=settings.initial_branch_code,
                    extra_branch_name=settings.initial_extra_branch_name,
                    extra_branch_code=settings.initial_extra_branch_code,
                    email=owner_email,
                    full_name=f"Владелец {settings.initial_tenant_name}",
                    password=owner_password,
                )
            )
            if created:
                logger.info(
                    "Initialized empty database for tenant %s",
                    settings.initial_tenant_slug,
                )
        elif settings.app_env == "production":
            logger.warning(
                "Initial owner credentials are missing; empty database bootstrap is disabled"
            )
        call_worker.start()
        meta_sync_worker.start()
        try:
            yield
        finally:
            await call_worker.stop()
            await meta_sync_worker.stop()
            logger.info("Stopping %s", settings.app_name)

    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        docs_url=f"{settings.api_v1_prefix}/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.add_middleware(RequestIdMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "UNAUTHORIZED" if exc.status_code == 401 else "HTTP_ERROR"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": str(exc.detail), "details": None}},
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(item) for item in error["loc"]), "message": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": details,
                }
            },
        )

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}

    @application.get("/ready", tags=["system"])
    async def ready() -> JSONResponse:
        """Verify the persistent dependency required by every business feature."""
        try:
            async with AsyncSessionFactory() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            logger.exception("Readiness database check failed")
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "database": "unavailable"},
            )
        return JSONResponse(content={"status": "ready", "database": "ready"})

    application.include_router(auth_router, prefix=settings.api_v1_prefix)
    application.include_router(tenancy_router, prefix=settings.api_v1_prefix)
    application.include_router(telegram_router, prefix=settings.api_v1_prefix)
    application.include_router(admin_router, prefix=settings.api_v1_prefix)
    application.include_router(analytics_router, prefix=settings.api_v1_prefix)
    application.include_router(integrations_router, prefix=settings.api_v1_prefix)
    application.include_router(finance_router, prefix=settings.api_v1_prefix)
    application.include_router(sales_router, prefix=settings.api_v1_prefix)
    application.include_router(reports_router, prefix=settings.api_v1_prefix)
    application.include_router(doctors_router, prefix=settings.api_v1_prefix)
    application.include_router(marketing_router, prefix=settings.api_v1_prefix)
    application.include_router(dashboard_router, prefix=settings.api_v1_prefix)
    application.include_router(call_quality_router, prefix=settings.api_v1_prefix)
    application.include_router(analyst_router, prefix=settings.api_v1_prefix)
    application.include_router(contacts_router, prefix=settings.api_v1_prefix)
    application.include_router(kcell_router, prefix=settings.api_v1_prefix)
    application.include_router(losses_router, prefix=settings.api_v1_prefix)
    application.include_router(ml_router, prefix=settings.api_v1_prefix)
    application.include_router(whatsapp_router, prefix=settings.api_v1_prefix)
    application.include_router(whatsapp_webhook_router, prefix=settings.api_v1_prefix)
    application.include_router(whatsapp_qr_webhook_router, prefix=settings.api_v1_prefix)

    return application


app = create_app()
