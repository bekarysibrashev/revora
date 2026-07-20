"""Точка входа FastAPI-приложения Revora."""

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.core.errors import AppError
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.doctors.router import router as doctors_router
from app.modules.finance.router import router as finance_router
from app.modules.integrations.router import router as integrations_router
from app.modules.marketing.router import router as marketing_router
from app.modules.sales.router import router as sales_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting %s in %s", settings.app_name, settings.app_env)
        yield
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

    application.include_router(auth_router, prefix=settings.api_v1_prefix)
    application.include_router(admin_router, prefix=settings.api_v1_prefix)
    application.include_router(integrations_router, prefix=settings.api_v1_prefix)
    application.include_router(finance_router, prefix=settings.api_v1_prefix)
    application.include_router(sales_router, prefix=settings.api_v1_prefix)
    application.include_router(doctors_router, prefix=settings.api_v1_prefix)
    application.include_router(marketing_router, prefix=settings.api_v1_prefix)
    application.include_router(dashboard_router, prefix=settings.api_v1_prefix)

    return application


app = create_app()
