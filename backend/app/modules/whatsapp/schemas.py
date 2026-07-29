from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class WhatsAppStatusResponse(BaseModel):
    configured: bool
    test_mode: bool
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


class KnowledgeApprovalRequest(BaseModel):
    approved: bool
    risk_level: str | None = Field(default=None, pattern="^(safe|review|human_only)$")


class KnowledgeImportResponse(BaseModel):
    imported: int
    review_required: int
    human_only: int
