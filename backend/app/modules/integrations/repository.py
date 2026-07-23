"""Persistence for connections, raw rows, mapping and normalization state."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations.models import (
    IntegrationConnection,
    MappingProfile,
    NormalizationError,
    RawRecord,
    RecordLineage,
    SyncRun,
)
from app.modules.integrations.schemas import MappingDefinition, MappingIssue


class IntegrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_connections(self, tenant_id: UUID) -> list[IntegrationConnection]:
        return list(
            (
                await self.session.scalars(
                    select(IntegrationConnection)
                    .where(IntegrationConnection.tenant_id == tenant_id)
                    .order_by(IntegrationConnection.name)
                )
            ).all()
        )

    async def get_connection(
        self, tenant_id: UUID, connection_id: UUID
    ) -> IntegrationConnection | None:
        return await self.session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.id == connection_id,
            )
        )

    async def create_connection(
        self, *, tenant_id: UUID, provider: str, name: str, settings: dict[str, object]
    ) -> IntegrationConnection:
        connection = IntegrationConnection(
            tenant_id=tenant_id,
            provider=provider,
            name=name,
            status="active",
            settings=settings,
        )
        self.session.add(connection)
        await self.session.flush()
        return connection

    async def create_mapping_profile(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        definition: MappingDefinition,
    ) -> MappingProfile:
        current_version = await self.session.scalar(
            select(func.max(MappingProfile.version)).where(
                MappingProfile.tenant_id == tenant_id,
                MappingProfile.connection_id == connection_id,
                MappingProfile.source_entity == definition.source_entity,
                MappingProfile.target_entity == definition.target_entity,
            )
        )
        await self.session.execute(
            update(MappingProfile)
            .where(
                MappingProfile.tenant_id == tenant_id,
                MappingProfile.connection_id == connection_id,
                MappingProfile.source_entity == definition.source_entity,
                MappingProfile.target_entity == definition.target_entity,
                MappingProfile.is_active.is_(True),
            )
            .values(is_active=False)
        )
        profile = MappingProfile(
            tenant_id=tenant_id,
            connection_id=connection_id,
            source_entity=definition.source_entity,
            target_entity=definition.target_entity,
            version=(current_version or 0) + 1,
            rules=definition.model_dump(mode="json"),
            is_active=True,
        )
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def get_mapping_profile(
        self, *, tenant_id: UUID, connection_id: UUID, mapping_profile_id: UUID
    ) -> MappingProfile | None:
        return await self.session.scalar(
            select(MappingProfile).where(
                MappingProfile.tenant_id == tenant_id,
                MappingProfile.connection_id == connection_id,
                MappingProfile.id == mapping_profile_id,
            )
        )

    async def list_mapping_profiles(
        self, tenant_id: UUID, connection_id: UUID
    ) -> list[MappingProfile]:
        return list((await self.session.scalars(
            select(MappingProfile).where(
                MappingProfile.tenant_id == tenant_id,
                MappingProfile.connection_id == connection_id,
            ).order_by(MappingProfile.is_active.desc(), MappingProfile.created_at.desc())
        )).all())

    async def deactivate_mapping_profile(
        self, *, tenant_id: UUID, connection_id: UUID, mapping_profile_id: UUID
    ) -> bool:
        # Soft-delete: raw records / quarantine rows already reference this
        # profile's id, so a hard delete would break that history. Marking
        # it inactive removes it from the "available for new uploads" list.
        result = await self.session.execute(
            update(MappingProfile)
            .where(
                MappingProfile.tenant_id == tenant_id,
                MappingProfile.connection_id == connection_id,
                MappingProfile.id == mapping_profile_id,
            )
            .values(is_active=False)
        )
        return result.rowcount > 0

    async def create_sync_run(self, tenant_id: UUID, connection_id: UUID) -> SyncRun:
        run = SyncRun(
            tenant_id=tenant_id,
            connection_id=connection_id,
            status="processing",
            started_at=datetime.now(UTC),
            records_read=0,
            records_written=0,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def store_raw_record(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
        source_entity: str,
        source_record_id: str | None,
        source_schema_version: str | None,
        record_hash: str,
        payload: dict[str, object],
    ) -> tuple[RawRecord, bool]:
        record_id = uuid4()
        statement = (
            insert(RawRecord)
            .values(
                id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                sync_run_id=sync_run_id,
                source_entity=source_entity,
                source_record_id=source_record_id,
                source_schema_version=source_schema_version,
                record_hash=record_hash,
                payload=payload,
                status="pending",
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "connection_id", "source_entity", "record_hash"]
            )
            .returning(RawRecord)
        )
        created = (await self.session.execute(statement)).scalar_one_or_none()
        if created is not None:
            return created, True
        existing = await self.session.scalar(
            select(RawRecord).where(
                RawRecord.tenant_id == tenant_id,
                RawRecord.connection_id == connection_id,
                RawRecord.source_entity == source_entity,
                RawRecord.record_hash == record_hash,
            )
        )
        if existing is None:
            raise RuntimeError("Raw record conflict could not be resolved")
        return existing, False

    async def quarantine(
        self,
        *,
        tenant_id: UUID,
        raw_record: RawRecord,
        mapping_profile_id: UUID,
        issues: list[MappingIssue],
    ) -> None:
        for issue in issues:
            self.session.add(
                NormalizationError(
                    tenant_id=tenant_id,
                    raw_record_id=raw_record.id,
                    mapping_profile_id=mapping_profile_id,
                    error_code=issue.code,
                    message=issue.message,
                    field_name=issue.field_name,
                    raw_value=issue.raw_value,
                    status="open",
                )
            )
        raw_record.status = "quarantined"
        await self.session.flush()

    async def mark_normalized(
        self,
        *,
        tenant_id: UUID,
        raw_record: RawRecord,
        mapping_profile_id: UUID,
        target_entity: str,
        target_record_id: UUID,
    ) -> None:
        raw_record.status = "normalized"
        self.session.add(
            RecordLineage(
                tenant_id=tenant_id,
                raw_record_id=raw_record.id,
                mapping_profile_id=mapping_profile_id,
                target_entity=target_entity,
                target_record_id=target_record_id,
            )
        )
        await self.session.flush()

    async def finish_sync_run(
        self,
        run: SyncRun,
        *,
        status: str,
        records_read: int,
        records_written: int,
        error_message: str | None = None,
    ) -> None:
        run.status = status
        run.records_read = records_read
        run.records_written = records_written
        run.error_message = error_message
        run.finished_at = datetime.now(UTC)
        await self.session.flush()
