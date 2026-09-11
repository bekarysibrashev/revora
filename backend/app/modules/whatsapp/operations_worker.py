"""Durable WhatsApp delivery and voice-transcription worker."""

import asyncio
import base64
from contextlib import suppress
from datetime import UTC, datetime, timedelta
import logging

from sqlalchemy import select, text, update

from app.core.config import Settings
from app.core.database import AsyncSessionFactory
from app.modules.ai.call_quality.intelligence import CallIntelligenceError
from app.modules.ai.call_quality.pipeline import CallQualityPipeline
from app.modules.tenancy.models import Tenant
from app.modules.whatsapp.models import (
    WhatsAppChannel,
    WhatsAppConversation,
    WhatsAppGatewayLog,
    WhatsAppMessage,
)
from app.modules.whatsapp.security import decrypt_contact, encrypt_contact
from app.modules.whatsapp.service import WhatsAppService


logger = logging.getLogger(__name__)


class EmbeddedWhatsAppOperationsWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.settings.embedded_whatsapp_operations_worker or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="revora-whatsapp-operations")
        logger.info("Embedded WhatsApp operations worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(3)
        while True:
            try:
                worked = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                worked = False
                logger.exception("WhatsApp operations worker iteration failed")
            await asyncio.sleep(1 if worked else self.settings.whatsapp_operations_interval_seconds)

    async def run_once(self) -> bool:
        async with AsyncSessionFactory() as session:
            tenant_ids = list(
                (await session.scalars(select(Tenant.id).where(Tenant.is_active.is_(True)))).all()
            )
            for tenant_id in tenant_ids:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_id)},
                )
                if await self._deliver_one(session, tenant_id):
                    return True
                if await self._transcribe_one(session, tenant_id):
                    return True
        return False

    async def _deliver_one(self, session, tenant_id) -> bool:
        now = datetime.now(UTC)
        await session.execute(
            update(WhatsAppMessage)
            .where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.status == "sending",
                WhatsAppMessage.updated_at < now - timedelta(minutes=3),
            )
            .values(status="retrying", next_delivery_at=now)
        )
        message = await session.scalar(
            select(WhatsAppMessage)
            .where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.direction == "out",
                WhatsAppMessage.status.in_(("queued", "retrying")),
                WhatsAppMessage.is_draft.is_(False),
                (WhatsAppMessage.next_delivery_at.is_(None) | (WhatsAppMessage.next_delivery_at <= now)),
            )
            .order_by(WhatsAppMessage.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if message is None:
            await session.commit()
            return False
        message.status = "sending"
        message.delivery_attempts += 1
        message.last_delivery_error = None
        message_id = message.id
        await session.commit()

        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        message = await session.scalar(
            select(WhatsAppMessage).where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.id == message_id,
            )
        )
        conversation = await session.get(WhatsAppConversation, message.conversation_id) if message else None
        channel = await session.get(WhatsAppChannel, conversation.channel_id) if conversation else None
        if message is None or conversation is None or channel is None:
            return False
        secret = self.settings.whatsapp_data_key.get_secret_value()
        try:
            recipient = decrypt_contact(conversation.contact_ciphertext, secret)
            body = decrypt_contact(message.body_ciphertext, secret)
            await WhatsAppService(session, self.settings)._send(
                channel, recipient, body, command_id=str(message.id)
            )
        except Exception as exc:
            message.last_delivery_error = str(exc)[:500]
            if message.delivery_attempts >= self.settings.whatsapp_delivery_max_attempts:
                message.status = "failed"
                message.next_delivery_at = None
            else:
                message.status = "retrying"
                delay = min(300, 5 * (2 ** (message.delivery_attempts - 1)))
                message.next_delivery_at = datetime.now(UTC) + timedelta(seconds=delay)
            session.add(
                WhatsAppGatewayLog(
                    tenant_id=tenant_id,
                    level="error" if message.status == "failed" else "warn",
                    event="delivery",
                    message=f"Не удалось отправить сообщение: {message.last_delivery_error}",
                    occurred_at=datetime.now(UTC),
                )
            )
        else:
            message.status = "sent"
            message.sent_at = datetime.now(UTC)
            message.next_delivery_at = None
        await session.commit()
        return True

    async def _transcribe_one(self, session, tenant_id) -> bool:
        await session.execute(
            update(WhatsAppMessage)
            .where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.transcription_status == "processing",
                WhatsAppMessage.updated_at < datetime.now(UTC) - timedelta(minutes=10),
            )
            .values(transcription_status="retrying")
        )
        message = await session.scalar(
            select(WhatsAppMessage)
            .where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.message_type == "audio",
                WhatsAppMessage.media_ciphertext.is_not(None),
                WhatsAppMessage.transcription_status.in_(("queued", "retrying")),
                WhatsAppMessage.transcription_attempts < 3,
            )
            .order_by(WhatsAppMessage.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if message is None:
            await session.commit()
            return False
        message.transcription_status = "processing"
        message.transcription_attempts += 1
        message_id = message.id
        await session.commit()

        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        message = await session.scalar(
            select(WhatsAppMessage).where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.id == message_id,
            )
        )
        if message is None:
            return False
        secret = self.settings.whatsapp_data_key.get_secret_value()
        try:
            media = base64.b64decode(decrypt_contact(message.media_ciphertext, secret), validate=True)
            client = CallQualityPipeline._default_transcription_client(self.settings)
            transcript = await client.transcribe(
                media,
                filename=message.media_filename or "voice.ogg",
                content_type=message.media_mime_type or "audio/ogg",
            )
            text_value = " ".join(item.text.strip() for item in transcript.segments if item.text.strip())
            if not text_value:
                raise ValueError("Пустая расшифровка")
            message.transcript_ciphertext = encrypt_contact(text_value, secret)
            message.transcription_status = "ready"
            message.transcription_error = None
        except CallIntelligenceError as exc:
            message.transcription_error = str(exc)[:500]
            message.transcription_status = (
                "failed"
                if not exc.retryable or message.transcription_attempts >= 3
                else "retrying"
            )
        except (ValueError, TypeError) as exc:
            message.transcription_error = str(exc)[:500]
            message.transcription_status = "failed"
        except Exception as exc:
            # Network/provider failures must not leave a voice message stuck in
            # "processing" until the stale-job recovery window expires.
            message.transcription_error = str(exc)[:500]
            message.transcription_status = (
                "failed" if message.transcription_attempts >= 3 else "retrying"
            )
            logger.warning(
                "WhatsApp voice transcription failed tenant=%s message=%s attempt=%s",
                tenant_id,
                message.id,
                message.transcription_attempts,
            )
        await session.commit()
        return True
