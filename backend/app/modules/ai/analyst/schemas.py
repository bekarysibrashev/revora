from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, Field, field_validator

class AnalystSource(BaseModel):
    tool: str
    label: str
    date_from: date
    date_to: date
    branch_id: UUID | None
    data_as_of: datetime | None

class ChatSessionCreate(BaseModel):
    title: str = Field(default="Новый анализ", min_length=1, max_length=200)
    branch_id: UUID | None = None
    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return value.strip()

class ChatSessionResponse(BaseModel):
    id: UUID
    title: str
    branch_id: UUID | None
    is_archived: bool
    last_message_at: datetime | None
    created_at: datetime

class ChatSessionList(BaseModel):
    items: list[ChatSessionResponse]
    total: int

class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=2, max_length=4000)
    date_from: date | None = None
    date_to: date | None = None
    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        return value.strip()

class ChatMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    sources: list[AnalystSource] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    model: str | None
    created_at: datetime

class ChatMessageList(BaseModel):
    items: list[ChatMessageResponse]
    total: int

class ChatTurnResponse(BaseModel):
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse

class ArchiveResponse(BaseModel):
    message: str = "Session archived"
