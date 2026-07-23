"""Application orchestration for source ingestion and canonical loading."""

from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.integrations.adapter import IntegrationAdapter
from app.modules.integrations.canonical_writer import CanonicalWriteError, CanonicalWriter
from app.modules.integrations.mapper import CanonicalMapper, compute_record_hash
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.schemas import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionResponse,
    IngestionSummaryResponse,
    MappingDefinition,
    MappingIssue,
    MappingProfileListResponse,
    MappingProfileResponse,
)
from app.modules.integrations.tabular_adapter import InvalidTabularFile, UnsupportedTabularFile


class IntegrationService:
    def __init__(
        self, repository: IntegrationRepository, canonical_writer: CanonicalWriter
    ) -> None:
        self.repository = repository
        self.canonical_writer = canonical_writer

    async def list_connections(self, user: User) -> ConnectionListResponse:
        self._require_owner(user)
        connections = await self.repository.list_connections(user.tenant_id)
        items = [ConnectionResponse.model_validate(item) for item in connections]
        return ConnectionListResponse(items=items, total=len(items))

    async def create_connection(
        self, user: User, payload: ConnectionCreateRequest
    ) -> ConnectionResponse:
        self._require_owner(user)
        connection = await self.repository.create_connection(
            tenant_id=user.tenant_id,
            provider=payload.provider,
            name=payload.name,
            settings=payload.settings,
        )
        return ConnectionResponse.model_validate(connection)

    async def create_mapping_profile(
        self, user: User, connection_id: UUID, definition: MappingDefinition
    ) -> MappingProfileResponse:
        self._require_owner(user)
        await self._connection(user.tenant_id, connection_id)
        if definition.target_entity not in self.canonical_writer.SUPPORTED_TARGETS:
            raise AppError(
                "UNSUPPORTED_CANONICAL_TARGET",
                f"Unsupported canonical target '{definition.target_entity}'",
                422,
            )
        profile = await self.repository.create_mapping_profile(
            tenant_id=user.tenant_id,
            connection_id=connection_id,
            definition=definition,
        )
        return MappingProfileResponse.model_validate(profile)

    async def list_mapping_profiles(
        self, user: User, connection_id: UUID
    ) -> MappingProfileListResponse:
        self._require_owner(user)
        await self._connection(user.tenant_id, connection_id)
        profiles = await self.repository.list_mapping_profiles(user.tenant_id, connection_id)
        items = [MappingProfileResponse.model_validate(item) for item in profiles]
        return MappingProfileListResponse(items=items, total=len(items))

    async def delete_mapping_profile(
        self, user: User, connection_id: UUID, mapping_profile_id: UUID
    ) -> None:
        self._require_owner(user)
        await self._connection(user.tenant_id, connection_id)
        deleted = await self.repository.deactivate_mapping_profile(
            tenant_id=user.tenant_id,
            connection_id=connection_id,
            mapping_profile_id=mapping_profile_id,
        )
        if not deleted:
            raise AppError("MAPPING_PROFILE_NOT_FOUND", "Mapping profile not found", 404)

    async def ingest(
        self,
        user: User,
        *,
        connection_id: UUID,
        mapping_profile_id: UUID,
        adapter: IntegrationAdapter,
    ) -> IngestionSummaryResponse:
        self._require_owner(user)
        await self._connection(user.tenant_id, connection_id)
        profile = await self.repository.get_mapping_profile(
            tenant_id=user.tenant_id,
            connection_id=connection_id,
            mapping_profile_id=mapping_profile_id,
        )
        if profile is None:
            raise AppError("MAPPING_PROFILE_NOT_FOUND", "Mapping profile not found", 404)
        definition = MappingDefinition.model_validate(profile.rules)
        mapper = CanonicalMapper(definition)
        run = await self.repository.create_sync_run(user.tenant_id, connection_id)
        records_read = 0
        normalized = 0
        quarantined = 0
        duplicates = 0

        try:
            async for source_record in adapter.fetch():
                records_read += 1
                raw_record, created = await self.repository.store_raw_record(
                    tenant_id=user.tenant_id,
                    connection_id=connection_id,
                    sync_run_id=run.id,
                    source_entity=source_record.source_entity,
                    source_record_id=source_record.external_id,
                    source_schema_version=source_record.schema_version,
                    record_hash=compute_record_hash(
                        source_record.source_entity, dict(source_record.payload)
                    ),
                    payload=dict(source_record.payload),
                )
                if not created:
                    duplicates += 1
                    continue

                result = mapper.normalize(source_record)
                if result.issues:
                    await self.repository.quarantine(
                        tenant_id=user.tenant_id,
                        raw_record=raw_record,
                        mapping_profile_id=profile.id,
                        issues=result.issues,
                    )
                    quarantined += 1
                    continue

                try:
                    target_record_id = await self.canonical_writer.write(
                        tenant_id=user.tenant_id,
                        target_entity=result.target_entity,
                        data=result.data,
                    )
                except CanonicalWriteError as exc:
                    await self.repository.quarantine(
                        tenant_id=user.tenant_id,
                        raw_record=raw_record,
                        mapping_profile_id=profile.id,
                        issues=[
                            MappingIssue(
                                code="CANONICAL_WRITE_FAILED",
                                message=str(exc),
                            )
                        ],
                    )
                    quarantined += 1
                    continue

                await self.repository.mark_normalized(
                    tenant_id=user.tenant_id,
                    raw_record=raw_record,
                    mapping_profile_id=profile.id,
                    target_entity=result.target_entity,
                    target_record_id=target_record_id,
                )
                normalized += 1
        except (InvalidTabularFile, UnsupportedTabularFile) as exc:
            await self.repository.finish_sync_run(
                run,
                status="failed",
                records_read=records_read,
                records_written=normalized,
                error_message=str(exc),
            )
            return IngestionSummaryResponse(
                sync_run_id=run.id,
                status="failed",
                records_read=records_read,
                records_normalized=normalized,
                records_quarantined=quarantined,
                records_duplicate=duplicates,
                error_message=str(exc),
            )

        await self.repository.finish_sync_run(
            run,
            status="completed_with_errors" if quarantined else "completed",
            records_read=records_read,
            records_written=normalized,
        )
        return IngestionSummaryResponse(
            sync_run_id=run.id,
            status="completed_with_errors" if quarantined else "completed",
            records_read=records_read,
            records_normalized=normalized,
            records_quarantined=quarantined,
            records_duplicate=duplicates,
        )

    async def _connection(self, tenant_id: UUID, connection_id: UUID):
        connection = await self.repository.get_connection(tenant_id, connection_id)
        if connection is None:
            raise AppError("INTEGRATION_NOT_FOUND", "Integration connection not found", 404)
        return connection

    @staticmethod
    def _require_owner(user: User) -> None:
        if user.role != UserRole.OWNER:
            raise AppError("FORBIDDEN", "Only the owner can manage integrations", 403)
