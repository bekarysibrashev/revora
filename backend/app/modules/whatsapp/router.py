import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

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
    KnowledgeApprovalRequest,
    KnowledgeImportResponse,
    KnowledgeItemResponse,
    KnowledgeListResponse,
    MessageItem,
    SimulatorMessageRequest,
    SimulatorMessageResponse,
    WhatsAppStatusResponse,
    WhatsAppChannelResponse,
)
from app.modules.whatsapp.security import valid_meta_signature
from app.modules.whatsapp.service import WhatsAppService

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
webhook_router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhook"])
Session = Annotated[AsyncSession, Depends(get_db_session)]
RuntimeSettings = Annotated[Settings, Depends(get_settings)]


@router.get("/status", response_model=WhatsAppStatusResponse)
async def status(
    user: CurrentUser, session: Session, settings: RuntimeSettings
) -> WhatsAppStatusResponse:
    return await WhatsAppService(session, settings).status(user)


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
    payload: KnowledgeApprovalRequest,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> KnowledgeItemResponse:
    return await WhatsAppService(session, settings).approve_knowledge(
        user, item_id, payload.approved, payload.risk_level
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
                timestamp = None
                try:
                    timestamp = datetime.fromtimestamp(
                        int(message.get("timestamp")), tz=UTC
                    )
                except (TypeError, ValueError):
                    pass
                await service.process_incoming(
                    tenant_id=tenant.id,
                    channel=channel,
                    contact_id=contact_id,
                    external_message_id=external_message_id,
                    body=body,
                    simulated=False,
                    provider_timestamp=timestamp,
                )
    return {"status": "ok"}
