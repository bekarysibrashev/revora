import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import unquote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.errors import AppError
from app.modules.auth.dependencies import CurrentUser
from app.modules.tenancy.models import Tenant
from app.modules.whatsapp.schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    EmbeddedSignupCompleteRequest,
    HumanMessageRequest,
    KnowledgeCreateRequest,
    KnowledgeImportResponse,
    KnowledgeItemResponse,
    KnowledgeListResponse,
    KnowledgeUpdateRequest,
    MessageItem,
    SimulatorMessageRequest,
    SimulatorMessageResponse,
    WhatsAppStatusResponse,
    WhatsAppChannelResponse,
    WhatsAppQrEventPayload,
    WhatsAppQrSessionPayload,
    WhatsAppQrStatusResponse,
)
from app.modules.whatsapp.models import WhatsAppQrSession
from app.modules.whatsapp.security import (
    WhatsAppDataProtectionError,
    decrypt_contact,
    encrypt_contact,
    valid_meta_signature,
)
from app.modules.whatsapp.service import WhatsAppService

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
webhook_router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhook"])
qr_webhook_router = APIRouter(
    prefix="/webhooks/whatsapp-qr", tags=["whatsapp-qr-webhook"]
)
Session = Annotated[AsyncSession, Depends(get_db_session)]
RuntimeSettings = Annotated[Settings, Depends(get_settings)]


def _meta_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return None


def _message_body(message: dict[str, Any]) -> str | None:
    message_type = str(message.get("type") or "unknown")
    content = message.get(message_type)
    if isinstance(content, dict):
        body = content.get("body") or content.get("caption")
        if body:
            return str(body).strip()
    if message_type in {"revoke", "unsupported"}:
        return None
    return f"[{message_type}]"


def _require_qr_gateway(request: Request, settings: Settings) -> None:
    expected = settings.whatsapp_qr_gateway_secret.get_secret_value()
    supplied = request.headers.get("x-gateway-secret", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise AppError("WHATSAPP_QR_GATEWAY_UNAUTHORIZED", "Invalid gateway secret", 401)


async def _qr_tenant(session: AsyncSession, settings: Settings) -> Tenant:
    tenant = await session.scalar(
        select(Tenant).where(
            Tenant.slug == settings.whatsapp_tenant_slug,
            Tenant.is_active.is_(True),
        )
    )
    if tenant is None:
        raise AppError("WHATSAPP_TENANT_NOT_FOUND", "WhatsApp tenant is not configured", 503)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant.id)},
    )
    return tenant


@router.get("/status", response_model=WhatsAppStatusResponse)
async def status(
    user: CurrentUser, session: Session, settings: RuntimeSettings
) -> WhatsAppStatusResponse:
    return await WhatsAppService(session, settings).status(user)


async def _qr_gateway_request(
    settings: Settings, method: str, path: str
) -> WhatsAppQrStatusResponse:
    url = settings.whatsapp_qr_gateway_url.rstrip("/")
    secret = settings.whatsapp_qr_gateway_secret.get_secret_value()
    if not url or not secret:
        return WhatsAppQrStatusResponse(
            configured=False,
            state="not_configured",
            connected=False,
            message="QR-шлюз ещё не развернут",
        )
    try:
        # Render's free web services can sleep. Waking the QR gateway can take
        # 50+ seconds, so the proxy must outwait the cold-start instead of
        # turning a successful wake-up into a misleading "nothing happened".
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.request(
                method,
                f"{url}{path}",
                headers={"X-Gateway-Secret": secret},
            )
        response.raise_for_status()
        return WhatsAppQrStatusResponse(configured=True, **response.json())
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise AppError(
            "WHATSAPP_QR_GATEWAY_UNAVAILABLE",
            "QR-шлюз WhatsApp пока недоступен",
            503,
        ) from exc


@router.get("/qr/status", response_model=WhatsAppQrStatusResponse)
async def qr_status(
    user: CurrentUser, settings: RuntimeSettings
) -> WhatsAppQrStatusResponse:
    if user.role.value != "owner":
        raise AppError("FORBIDDEN", "Only the owner can connect WhatsApp", 403)
    return await _qr_gateway_request(settings, "GET", "/status")


@router.post("/qr/connect", response_model=WhatsAppQrStatusResponse)
async def qr_connect(
    user: CurrentUser, settings: RuntimeSettings
) -> WhatsAppQrStatusResponse:
    if user.role.value != "owner":
        raise AppError("FORBIDDEN", "Only the owner can connect WhatsApp", 403)
    return await _qr_gateway_request(settings, "POST", "/connect")


@router.post(
    "/embedded-signup/complete",
    response_model=WhatsAppChannelResponse,
)
async def complete_embedded_signup(
    payload: EmbeddedSignupCompleteRequest,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> WhatsAppChannelResponse:
    return await WhatsAppService(session, settings).complete_embedded_signup(
        user,
        code=payload.code,
        waba_id=payload.waba_id,
        phone_number_id=payload.phone_number_id,
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def conversations(
    user: CurrentUser, session: Session, settings: RuntimeSettings
) -> ConversationListResponse:
    return await WhatsAppService(session, settings).conversations(user)


@router.get(
    "/conversations/{conversation_id}", response_model=ConversationDetailResponse
)
async def conversation(
    conversation_id: UUID,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> ConversationDetailResponse:
    return await WhatsAppService(session, settings).conversation(user, conversation_id)


@router.post("/simulator/messages", response_model=SimulatorMessageResponse)
async def simulator_message(
    payload: SimulatorMessageRequest,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> SimulatorMessageResponse:
    return await WhatsAppService(session, settings).simulate(
        user, payload.message, payload.contact_id
    )


@router.post(
    "/conversations/{conversation_id}/takeover",
    response_model=ConversationDetailResponse,
)
async def takeover(
    conversation_id: UUID,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> ConversationDetailResponse:
    return await WhatsAppService(session, settings).takeover(user, conversation_id)


@router.post(
    "/conversations/{conversation_id}/release",
    response_model=ConversationDetailResponse,
)
async def release(
    conversation_id: UUID,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> ConversationDetailResponse:
    return await WhatsAppService(session, settings).release(user, conversation_id)


@router.post(
    "/conversations/{conversation_id}/messages", response_model=MessageItem
)
async def human_message(
    conversation_id: UUID,
    payload: HumanMessageRequest,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> MessageItem:
    return await WhatsAppService(session, settings).send_human(
        user, conversation_id, payload.message
    )


@router.get("/knowledge", response_model=KnowledgeListResponse)
async def knowledge(
    user: CurrentUser, session: Session, settings: RuntimeSettings
) -> KnowledgeListResponse:
    return await WhatsAppService(session, settings).knowledge(user)


@router.post("/knowledge", response_model=KnowledgeItemResponse)
async def create_knowledge(
    payload: KnowledgeCreateRequest,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> KnowledgeItemResponse:
    return await WhatsAppService(session, settings).create_knowledge(user, payload)


@router.post("/knowledge/import", response_model=KnowledgeImportResponse)
async def import_knowledge(
    request: Request,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> KnowledgeImportResponse:
    if request.headers.get("content-type", "").split(";", 1)[0] not in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    }:
        raise AppError("KNOWLEDGE_FILE_TYPE", "Upload an XLSX workbook", 415)
    filename = Path(
        unquote(request.headers.get("x-filename", "knowledge.xlsx"))
    ).name[:200]
    data = await request.body()
    return await WhatsAppService(session, settings).import_knowledge(
        user, data, filename
    )


@router.patch(
    "/knowledge/{item_id}", response_model=KnowledgeItemResponse
)
async def approve_knowledge(
    item_id: UUID,
    payload: KnowledgeUpdateRequest,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> KnowledgeItemResponse:
    return await WhatsAppService(session, settings).update_knowledge(
        user, item_id, payload
    )


@webhook_router.get("")
async def verify_webhook(
    settings: RuntimeSettings,
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> PlainTextResponse:
    expected = settings.whatsapp_verify_token.get_secret_value()
    if (
        mode != "subscribe"
        or not expected
        or token is None
        or not hmac.compare_digest(token, expected)
        or challenge is None
    ):
        raise AppError("WHATSAPP_WEBHOOK_VERIFICATION_FAILED", "Webhook verification failed", 403)
    return PlainTextResponse(challenge)


@webhook_router.post("")
async def receive_webhook(
    request: Request, session: Session, settings: RuntimeSettings
) -> dict[str, str]:
    raw = await request.body()
    if not valid_meta_signature(
        raw,
        request.headers.get("x-hub-signature-256", ""),
        settings.whatsapp_app_secret.get_secret_value(),
    ):
        raise AppError("WHATSAPP_SIGNATURE_INVALID", "Invalid Meta signature", 401)
    payload = await request.json()
    tenant = await session.scalar(
        select(Tenant).where(
            Tenant.slug == settings.whatsapp_tenant_slug,
            Tenant.is_active.is_(True),
        )
    )
    if tenant is None:
        raise AppError("WHATSAPP_TENANT_NOT_FOUND", "WhatsApp tenant is not configured", 503)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant.id)},
    )
    service = WhatsAppService(session, settings)
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "")
            if not phone_number_id:
                continue
            channel = await service.ensure_webhook_channel(
                tenant.id,
                phone_number_id,
                str(metadata.get("display_phone_number") or phone_number_id),
            )
            channel.last_webhook_at = datetime.now(UTC)
            for message in value.get("messages") or []:
                if message.get("type") != "text":
                    continue
                contact_id = str(message.get("from") or "").strip()
                external_message_id = str(message.get("id") or "").strip()
                body = str((message.get("text") or {}).get("body") or "").strip()
                if not contact_id or not external_message_id or not body:
                    continue
                await service.process_incoming(
                    tenant_id=tenant.id,
                    channel=channel,
                    contact_id=contact_id,
                    external_message_id=external_message_id,
                    body=body,
                    simulated=False,
                    provider_timestamp=_meta_timestamp(message.get("timestamp")),
                )
            for echo in value.get("message_echoes") or []:
                contact_id = str(echo.get("to") or "").strip()
                external_message_id = str(echo.get("id") or "").strip()
                if not contact_id or not external_message_id:
                    continue
                await service.store_synced_message(
                    tenant_id=tenant.id,
                    channel=channel,
                    contact_id=contact_id,
                    external_message_id=external_message_id,
                    direction="out",
                    message_type=str(echo.get("type") or "unknown"),
                    body=_message_body(echo),
                    provider_timestamp=_meta_timestamp(echo.get("timestamp")),
                    status="echoed",
                )
            for history_chunk in value.get("history") or []:
                for thread in history_chunk.get("threads") or []:
                    contact_id = str(thread.get("id") or "").strip()
                    if not contact_id:
                        continue
                    for message in thread.get("messages") or []:
                        external_message_id = str(message.get("id") or "").strip()
                        if not external_message_id:
                            continue
                        direction = (
                            "in"
                            if str(message.get("from") or "").strip() == contact_id
                            else "out"
                        )
                        history_status = str(
                            (message.get("history_context") or {}).get("status")
                            or "synced"
                        ).lower()
                        await service.store_synced_message(
                            tenant_id=tenant.id,
                            channel=channel,
                            contact_id=contact_id,
                            external_message_id=external_message_id,
                            direction=direction,
                            message_type=str(message.get("type") or "unknown"),
                            body=_message_body(message),
                            provider_timestamp=_meta_timestamp(message.get("timestamp")),
                            status=history_status,
                        )
    return {"status": "ok"}


@qr_webhook_router.get("/session")
async def get_qr_session(
    request: Request, session: Session, settings: RuntimeSettings
) -> dict[str, str | None]:
    _require_qr_gateway(request, settings)
    tenant = await _qr_tenant(session, settings)
    item = await session.scalar(
        select(WhatsAppQrSession).where(WhatsAppQrSession.tenant_id == tenant.id)
    )
    if item is None:
        return {"archive": None}
    try:
        archive = decrypt_contact(
            item.archive_ciphertext,
            settings.whatsapp_data_key.get_secret_value(),
        )
    except WhatsAppDataProtectionError as exc:
        raise AppError("WHATSAPP_QR_SESSION_INVALID", str(exc), 503) from exc
    return {"archive": archive}


@qr_webhook_router.put("/session")
async def put_qr_session(
    payload: WhatsAppQrSessionPayload,
    request: Request,
    session: Session,
    settings: RuntimeSettings,
) -> dict[str, str]:
    _require_qr_gateway(request, settings)
    tenant = await _qr_tenant(session, settings)
    try:
        ciphertext = encrypt_contact(
            payload.archive,
            settings.whatsapp_data_key.get_secret_value(),
        )
    except WhatsAppDataProtectionError as exc:
        raise AppError("WHATSAPP_QR_SESSION_KEY_MISSING", str(exc), 503) from exc
    item = await session.scalar(
        select(WhatsAppQrSession).where(WhatsAppQrSession.tenant_id == tenant.id)
    )
    if item is None:
        item = WhatsAppQrSession(tenant_id=tenant.id, archive_ciphertext=ciphertext)
        session.add(item)
    else:
        item.archive_ciphertext = ciphertext
    await session.flush()
    return {"status": "saved"}


@qr_webhook_router.post("/events")
async def receive_qr_events(
    payload: WhatsAppQrEventPayload,
    request: Request,
    session: Session,
    settings: RuntimeSettings,
) -> dict[str, int]:
    _require_qr_gateway(request, settings)
    tenant = await _qr_tenant(session, settings)
    service = WhatsAppService(session, settings)
    channel = await service.ensure_qr_channel(
        tenant.id, payload.phone, payload.display_name
    )
    channel.last_webhook_at = datetime.now(UTC)
    processed = 0
    for message in payload.messages:
        occurred_at = _meta_timestamp(message.timestamp)
        body = message.body or f"[{message.message_type}]"
        if message.direction == "in" and not message.history:
            await service.process_incoming(
                tenant_id=tenant.id,
                channel=channel,
                contact_id=message.chat_id,
                external_message_id=f"qr:{message.id}",
                body=body,
                simulated=False,
                provider_timestamp=occurred_at,
            )
        else:
            await service.store_synced_message(
                tenant_id=tenant.id,
                channel=channel,
                contact_id=message.chat_id,
                external_message_id=f"qr:{message.id}",
                direction=message.direction,
                message_type=message.message_type,
                body=body,
                provider_timestamp=occurred_at,
                status="history" if message.history else "synced",
            )
        processed += 1
    return {"processed": processed}
