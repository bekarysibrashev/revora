"""Contracts for source-to-canonical mapping definitions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TransformName = Literal["string", "decimal", "date", "datetime", "integer", "boolean"]


class FieldMappingRule(BaseModel):
    """How one canonical field is read from a source row."""

    source_fields: list[str] = Field(min_length=1)
    required: bool = False
    transform: TransformName = "string"
    default: object | None = None

    @field_validator("source_fields")
    @classmethod
    def normalize_source_fields(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized:
            raise ValueError("At least one non-empty source field is required")
        if len(normalized) != len(set(item.casefold() for item in normalized)):
            raise ValueError("Source field aliases must be unique")
        return normalized


class MappingDefinition(BaseModel):
    """Version-independent executable mapping rules."""

    source_entity: str = Field(min_length=1, max_length=100)
    target_entity: str = Field(min_length=1, max_length=100)
    fields: dict[str, FieldMappingRule] = Field(min_length=1)

    @field_validator("source_entity", "target_entity")
    @classmethod
    def normalize_entity_name(cls, value: str) -> str:
        return value.strip().lower()


class MappingIssue(BaseModel):
    code: str
    message: str
    field_name: str | None = None
    raw_value: object | None = None


class MappingResult(BaseModel):
    target_entity: str
    data: dict[str, object]
    issues: list[MappingIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues


class ConnectionCreateRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=150)
    settings: dict[str, object] = Field(default_factory=dict)

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    name: str
    status: str
    settings: dict[str, object]
    created_at: datetime
    updated_at: datetime


class ConnectionListResponse(BaseModel):
    items: list[ConnectionResponse]
    total: int


class MappingProfileCreateRequest(MappingDefinition):
    pass


class MappingProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connection_id: UUID
    source_entity: str
    target_entity: str
    version: int
    rules: dict[str, object]
    is_active: bool
    created_at: datetime


class MappingProfileListResponse(BaseModel):
    items: list[MappingProfileResponse]
    total: int


class IngestionSummaryResponse(BaseModel):
    sync_run_id: UUID
    status: str
    records_read: int
    records_normalized: int
    records_quarantined: int
    records_duplicate: int
    error_message: str | None = None
