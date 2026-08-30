from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.service import ContactRegistry
from app.modules.auth.models import User, UserRole
from app.modules.whatsapp.ai import (
    ChatCompletionBot,
    WhatsAppAIError,
    is_urgent_or_sensitive,
    retrieve_knowledge,
    rules_decision,
)
from app.modules.whatsapp.knowledge_import import import_knowledge_workbook
from app.modules.whatsapp.meta_client import (
    MetaEmbeddedSignupClient,
    MetaEmbeddedSignupError,
)
from app.modules.whatsapp.models import (
    WhatsAppAIUsage,
    WhatsAppChannel,
    WhatsAppConversation,
    WhatsAppKnowledgeItem,
    WhatsAppMessage,
)
from app.modules.whatsapp.schemas import (
    ConversationDetailResponse,
    ConversationListItem,
    ConversationListResponse,
    KnowledgeImportResponse,
    KnowledgeCreateRequest,
    KnowledgeItemResponse,
    KnowledgeListResponse,
    KnowledgeUpdateRequest,
    SimulatorMessageResponse,
    WhatsAppChannelResponse,
    WhatsAppStatusResponse,
    MessageItem,
)
from app.modules.whatsapp.security import (
    WhatsAppDataProtectionError,
    contact_hash,
    decrypt_contact,
    encrypt_contact,
    mask_contact,
)


class WhatsAppService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def status(self, user: User) -> WhatsAppStatusResponse:
        self._allowed(user)
        tenant = user.tenant_id
        channels = await self._count(WhatsAppChannel, tenant)
        open_conversations = await self.session.scalar(
            select(func.count()).select_from(WhatsAppConversation).where(
                WhatsAppConversation.tenant_id == tenant,
                WhatsAppConversation.state != "closed",
            )
        ) or 0
        waiting = await self.session.scalar(
            select(func.count()).select_from(WhatsAppConversation).where(
                WhatsAppConversation.tenant_id == tenant,
                WhatsAppConversation.state == "human_requested",
            )
        ) or 0
        knowledge_total = await self._count(WhatsAppKnowledgeItem, tenant)
        knowledge_approved = await self.session.scalar(
            select(func.count()).select_from(WhatsAppKnowledgeItem).where(
                WhatsAppKnowledgeItem.tenant_id == tenant,
                WhatsAppKnowledgeItem.is_approved.is_(True),
            )
        ) or 0
        spend = await self._monthly_spend(tenant)
        connected_channels = await self.session.scalar(
            select(func.count()).select_from(WhatsAppChannel).where(
                WhatsAppChannel.tenant_id == tenant,
                WhatsAppChannel.status == "connected",
                (
                    WhatsAppChannel.access_token_ciphertext.is_not(None)
                    | (WhatsAppChannel.connection_mode == "qr")
                ),
            )
        ) or 0
        setup_values = {
            "META_APP_ID": self.settings.meta_app_id,
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": (
                self.settings.whatsapp_embedded_signup_config_id
            ),
            "WHATSAPP_APP_SECRET": (
                self.settings.whatsapp_app_secret.get_secret_value()
            ),
            "WHATSAPP_DATA_KEY": (
                self.settings.whatsapp_data_key.get_secret_value()
            ),
            "WHATSAPP_VERIFY_TOKEN": (
                self.settings.whatsapp_verify_token.get_secret_value()
            ),
        }
        connection_missing = [
            name for name, value in setup_values.items() if not value
        ]
        embedded_signup_ready = all(
            setup_values[name]
            for name in (
                "META_APP_ID",
                "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID",
                "WHATSAPP_APP_SECRET",
                "WHATSAPP_DATA_KEY",
            )
        )
        configured = bool(connected_channels) or (
            bool(self.settings.whatsapp_access_token.get_secret_value())
            and not connection_missing
        )
        return WhatsAppStatusResponse(
            configured=configured,
            test_mode=not configured,
            embedded_signup_ready=embedded_signup_ready,
            meta_app_id=self.settings.meta_app_id or None,
            embedded_signup_config_id=(
                self.settings.whatsapp_embedded_signup_config_id or None
            ),
            connection_missing=connection_missing,
            ai_provider=self.settings.whatsapp_ai_provider,
            auto_send=self.settings.whatsapp_ai_auto_send,
            monthly_budget_kzt=self.settings.whatsapp_monthly_budget_kzt,
            estimated_spend_kzt=spend,
            channels=channels,
            open_conversations=open_conversations,
            waiting_for_human=waiting,
            knowledge_total=knowledge_total,
            knowledge_approved=knowledge_approved,
        )

    async def complete_embedded_signup(
        self,
        user: User,
        *,
        code: str,
        waba_id: str,
        phone_number_id: str | None,
    ) -> WhatsAppChannelResponse:
        self._owner(user)
        app_id = self.settings.meta_app_id
        app_secret = self.settings.whatsapp_app_secret.get_secret_value()
        data_key = self.settings.whatsapp_data_key.get_secret_value()
        if not app_id or not app_secret or not data_key:
            raise AppError(
                "WHATSAPP_EMBEDDED_SIGNUP_NOT_CONFIGURED",
                "Meta App ID, App Secret and WhatsApp data key are required",
                503,
            )
        try:
            client = MetaEmbeddedSignupClient(
                app_id=app_id,
                app_secret=app_secret,
                graph_version=self.settings.whatsapp_graph_api_version,
            )
            token, expires_in = await client.exchange_code(code)
            phone = await client.verify_subscribe_and_sync(
                token=token,
                waba_id=waba_id,
                phone_number_id=phone_number_id,
            )
            encrypted_token = encrypt_contact(token, data_key)
        except (MetaEmbeddedSignupError, WhatsAppDataProtectionError) as exc:
            raise AppError(
                "WHATSAPP_EMBEDDED_SIGNUP_FAILED",
                str(exc),
                502,
            ) from exc
        display_phone_number = phone["display_phone_number"]
        verified_name = phone["verified_name"]
        phone_number_id = phone["id"]
        channel = await self._ensure_channel(
            user.tenant_id,
            phone_number_id,
            verified_name or mask_contact(display_phone_number),
            status="connected",
        )
        channel.waba_id = waba_id
        channel.business_number_masked = mask_contact(display_phone_number)
        channel.access_token_ciphertext = encrypted_token
        channel.token_expires_at = (
            datetime.now(UTC) + timedelta(seconds=expires_in)
            if expires_in
            else None
        )
        channel.connected_by_user_id = user.id
        channel.connection_mode = "coexistence"
        channel.status = "connected"
        channel.bot_mode = "draft"
        channel.is_active = True
        await self.session.flush()
        return WhatsAppChannelResponse(
            id=channel.id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            display_name=channel.display_name,
            business_number_masked=channel.business_number_masked,
            status=channel.status,
            connection_mode=channel.connection_mode,
        )

    async def conversations(self, user: User) -> ConversationListResponse:
        self._allowed(user)
        rows = (
            await self.session.execute(
                select(WhatsAppConversation, WhatsAppChannel.display_name)
                .join(WhatsAppChannel, WhatsAppChannel.id == WhatsAppConversation.channel_id)
                .where(WhatsAppConversation.tenant_id == user.tenant_id)
                .order_by(WhatsAppConversation.last_message_at.desc())
                .limit(500)
            )
        ).all()
        return ConversationListResponse(
            items=[self._conversation(item, channel_name) for item, channel_name in rows]
        )

    async def conversation(self, user: User, conversation_id: UUID) -> ConversationDetailResponse:
        self._allowed(user)
        row = (
            await self.session.execute(
                select(WhatsAppConversation, WhatsAppChannel.display_name)
                .join(WhatsAppChannel, WhatsAppChannel.id == WhatsAppConversation.channel_id)
                .where(
                    WhatsAppConversation.tenant_id == user.tenant_id,
                    WhatsAppConversation.id == conversation_id,
                )
            )
        ).first()
        if row is None:
            raise AppError("WHATSAPP_CONVERSATION_NOT_FOUND", "Conversation not found", 404)
        item, channel_name = row
        messages = list(
            (
                await self.session.scalars(
                    select(WhatsAppMessage)
                    .where(
                        WhatsAppMessage.tenant_id == user.tenant_id,
                        WhatsAppMessage.conversation_id == item.id,
                    )
                    .order_by(WhatsAppMessage.created_at)
                    .limit(300)
                )
            ).all()
        )
        item.unread_count = 0
        return ConversationDetailResponse(
            conversation=self._conversation(item, channel_name),
            messages=[
                MessageItem(
                    id=message.id,
                    direction=message.direction,
                    sender_kind=message.sender_kind,
                    body=self._decrypt_message(message.body_ciphertext),
                    status=message.status,
                    is_draft=message.is_draft,
                    created_at=message.created_at,
                )
                for message in messages
            ],
        )

    async def simulate(self, user: User, message: str, contact_id: str) -> SimulatorMessageResponse:
        self._allowed(user)
        channel = await self._ensure_channel(
            user.tenant_id, "simulator", "Тестовый WhatsApp", status="test"
        )
        return await self.process_incoming(
            tenant_id=user.tenant_id,
            channel=channel,
            contact_id=contact_id,
            external_message_id=f"sim-in:{uuid4()}",
            body=message,
            simulated=True,
        )

    async def process_incoming(
        self,
        *,
        tenant_id: UUID,
        channel: WhatsAppChannel,
        contact_id: str,
        external_message_id: str,
        body: str,
        simulated: bool,
        provider_timestamp: datetime | None = None,
    ) -> SimulatorMessageResponse:
        duplicate = await self.session.scalar(
            select(WhatsAppMessage).where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.external_message_id == external_message_id,
            )
        )
        if duplicate:
            conversation = await self.session.get(WhatsAppConversation, duplicate.conversation_id)
            return SimulatorMessageResponse(
                conversation_id=duplicate.conversation_id,
                state=conversation.state if conversation else "unknown",
                reply=None,
                handoff=False,
                handoff_reason=None,
                provider="idempotent",
                cost_kzt=Decimal("0"),
            )
        if not simulated:
            await ContactRegistry(
                ContactRepository(self.session), self._data_secret()
            ).register_inbound(
                tenant_id=tenant_id,
                phone=contact_id,
                source="whatsapp",
                occurred_at=provider_timestamp or datetime.now(UTC),
            )
        conversation = await self._get_or_create_conversation(
            tenant_id, channel.id, contact_id
        )
        now = datetime.now(UTC)
        conversation.last_message_at = now
        conversation.last_patient_message_at = now
        if any(character in body.lower() for character in "әіңғүұқөһ"):
            conversation.language = "kk"
        conversation.unread_count += 1
        self.session.add(
            WhatsAppMessage(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                external_message_id=external_message_id,
                direction="in",
                sender_kind="patient",
                body_ciphertext=self._encrypt_message(body),
                status="received",
                provider_timestamp=provider_timestamp,
            )
        )
        await self.session.flush()
        if conversation.state == "human_active":
            latest_human_message = await self.session.scalar(
                select(WhatsAppMessage)
                .where(
                    WhatsAppMessage.conversation_id == conversation.id,
                    WhatsAppMessage.direction == "out",
                    WhatsAppMessage.sender_kind.in_(("business_app", "human")),
                )
                .order_by(WhatsAppMessage.created_at.desc())
                .limit(1)
            )
            pause_until = (
                latest_human_message.created_at
                + timedelta(minutes=self.settings.whatsapp_admin_pause_minutes)
                if latest_human_message
                else None
            )
            if pause_until and now >= pause_until:
                conversation.state = "bot_active"
                conversation.assigned_user_id = None
                conversation.handoff_reason = None
        if conversation.state in {"human_active", "human_requested"}:
            return SimulatorMessageResponse(
                conversation_id=conversation.id,
                state=conversation.state,
                reply=None,
                handoff=True,
                handoff_reason=conversation.handoff_reason,
                provider="paused",
                cost_kzt=Decimal("0"),
            )
        decision, provider, cost = await self._decide(tenant_id, conversation, body)
        if decision.handoff:
            conversation.state = "human_requested"
            conversation.handoff_reason = decision.handoff_reason
        outbound = WhatsAppMessage(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            external_message_id=f"{'sim' if simulated else 'bot'}-out:{uuid4()}",
            direction="out",
            sender_kind="bot",
            body_ciphertext=self._encrypt_message(decision.reply),
            status="simulated" if simulated else "draft",
            is_draft=not simulated,
        )
        self.session.add(outbound)
        await self.session.flush()
        if not simulated and self.settings.whatsapp_ai_auto_send:
            await self._send(channel, contact_id, decision.reply)
            outbound.status = "sent"
            outbound.is_draft = False
            outbound.sent_at = now
        return SimulatorMessageResponse(
            conversation_id=conversation.id,
            state=conversation.state,
            reply=decision.reply,
            handoff=decision.handoff,
            handoff_reason=decision.handoff_reason,
            provider=provider,
            cost_kzt=cost,
        )

    async def store_synced_message(
        self,
        *,
        tenant_id: UUID,
        channel: WhatsAppChannel,
        contact_id: str,
        external_message_id: str,
        direction: str,
        message_type: str,
        body: str | None,
        provider_timestamp: datetime | None,
        status: str = "synced",
    ) -> None:
        duplicate = await self.session.scalar(
            select(WhatsAppMessage.id).where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.external_message_id == external_message_id,
            )
        )
        if duplicate:
            return
        if direction == "in":
            await ContactRegistry(
                ContactRepository(self.session), self._data_secret()
            ).register_inbound(
                tenant_id=tenant_id,
                phone=contact_id,
                source="whatsapp",
                occurred_at=provider_timestamp or datetime.now(UTC),
            )
        conversation = await self._get_or_create_conversation(
            tenant_id, channel.id, contact_id
        )
        occurred_at = provider_timestamp or datetime.now(UTC)
        if occurred_at > conversation.last_message_at:
            conversation.last_message_at = occurred_at
        if direction == "in" and (
            conversation.last_patient_message_at is None
            or occurred_at > conversation.last_patient_message_at
        ):
            conversation.last_patient_message_at = occurred_at
        self.session.add(
            WhatsAppMessage(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                external_message_id=external_message_id,
                direction=direction,
                sender_kind="patient" if direction == "in" else "business_app",
                message_type=message_type,
                body_ciphertext=self._encrypt_message(body) if body else None,
                status=status,
                is_draft=False,
                provider_timestamp=provider_timestamp,
                sent_at=occurred_at if direction == "out" else None,
            )
        )
        if direction == "out" and status not in {"bot_echo", "history"}:
            conversation.state = "human_active"
            conversation.assigned_user_id = None
            conversation.handoff_reason = "Администратор ответил в WhatsApp Business"
        await self.session.flush()

    async def takeover(self, user: User, conversation_id: UUID) -> ConversationDetailResponse:
        item = await self._owned_conversation(user, conversation_id)
        item.state = "human_active"
        item.assigned_user_id = user.id
        item.handoff_reason = None
        return await self.conversation(user, conversation_id)

    async def release(self, user: User, conversation_id: UUID) -> ConversationDetailResponse:
        item = await self._owned_conversation(user, conversation_id)
        item.state = "bot_active"
        item.assigned_user_id = None
        item.handoff_reason = None
        return await self.conversation(user, conversation_id)

    async def send_human(self, user: User, conversation_id: UUID, body: str) -> MessageItem:
        item = await self._owned_conversation(user, conversation_id)
        channel = await self.session.get(WhatsAppChannel, item.channel_id)
        if channel is None:
            raise AppError("WHATSAPP_CHANNEL_NOT_FOUND", "WhatsApp channel not found", 404)
        item.state = "human_active"
        item.assigned_user_id = user.id
        now = datetime.now(UTC)
        message = WhatsAppMessage(
            tenant_id=user.tenant_id,
            conversation_id=item.id,
            external_message_id=f"human-out:{uuid4()}",
            direction="out",
            sender_kind="human",
            body_ciphertext=self._encrypt_message(body),
            status="simulated" if channel.phone_number_id == "simulator" else "sending",
            sent_at=now if channel.phone_number_id == "simulator" else None,
        )
        self.session.add(message)
        await self.session.flush()
        if channel.phone_number_id != "simulator":
            contact = decrypt_contact(
                item.contact_ciphertext,
                self.settings.whatsapp_data_key.get_secret_value(),
            )
            await self._send(channel, contact, body)
            message.status = "sent"
            message.sent_at = now
        return MessageItem(
            id=message.id,
            direction=message.direction,
            sender_kind=message.sender_kind,
            body=self._decrypt_message(message.body_ciphertext),
            status=message.status,
            is_draft=message.is_draft,
            created_at=message.created_at,
        )

    async def import_knowledge(self, user: User, data: bytes, filename: str) -> KnowledgeImportResponse:
        self._owner(user)
        if len(data) > 10_000_000:
            raise AppError("KNOWLEDGE_FILE_TOO_LARGE", "Workbook exceeds 10 MB", 413)
        try:
            rows = import_knowledge_workbook(data, filename)
        except Exception as exc:
            raise AppError("KNOWLEDGE_FILE_INVALID", "Could not read the XLSX workbook", 422) from exc
        sources = [row.source for row in rows]
        existing_sources = set(
            (
                await self.session.scalars(
                    select(WhatsAppKnowledgeItem.source).where(
                        WhatsAppKnowledgeItem.tenant_id == user.tenant_id,
                        WhatsAppKnowledgeItem.source.in_(sources),
                    )
                )
            ).all()
        ) if sources else set()
        new_rows = [row for row in rows if row.source not in existing_sources]
        for row in new_rows:
            self.session.add(
                WhatsAppKnowledgeItem(
                    tenant_id=user.tenant_id,
                    category=row.category,
                    title=row.title,
                    content_ru=row.content_ru,
                    content_kk=row.content_kk,
                    keywords=[],
                    risk_level=row.risk_level,
                    source=row.source,
                    is_approved=False,
                )
            )
        return KnowledgeImportResponse(
            imported=len(new_rows),
            review_required=sum(row.risk_level == "review" for row in new_rows),
            human_only=sum(row.risk_level == "human_only" for row in new_rows),
        )

    async def knowledge(self, user: User) -> KnowledgeListResponse:
        self._allowed(user)
        rows = list(
            (
                await self.session.scalars(
                    select(WhatsAppKnowledgeItem)
                    .where(WhatsAppKnowledgeItem.tenant_id == user.tenant_id)
                    .order_by(
                        WhatsAppKnowledgeItem.is_approved,
                        WhatsAppKnowledgeItem.category,
                        WhatsAppKnowledgeItem.title,
                    )
                    .limit(1000)
                )
            ).all()
        )
        return KnowledgeListResponse(items=[self._knowledge(item) for item in rows])

    async def create_knowledge(
        self, user: User, payload: KnowledgeCreateRequest
    ) -> KnowledgeItemResponse:
        self._owner(user)
        item = WhatsAppKnowledgeItem(
            tenant_id=user.tenant_id,
            category=payload.category.strip(),
            title=payload.title.strip(),
            content_ru=payload.content_ru.strip() if payload.content_ru else None,
            content_kk=payload.content_kk.strip() if payload.content_kk else None,
            keywords=[],
            risk_level=payload.risk_level,
            source=f"manual:{uuid4()}",
            is_approved=False,
        )
        self.session.add(item)
        await self.session.flush()
        return self._knowledge(item)

    async def update_knowledge(
        self, user: User, item_id: UUID, payload: KnowledgeUpdateRequest
    ) -> KnowledgeItemResponse:
        self._owner(user)
        item = await self.session.scalar(
            select(WhatsAppKnowledgeItem).where(
                WhatsAppKnowledgeItem.tenant_id == user.tenant_id,
                WhatsAppKnowledgeItem.id == item_id,
            )
        )
        if item is None:
            raise AppError("KNOWLEDGE_NOT_FOUND", "Knowledge item not found", 404)
        changed = False
        for field in ("category", "title", "content_ru", "content_kk", "risk_level"):
            value = getattr(payload, field)
            if value is not None:
                normalized = value.strip() if isinstance(value, str) else value
                if getattr(item, field) != normalized:
                    setattr(item, field, normalized)
                    changed = True
        approved = payload.approved
        # Any edited answer must pass owner approval again before the bot can
        # use it with patients. A PATCH cannot silently modify live knowledge.
        if changed and approved is None:
            item.is_approved = False
            item.approved_by_id = None
            item.approved_at = None
        if approved is True and item.risk_level == "human_only":
            raise AppError(
                "KNOWLEDGE_HUMAN_ONLY",
                "Promotional or human-only material cannot be enabled for automatic answers",
                409,
            )
        if approved is not None:
            item.is_approved = approved
            item.approved_by_id = user.id if approved else None
            item.approved_at = datetime.now(UTC) if approved else None
        return self._knowledge(item)

    async def _decide(self, tenant_id: UUID, conversation: WhatsAppConversation, body: str):
        sensitive = is_urgent_or_sensitive(body)
        if sensitive:
            reply = (
                "Я передаю сообщение администратору. Если состояние угрожает жизни "
                "или быстро ухудшается, пожалуйста, обратитесь за неотложной медицинской помощью."
            )
            return rules_decision(None).model_copy(
                update={"reply": reply, "handoff_reason": sensitive}
            ), "safety", Decimal("0")
        rows = list(
            (
                await self.session.scalars(
                    select(WhatsAppKnowledgeItem).where(
                        WhatsAppKnowledgeItem.tenant_id == tenant_id,
                        WhatsAppKnowledgeItem.is_approved.is_(True),
                        WhatsAppKnowledgeItem.risk_level != "human_only",
                    )
                )
            ).all()
        )
        pairs = [
            (item.title, item.content_kk if conversation.language == "kk" and item.content_kk else item.content_ru)
            for item in rows
            if (item.content_kk if conversation.language == "kk" and item.content_kk else item.content_ru)
        ]
        match = retrieve_knowledge(body, pairs)
        if match is None or self.settings.whatsapp_ai_provider == "rules":
            return rules_decision(match), "rules", Decimal("0")
        if await self._monthly_spend(tenant_id) >= self.settings.whatsapp_monthly_budget_kzt:
            decision = rules_decision(match)
            return decision, "budget-fallback", Decimal("0")
        provider = self.settings.whatsapp_ai_provider
        if provider == "groq":
            api_key = self.settings.groq_api_key.get_secret_value()
            base_url = self.settings.groq_base_url
        else:
            api_key = self.settings.openai_api_key.get_secret_value()
            base_url = self.settings.openai_base_url
        if not api_key:
            return rules_decision(match), "rules-fallback", Decimal("0")
        history_rows = list(
            (
                await self.session.scalars(
                    select(WhatsAppMessage)
                    .where(WhatsAppMessage.conversation_id == conversation.id)
                    .order_by(WhatsAppMessage.created_at.desc())
                    .limit(self.settings.whatsapp_max_context_messages)
                )
            ).all()
        )
        history = [
            {
                "role": "user" if row.direction == "in" else "assistant",
                "content": self._decrypt_message(row.body_ciphertext),
            }
            for row in reversed(history_rows)
        ]
        try:
            decision, input_tokens, output_tokens = await ChatCompletionBot(
                api_key, base_url, self.settings.whatsapp_ai_model
            ).decide(body, history, match)
        except WhatsAppAIError:
            return rules_decision(match), "rules-fallback", Decimal("0")
        cost = self._estimate_cost(provider, input_tokens, output_tokens)
        self.session.add(
            WhatsAppAIUsage(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                provider=provider,
                model=self.settings.whatsapp_ai_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_kzt=cost,
                occurred_at=datetime.now(UTC),
            )
        )
        return decision, provider, cost

    async def _send(
        self, channel: WhatsAppChannel, recipient: str, body: str
    ) -> None:
        if channel.connection_mode == "qr":
            gateway_url = self.settings.whatsapp_qr_gateway_url.rstrip("/")
            gateway_secret = self.settings.whatsapp_qr_gateway_secret.get_secret_value()
            if not gateway_url or not gateway_secret:
                raise AppError(
                    "WHATSAPP_QR_GATEWAY_NOT_CONFIGURED",
                    "WhatsApp QR gateway is not configured",
                    503,
                )
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(
                        f"{gateway_url}/send",
                        headers={"X-Gateway-Secret": gateway_secret},
                        json={"to": recipient, "text": body},
                    )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise AppError(
                    "WHATSAPP_QR_SEND_FAILED",
                    "WhatsApp QR gateway did not accept the message",
                    502,
                ) from exc
            return
        token = self.settings.whatsapp_access_token.get_secret_value()
        if channel.access_token_ciphertext:
            try:
                token = decrypt_contact(
                    channel.access_token_ciphertext,
                    self.settings.whatsapp_data_key.get_secret_value(),
                )
            except WhatsAppDataProtectionError as exc:
                raise AppError(
                    "WHATSAPP_TOKEN_DECRYPTION_FAILED",
                    "The WhatsApp channel token cannot be decrypted",
                    503,
                ) from exc
        if not token:
            raise AppError("WHATSAPP_NOT_CONFIGURED", "WhatsApp access token is missing", 503)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"https://graph.facebook.com/{self.settings.whatsapp_graph_api_version}/{channel.phone_number_id}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to": recipient,
                        "type": "text",
                        "text": {"body": body, "preview_url": False},
                    },
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppError("WHATSAPP_SEND_FAILED", "Meta did not accept the message", 502) from exc

    async def _ensure_channel(
        self, tenant_id: UUID, phone_number_id: str, display_name: str, *, status: str
    ) -> WhatsAppChannel:
        item = await self.session.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.tenant_id == tenant_id,
                WhatsAppChannel.phone_number_id == phone_number_id,
            )
        )
        if item is None:
            item = WhatsAppChannel(
                tenant_id=tenant_id,
                phone_number_id=phone_number_id,
                display_name=display_name,
                status=status,
                bot_mode="draft",
                is_active=True,
            )
            self.session.add(item)
            await self.session.flush()
        return item

    async def ensure_webhook_channel(
        self, tenant_id: UUID, phone_number_id: str, display_name: str
    ) -> WhatsAppChannel:
        return await self._ensure_channel(
            tenant_id, phone_number_id, display_name or phone_number_id, status="connected"
        )

    async def ensure_qr_channel(
        self, tenant_id: UUID, phone: str, display_name: str
    ) -> WhatsAppChannel:
        normalized = "".join(character for character in phone if character.isdigit())
        channel = await self._ensure_channel(
            tenant_id,
            f"qr:{normalized}",
            display_name or f"WhatsApp +{normalized}",
            status="connected",
        )
        channel.connection_mode = "qr"
        channel.status = "connected"
        channel.business_number_masked = f"+{normalized}" if normalized else None
        channel.is_active = True
        return channel

    async def _get_or_create_conversation(
        self, tenant_id: UUID, channel_id: UUID, contact_id: str
    ) -> WhatsAppConversation:
        hashed = contact_hash(contact_id)
        item = await self.session.scalar(
            select(WhatsAppConversation).where(
                WhatsAppConversation.tenant_id == tenant_id,
                WhatsAppConversation.channel_id == channel_id,
                WhatsAppConversation.contact_hash == hashed,
            )
        )
        if item is None:
            try:
                encrypted = encrypt_contact(contact_id, self._data_secret())
            except WhatsAppDataProtectionError as exc:
                raise AppError("WHATSAPP_DATA_KEY_MISSING", str(exc), 503) from exc
            item = WhatsAppConversation(
                tenant_id=tenant_id,
                channel_id=channel_id,
                contact_hash=hashed,
                contact_ciphertext=encrypted,
                contact_masked=mask_contact(contact_id),
                state="bot_active",
                language="ru",
                last_message_at=datetime.now(UTC),
                unread_count=0,
            )
            self.session.add(item)
            await self.session.flush()
        return item

    def _data_secret(self) -> str:
        secret = self.settings.whatsapp_data_key.get_secret_value()
        if not secret and not self.settings.whatsapp_access_token.get_secret_value():
            return "local-simulator-data-key-change-me"
        return secret

    def _encrypt_message(self, body: str) -> str:
        try:
            return encrypt_contact(body, self._data_secret())
        except WhatsAppDataProtectionError as exc:
            raise AppError("WHATSAPP_DATA_KEY_MISSING", str(exc), 503) from exc

    def _decrypt_message(self, body_ciphertext: str | None) -> str:
        if not body_ciphertext:
            return ""
        try:
            return decrypt_contact(body_ciphertext, self._data_secret())
        except WhatsAppDataProtectionError as exc:
            raise AppError("WHATSAPP_DATA_KEY_INVALID", str(exc), 503) from exc

    async def _owned_conversation(self, user: User, conversation_id: UUID) -> WhatsAppConversation:
        self._allowed(user)
        item = await self.session.scalar(
            select(WhatsAppConversation).where(
                WhatsAppConversation.tenant_id == user.tenant_id,
                WhatsAppConversation.id == conversation_id,
            )
        )
        if item is None:
            raise AppError("WHATSAPP_CONVERSATION_NOT_FOUND", "Conversation not found", 404)
        return item

    async def _monthly_spend(self, tenant_id: UUID) -> Decimal:
        month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        value = await self.session.scalar(
            select(func.sum(WhatsAppAIUsage.estimated_cost_kzt)).where(
                WhatsAppAIUsage.tenant_id == tenant_id,
                WhatsAppAIUsage.occurred_at >= month_start,
            )
        )
        return Decimal(value or 0)

    def _estimate_cost(self, provider: str, input_tokens: int, output_tokens: int) -> Decimal:
        if provider == "groq":
            return Decimal("0")
        usd = Decimal(input_tokens) / 1_000_000 * Decimal("0.75")
        usd += Decimal(output_tokens) / 1_000_000 * Decimal("4.50")
        return (usd * self.settings.whatsapp_usd_kzt_rate).quantize(Decimal("0.0001"))

    async def _count(self, model, tenant_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
            )
            or 0
        )

    @staticmethod
    def _allowed(user: User) -> None:
        if user.role not in {
            UserRole.OWNER,
            UserRole.MANAGER,
            UserRole.ADMINISTRATOR,
            UserRole.SALES_MANAGER,
        }:
            raise AppError("FORBIDDEN", "WhatsApp is not available for this role", 403)

    @staticmethod
    def _owner(user: User) -> None:
        if user.role != UserRole.OWNER:
            raise AppError("FORBIDDEN", "Only the owner can manage bot knowledge", 403)

    def _conversation(self, item: WhatsAppConversation, channel_name: str) -> ConversationListItem:
        try:
            contact_full = decrypt_contact(item.contact_ciphertext, self._data_secret())
        except WhatsAppDataProtectionError:
            contact_full = item.contact_masked
        return ConversationListItem(
            id=item.id,
            channel_name=channel_name,
            contact_masked=item.contact_masked,
            contact_full=contact_full,
            state=item.state,
            language=item.language,
            handoff_reason=item.handoff_reason,
            last_message_at=item.last_message_at,
            unread_count=item.unread_count,
            assigned_user_id=item.assigned_user_id,
        )

    @staticmethod
    def _knowledge(item: WhatsAppKnowledgeItem) -> KnowledgeItemResponse:
        return KnowledgeItemResponse(
            id=item.id,
            category=item.category,
            title=item.title,
            content_ru=item.content_ru,
            content_kk=item.content_kk,
            risk_level=item.risk_level,
            source=item.source,
            is_approved=item.is_approved,
            created_at=item.created_at,
        )
