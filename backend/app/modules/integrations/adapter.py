"""Source adapter boundary used by API, file and database integrations."""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One untouched record emitted by an integration adapter."""

    source_entity: str
    payload: Mapping[str, object]
    external_id: str | None = None
    schema_version: str | None = None


class IntegrationAdapter(Protocol):
    """Every provider adapter only fetches; it does not know the canonical schema."""

    def fetch(self) -> AsyncIterator[SourceRecord]: ...
