"""Persistence for connections, raw rows, mapping and normalization state."""

from datetime import UTC, datetime
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
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
from app.modules.tenancy.models import Branch


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
        self,
        *,
        tenant_id: UUID,
        provider: str,
        name: str,
        settings: dict[str, object],
        status: str = "active",
    ) -> IntegrationConnection:
        connection = IntegrationConnection(
            tenant_id=tenant_id,
            provider=provider,
            name=name,
            status=status,
            settings=settings,
        )
        self.session.add(connection)
        await self.session.flush()
        return connection

    async def set_tenant_context(self, tenant_id: UUID) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    async def configure_one_c_connector(
        self,
        connection: IntegrationConnection,
        *,
        token_digest: str,
        settings: dict[str, object],
    ) -> None:
        connection.encrypted_credentials = token_digest
        connection.settings = settings
        connection.status = "awaiting_data"
        await self.session.flush()

    async def mark_connection_synced(
        self,
        connection: IntegrationConnection,
        *,
        entity: str,
        synced_at: datetime,
    ) -> None:
        connection.settings = {
            **(connection.settings or {}),
            "last_synced_at": synced_at.isoformat(),
            "last_entity": entity,
        }
        connection.status = (
            "syncing"
            if (connection.settings or {}).get("sync_status") == "running"
            else "connected"
        )
        await self.session.flush()

    async def single_active_branch_code(self, tenant_id: UUID) -> str | None:
        codes = list(
            (
                await self.session.scalars(
                    select(Branch.code)
                    .where(Branch.tenant_id == tenant_id, Branch.is_active.is_(True))
                    .limit(2)
                )
            ).all()
        )
        return str(codes[0]) if len(codes) == 1 else None

    async def one_c_branch_code_map(
        self, tenant_id: UUID, connection_id: UUID
    ) -> dict[str, str]:
        """Match 1C structural units to Revora branches by their human names.

        A mapping is returned only for an unambiguous match. This intentionally
        fails closed: an unknown 1C unit must never be silently assigned to the
        default branch of a multi-branch clinic.
        """

        branches = list(
            (
                await self.session.scalars(
                    select(Branch).where(
                        Branch.tenant_id == tenant_id, Branch.is_active.is_(True)
                    )
                )
            ).all()
        )
        units = list(
            (
                await self.session.scalars(
                    select(RawRecord).where(
                        RawRecord.tenant_id == tenant_id,
                        RawRecord.connection_id == connection_id,
                        RawRecord.source_entity == "Catalog_СтруктурныеЕдиницы",
                    )
                )
            ).all()
        )
        mapping: dict[str, str] = {}
        normalized_branches = [
            (
                branch,
                self._normalize_branch_name(branch.name),
                self._normalize_branch_name(branch.code),
            )
            for branch in branches
        ]
        for unit in units:
            payload = dict(unit.payload or {})
            key = str(payload.get("Ref_Key") or "").strip().lower()
            unit_name = self._normalize_branch_name(payload.get("Description"))
            if not key or not unit_name:
                continue
            matches = [
                branch
                for branch, branch_name, branch_code in normalized_branches
                if self._branch_matches_unit(
                    unit_name,
                    branch_name=branch_name,
                    branch_code=branch_code,
                )
            ]
            if len(matches) == 1:
                mapping[key] = str(matches[0].code)
        return mapping

    async def one_c_branch_mapping_details(
        self, tenant_id: UUID, connection_id: UUID
    ) -> list[tuple[str, str, str]]:
        mapping = await self.one_c_branch_code_map(tenant_id, connection_id)
        if not mapping:
            return []
        units = list(
            (
                await self.session.scalars(
                    select(RawRecord).where(
                        RawRecord.tenant_id == tenant_id,
                        RawRecord.connection_id == connection_id,
                        RawRecord.source_entity == "Catalog_СтруктурныеЕдиницы",
                    )
                )
            ).all()
        )
        details: list[tuple[str, str, str]] = []
        for unit in units:
            payload = dict(unit.payload or {})
            key = str(payload.get("Ref_Key") or "").strip().lower()
            if key in mapping:
                details.append(
                    (key, str(payload.get("Description") or key), mapping[key])
                )
        return sorted(details, key=lambda item: item[1].casefold())

    @staticmethod
    def _normalize_branch_name(value: object) -> str:
        text_value = unicodedata.normalize("NFKD", str(value or "")).casefold()
        return re.sub(r"[^a-zа-я0-9]+", "", text_value)

    @classmethod
    def _branch_matches_unit(
        cls, unit_name: str, *, branch_name: str, branch_code: str
    ) -> bool:
        """Match 1C Cyrillic names to stable Latin branch codes, fail closed."""

        unit_aliases = {unit_name, cls._transliterate_branch_name(unit_name)}
        branch_aliases = {branch_name, branch_code}
        return any(
            branch_alias
            and unit_alias
            and (
                branch_alias == unit_alias
                or branch_alias in unit_alias
                or unit_alias in branch_alias
            )
            for branch_alias in branch_aliases
            for unit_alias in unit_aliases
        )

    @staticmethod
    def _transliterate_branch_name(value: str) -> str:
        table = str.maketrans(
            {
                "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
                "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
                "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
                "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
                "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
                "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
                "э": "e", "ю": "yu", "я": "ya",
            }
        )
        return value.translate(table)

    @staticmethod
    def _chunks(values: list[UUID], size: int = 20000):
        # reset_one_c_records_for_reprocessing() can touch 100k+ ids in one
        # call (e.g. every Document_Прием_Лечение row). Each chunk is one
        # network round trip to Postgres; a small chunk size turned that
        # into hundreds of sequential round trips, which was slow enough on
        # its own to make the whole request time out even after the fix
        # that stopped loading full record payloads. Postgres has no
        # practical trouble with a 20k-item IN(...) list for a plain
        # UPDATE, so a much bigger chunk trades a larger single query for
        # far fewer round trips.
        for index in range(0, len(values), size):
            yield values[index : index + size]

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
            if source_record_id:
                previous_ids = select(RawRecord.id).where(
                    RawRecord.tenant_id == tenant_id,
                    RawRecord.connection_id == connection_id,
                    RawRecord.source_entity == source_entity,
                    RawRecord.source_record_id == source_record_id,
                    RawRecord.id != created.id,
                    RawRecord.status != "superseded",
                )
                await self.session.execute(
                    update(NormalizationError)
                    .where(
                        NormalizationError.raw_record_id.in_(previous_ids),
                        NormalizationError.status == "open",
                    )
                    .values(status="resolved", resolved_at=datetime.now(UTC))
                )
                await self.session.execute(
                    update(RawRecord)
                    .where(RawRecord.id.in_(previous_ids))
                    .values(status="superseded")
                )
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

    async def bulk_store_raw_records(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
        source_entity: str,
        source_schema_version: str | None,
        records: list[dict[str, object]],
    ) -> int:
        """Insert a connector batch in one database round trip.

        ``records`` contains precomputed ``source_record_id``, ``record_hash``
        and ``payload`` keys. Conflicting hashes are already present and are
        deliberately ignored. Older versions of newly inserted source
        identities are superseded in two set-based updates.
        """
        if not records:
            return 0
        values = [
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "sync_run_id": sync_run_id,
                "source_entity": source_entity,
                "source_record_id": item["source_record_id"],
                "source_schema_version": source_schema_version,
                "record_hash": item["record_hash"],
                "payload": item["payload"],
                "status": "pending",
            }
            for item in records
        ]
        statement = (
            insert(RawRecord)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "connection_id", "source_entity", "record_hash"]
            )
            .returning(RawRecord.id, RawRecord.source_record_id)
        )
        inserted = list((await self.session.execute(statement)).all())
        inserted_ids = [row.id for row in inserted]
        source_ids = [row.source_record_id for row in inserted if row.source_record_id]
        if inserted_ids and source_ids:
            previous_ids = select(RawRecord.id).where(
                RawRecord.tenant_id == tenant_id,
                RawRecord.connection_id == connection_id,
                RawRecord.source_entity == source_entity,
                RawRecord.source_record_id.in_(source_ids),
                RawRecord.id.notin_(inserted_ids),
                RawRecord.status != "superseded",
            )
            await self.session.execute(
                update(NormalizationError)
                .where(
                    NormalizationError.raw_record_id.in_(previous_ids),
                    NormalizationError.status == "open",
                )
                .values(status="resolved", resolved_at=datetime.now(UTC))
            )
            await self.session.execute(
                update(RawRecord)
                .where(RawRecord.id.in_(previous_ids))
                .values(status="superseded")
            )
        return len(inserted)

    async def quarantine(
        self,
        *,
        tenant_id: UUID,
        raw_record: RawRecord,
        mapping_profile_id: UUID | None,
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
