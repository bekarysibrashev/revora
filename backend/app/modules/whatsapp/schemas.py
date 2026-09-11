from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class WhatsAppStatusResponse(BaseModel):
    configured: bool
    test_mode: bool
    embedded_signup_ready: bool
    meta_app_id: str | None
    embedded_signup_config_id: str | None
    connection_missing: list[str]
    ai_provider: str
    auto_send: bool
    monthly_budget_kzt: int
    estimated_spend_kzt: Decimal
    channels: int
    open_conversations: int
    waiting_for_human: int
    knowledge_total: int
    knowledge_approved: int


class ConversationListItem(BaseModel):
    id: UUID
    channel_name: str
    contact_masked: str
    contact_full: str
    state: str
    language: str
    handoff_reason: str | None
    last_message_at: datetime
    unread_count: int
    assigned_user_id: UUID | None


class ConversationListResponse(BaseModel):
    items: list[ConversationListItem]


class MessageItem(BaseModel):
    id: UUID
    direction: str
    sender_kind: str
    body: str | None
    status: str
    is_draft: bool
    created_at: datetime
    message_type: str = "text"
    media_available: bool = False
    media_filename: str | None = None
    media_mime_type: str | None = None
    transcript: str | None = None
    transcription_status: str | None = None
    transcription_error: str | None = None
    delivery_attempts: int = 0
    last_delivery_error: str | None = None


class ConversationDetailResponse(BaseModel):
    conversation: ConversationListItem
    messages: list[MessageItem]


class SimulatorMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    contact_id: str = Field(default="simulator-patient", min_length=3, max_length=100)


class SimulatorMessageResponse(BaseModel):
    conversation_id: UUID
    state: str
    reply: str | None
    handoff: bool
    handoff_reason: str | None
    provider: str
    cost_kzt: Decimal


class HumanMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class WhatsAppBotModeRequest(BaseModel):
    auto_send: bool


class KnowledgeItemResponse(BaseModel):
    id: UUID
    category: str
    title: str
    content_ru: str | None
    content_kk: str | None
    risk_level: str
    source: str
    is_approved: bool
    created_at: datetime


class KnowledgeListResponse(BaseModel):
    items: list[KnowledgeItemResponse]


class KnowledgeCreateRequest(BaseModel):
    category: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=2, max_length=300)
    content_ru: str | None = Field(default=None, min_length=2, max_length=5000)
    content_kk: str | None = Field(default=None, min_length=2, max_length=5000)
    risk_level: str = Field(default="review", pattern="^(safe|review|human_only)$")

    @model_validator(mode="after")
    def require_content(self) -> "KnowledgeCreateRequest":
        if not (self.content_ru or self.content_kk):
            raise ValueError("At least one answer language is required")
        return self


class KnowledgeUpdateRequest(BaseModel):
    category: str | None = Field(default=None, min_length=2, max_length=120)
    title: str | None = Field(default=None, min_length=2, max_length=300)
    content_ru: str | None = Field(default=None, min_length=2, max_length=5000)
    content_kk: str | None = Field(default=None, min_length=2, max_length=5000)
    approved: bool | None = None
    risk_level: str | None = Field(default=None, pattern="^(safe|review|human_only)$")


class KnowledgeImportResponse(BaseModel):
    imported: int
    updated: int = 0
    auto_approved: int
    review_required: int
    human_only: int


class KnowledgeSheetResponse(BaseModel):
    connected: bool
    service_account_email: str | None = None
    sheet_url: str | None = None
    sheet_names: list[str] = Field(default_factory=list)
    is_enabled: bool = True
    last_synced_at: datetime | None = None
    last_sync_status: str | None = None
    last_sync_error: str | None = None
    last_sync_imported: int = 0
    last_sync_updated: int = 0
    last_sync_auto_approved: int = 0
    last_sync_review_required: int = 0
    last_sync_human_only: int = 0


class KnowledgeSheetConnectRequest(BaseModel):
    sheet_url: str = Field(min_length=10, max_length=500)
    # Tab names to sync from (case/whitespace-insensitive); empty = every tab
    # except the promotional/Лист-N ones the importer already excludes.
    sheet_names: list[str] = Field(default_factory=list, max_length=50)


class EmbeddedSignupCompleteRequest(BaseModel):
    code: str = Field(min_length=10, max_length=2000)
    waba_id: str = Field(pattern=r"^\d{5,30}$")
    phone_number_id: str | None = Field(default=None, pattern=r"^\d{5,30}$")
    business_id: str | None = Field(default=None, pattern=r"^\d{5,30}$")


class WhatsAppChannelResponse(BaseModel):
    id: UUID
    waba_id: str
    phone_number_id: str
    display_name: str
    business_number_masked: str | None
    status: str
    connection_mode: str


class WhatsAppQrStatusResponse(BaseModel):
    configured: bool
    state: str
    connected: bool
    qr_data_url: str | None = None
    phone: str | None = None
    message: str | None = None
    last_heartbeat_at: datetime | None = None
    last_message_at: datetime | None = None
    last_history_sync_at: datetime | None = None
    messages_forwarded: int = 0
    history_messages_forwarded: int = 0
    reconnect_count: int = 0
    last_error: str | None = None
    stale: bool = False


class WhatsAppQrSessionPayload(BaseModel):
    archive: str = Field(min_length=1, max_length=15_000_000)


class WhatsAppQrMessageEvent(BaseModel):
    id: str = Field(min_length=1, max_length=300)
    chat_id: str = Field(min_length=3, max_length=150)
    direction: str = Field(pattern="^(in|out)$")
    message_type: str = Field(default="text", max_length=30)
    body: str | None = Field(default=None, max_length=20_000)
    timestamp: int | None = None
    history: bool = False
    media_base64: str | None = Field(default=None, max_length=12_000_000)
    media_mime_type: str | None = Field(default=None, max_length=120)
    media_filename: str | None = Field(default=None, max_length=255)
    attribution: dict[str, str] | None = None


class WhatsAppQrEventPayload(BaseModel):
    phone: str = Field(min_length=3, max_length=100)
    display_name: str = Field(default="WhatsApp QR", max_length=150)
    messages: list[WhatsAppQrMessageEvent] = Field(max_length=250)


class WhatsAppGatewayLogEvent(BaseModel):
    level: str = Field(default="info", pattern="^(debug|info|warn|error)$")
    event: str = Field(default="gateway", min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    timestamp: int | None = None


class WhatsAppGatewayHeartbeat(BaseModel):
    state: str = Field(min_length=1, max_length=40)
    connected: bool
    phone: str | None = Field(default=None, max_length=100)
    gateway_version: str | None = Field(default=None, max_length=40)
    instance_id: str | None = Field(default=None, max_length=100)
    started_at: int | None = None
    last_message_at: int | None = None
    last_history_sync_at: int | None = None
    messages_forwarded: int = Field(default=0, ge=0)
    history_messages_forwarded: int = Field(default=0, ge=0)
    reconnect_count: int = Field(default=0, ge=0)
    last_error: str | None = Field(default=None, max_length=500)
    logs: list[WhatsAppGatewayLogEvent] = Field(default_factory=list, max_length=100)


class WhatsAppGatewayLogItem(BaseModel):
    id: UUID
    level: str
    event: str
    message: str
    occurred_at: datetime


class WhatsAppGatewayLogResponse(BaseModel):
    items: list[WhatsAppGatewayLogItem]


class WhatsAppAnalyticsResponse(BaseModel):
    date_from: date
    date_to: date
    conversations: int
    messages_total: int
    incoming_messages: int
    outgoing_messages: int
    bot_messages: int
    human_messages: int
    history_messages: int
    media_messages: int
    voice_messages: int
    transcribed_voice_messages: int
    waiting_for_human: int
    unanswered_conversations: int
    average_first_response_seconds: float | None
    new_contacts: int
    existing_patient_contacts: int
