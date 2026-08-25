"""Application orchestration for source ingestion and canonical loading."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import secrets
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.integrations.adapter import IntegrationAdapter
from app.modules.integrations.canonical_writer import CanonicalWriteError, CanonicalWriter
from app.modules.integrations.mapper import CanonicalMapper, compute_record_hash
from app.modules.integrations.one_c import (
    InvalidConnectorToken,
    ONE_C_PROVIDER,
    SAFE_ONE_C_ENTITIES,
    SAFE_ONE_C_FIELDS,
    connector_token_digest,
    issue_connector_token,
    parse_connector_token,
    source_record_id,
)
from app.modules.integrations.one_c_finance import (
    EXPENSE_ENTITY,
    MAPPABLE_ONE_C_ENTITIES as MAPPABLE_ONE_C_FINANCE_ENTITIES,
    MONEY_ENTITY,
    PAYROLL_ENTITY,
    PAYROLL_REGISTER_ENTITY,
    REVENUE_ENTITY,
    SALES_ENTITY,
    normalize_one_c_finance_record,
)
from app.modules.integrations.one_c_operational import (
    APPOINTMENT_ENTITY,
    LEAD_ENTITY,
    MAPPABLE_OPERATIONAL_ENTITIES,
    normalize_one_c_operational_record,
)
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.schemas import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionSyncStatusResponse,
    EntitySyncCount,
    IngestionSummaryResponse,
    MappingDefinition,
    MappingIssue,
    MappingProfileListResponse,
    MappingProfileResponse,
    OneCConnectorTokenResponse,
    OneCNormalizeRequest,
    OneCNormalizeResponse,
    OneCMetadataRequest,
    OneCMetadataResponse,
    OneCBranchMapping,
    OneCPushRequest,
    OneCPushResponse,
)
from app.modules.integrations.tabular_adapter import InvalidTabularFile, UnsupportedTabularFile


MAPPABLE_ONE_C_ENTITIES = (*MAPPABLE_ONE_C_FINANCE_ENTITIES, *MAPPABLE_OPERATIONAL_ENTITIES)
REPROCESSABLE_ONE_C_ENTITIES = (
    REVENUE_ENTITY,
    MONEY_ENTITY,
    EXPENSE_ENTITY,
    SALES_ENTITY,
    PAYROLL_ENTITY,
    PAYROLL_REGISTER_ENTITY,
    LEAD_ENTITY,
    APPOINTMENT_ENTITY,
)


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
        settings = payload.settings
        status = "active"
        if payload.provider == ONE_C_PROVIDER:
            # Never accept 1C credentials from the browser. The clinic-side
            # connector keeps them protected by Windows DPAPI and talks only
            # to localhost OData.
            settings = {
                "mode": "local_push",
                "allowed_entities": list(SAFE_ONE_C_ENTITIES),
            }
            status = "awaiting_setup"
        connection = await self.repository.create_connection(
            tenant_id=user.tenant_id,
            provider=payload.provider,
            name=payload.name,
            settings=settings,
            status=status,
        )
        return ConnectionResponse.model_validate(connection)

    async def rotate_one_c_connector_token(
        self, user: User, connection_id: UUID
    ) -> OneCConnectorTokenResponse:
        self._require_owner(user)
        connection = await self._connection(user.tenant_id, connection_id)
        if connection.provider != ONE_C_PROVIDER:
            raise AppError("INVALID_INTEGRATION_PROVIDER", "This is not a 1C connection", 422)
        token, digest = issue_connector_token(user.tenant_id, connection.id)
        settings = {
            **(connection.settings or {}),
            "mode": "local_push",
            "allowed_entities": list(SAFE_ONE_C_ENTITIES),
            "token_rotated_at": datetime.now(UTC).isoformat(),
        }
        await self.repository.configure_one_c_connector(
            connection, token_digest=digest, settings=settings
        )
        return OneCConnectorTokenResponse(
            connection_id=connection.id,
            token=token,
            allowed_entities=list(SAFE_ONE_C_ENTITIES),
        )

    async def one_c_sync_status(
        self, user: User, connection_id: UUID
    ) -> ConnectionSyncStatusResponse:
        self._require_owner(user)
        connection = await self._connection(user.tenant_id, connection_id)
        if connection.provider != ONE_C_PROVIDER:
            raise AppError("INVALID_INTEGRATION_PROVIDER", "This is not a 1C connection", 422)
        counts = await self.repository.raw_record_counts(user.tenant_id, connection.id)
        period_from = datetime.now(UTC) - timedelta(days=90)
        status_counts = await self.repository.raw_record_status_counts(
            user.tenant_id,
            connection.id,
            source_entities=MAPPABLE_ONE_C_ENTITIES,
            period_from=period_from,
        )
        settings = connection.settings or {}
        branch_mappings = await self.repository.one_c_branch_mapping_details(
            user.tenant_id, connection.id
        )
        last_synced_at = None
        if settings.get("last_synced_at"):
            try:
                last_synced_at = datetime.fromisoformat(str(settings["last_synced_at"]))
            except ValueError:
                last_synced_at = None
        return ConnectionSyncStatusResponse(
            connection_id=connection.id,
            status=connection.status,
            last_synced_at=last_synced_at,
            last_entity=str(settings["last_entity"]) if settings.get("last_entity") else None,
            total_records=sum(count for _, count in counts),
            pending_records=status_counts.get("pending", 0),
            normalized_records=status_counts.get("normalized", 0),
            quarantined_records=status_counts.get("quarantined", 0),
            entities=[EntitySyncCount(entity=entity, records=count) for entity, count in counts],
            branch_mappings=[
                OneCBranchMapping(
                    structural_unit_key=key,
                    structural_unit_name=name,
                    branch_code=branch_code,
                )
                for key, name, branch_code in branch_mappings
            ],
        )

    async def ingest_one_c_push(
        self, connector_token: str, payload: OneCPushRequest
    ) -> OneCPushResponse:
        parts, connection = await self._connector_connection(connector_token)

        allowed_entities = set(connection.settings.get("allowed_entities", []))
        if payload.entity not in allowed_entities:
            raise AppError(
                "ONE_C_ENTITY_NOT_ALLOWED",
                "This 1C entity is not approved for synchronization",
                403,
                {"entity": payload.entity},
            )
        approved_fields = SAFE_ONE_C_FIELDS.get(payload.entity)
        if approved_fields is None:
            raise AppError("ONE_C_ENTITY_NOT_ALLOWED", "This 1C entity has no field allowlist", 403)
        for record in payload.records:
            unexpected_fields = sorted(set(record) - approved_fields)
            if unexpected_fields:
                raise AppError(
                    "ONE_C_FIELDS_NOT_ALLOWED",
                    "This 1C batch contains fields outside the server allowlist",
                    422,
                    {"entity": payload.entity, "fields": unexpected_fields[:20]},
                )
        encoded_size = len(
            json.dumps(payload.records, ensure_ascii=False, default=str).encode("utf-8")
        )
        if encoded_size > 2 * 1024 * 1024:
            raise AppError("ONE_C_BATCH_TOO_LARGE", "1C batch exceeds 2 MB", 413)

        run = await self.repository.create_sync_run(parts.tenant_id, connection.id)
        stored = 0
        duplicates = 0
        normalized = 0
        quarantined = 0
        branch_code = (
            str(connection.settings["default_branch_code"])
            if connection.settings.get("default_branch_code")
            else await self.repository.single_active_branch_code(parts.tenant_id)
        )
        branch_code_map = await self.repository.one_c_branch_code_map(
            parts.tenant_id, connection.id
        )
        for record in payload.records:
            raw_record, created = await self.repository.store_raw_record(
                tenant_id=parts.tenant_id,
                connection_id=connection.id,
                sync_run_id=run.id,
                source_entity=payload.entity,
                source_record_id=source_record_id(record),
                source_schema_version=payload.schema_version,
                record_hash=compute_record_hash(payload.entity, record),
                payload=record,
            )
            if created:
                stored += 1
            else:
                duplicates += 1
            if raw_record.status == "pending":
                outcome = await self._normalize_one_c_raw_record(
                    tenant_id=parts.tenant_id,
                    raw_record=raw_record,
                    branch_code=self._one_c_record_branch_code(
                        record, branch_code_map, branch_code
                    ),
                )
                normalized += int(outcome == "normalized")
                quarantined += int(outcome == "quarantined")

        synced_at = datetime.now(UTC)
        await self.repository.finish_sync_run(
            run,
            status="completed",
            records_read=len(payload.records),
            records_written=stored,
        )
        await self.repository.mark_connection_synced(
            connection, entity=payload.entity, synced_at=synced_at
        )
        return OneCPushResponse(
            sync_run_id=run.id,
            status="completed",
            entity=payload.entity,
            records_received=len(payload.records),
            records_stored=stored,
            records_duplicate=duplicates,
            records_normalized=normalized,
            records_quarantined=quarantined,
        )

    async def ingest_one_c_metadata(
        self, connector_token: str, payload: OneCMetadataRequest
    ) -> OneCMetadataResponse:
        parts, connection = await self._connector_connection(connector_token)
        entities = [item.model_dump(mode="json") for item in payload.entities]
        encoded = json.dumps(entities, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(encoded) > 8 * 1024 * 1024:
            raise AppError("ONE_C_METADATA_TOO_LARGE", "1C metadata exceeds 8 MB", 413)
        fingerprint = sha256(encoded).hexdigest()
        discovered_at = datetime.now(UTC)
        snapshot = await self.repository.upsert_one_c_metadata(
            tenant_id=parts.tenant_id,
            connection_id=connection.id,
            schema_version=payload.schema_version,
            fingerprint=fingerprint,
            entities=entities,
            discovered_at=discovered_at,
        )
        connection.settings = {
            **(connection.settings or {}),
            "allowed_entities": list(SAFE_ONE_C_ENTITIES),
            "metadata_fingerprint": fingerprint,
            "metadata_discovered_at": discovered_at.isoformat(),
            "metadata_entity_count": len(entities),
        }
        property_count = sum(len(item.properties) for item in payload.entities)
        return OneCMetadataResponse(
            connection_id=connection.id,
            schema_version=snapshot.schema_version,
            fingerprint=snapshot.fingerprint,
            entity_count=len(entities),
            property_count=property_count,
            discovered_at=snapshot.discovered_at,
        )

    async def get_one_c_metadata(
        self, user: User, connection_id: UUID
    ) -> OneCMetadataRequest:
        self._require_owner(user)
        connection = await self._connection(user.tenant_id, connection_id)
        if connection.provider != ONE_C_PROVIDER:
            raise AppError("INVALID_INTEGRATION_PROVIDER", "This is not a 1C connection", 422)
        snapshot = await self.repository.get_one_c_metadata(user.tenant_id, connection.id)
        if snapshot is None:
            raise AppError("ONE_C_METADATA_NOT_FOUND", "1C metadata has not been discovered yet", 404)
        return OneCMetadataRequest(
            schema_version=snapshot.schema_version,
            entities=snapshot.entities,
        )

    async def _connector_connection(self, connector_token: str):
        try:
            parts = parse_connector_token(connector_token)
        except InvalidConnectorToken as exc:
            raise AppError("INVALID_CONNECTOR_TOKEN", "Invalid connector token", 401) from exc
        await self.repository.set_tenant_context(parts.tenant_id)
        connection = await self.repository.get_connection(parts.tenant_id, parts.connection_id)
        expected_digest = connection.encrypted_credentials if connection else None
        actual_digest = connector_token_digest(connector_token)
        if (
            connection is None
            or connection.provider != ONE_C_PROVIDER
            or not expected_digest
            or not secrets.compare_digest(expected_digest, actual_digest)
        ):
            raise AppError("INVALID_CONNECTOR_TOKEN", "Invalid connector token", 401)
        return parts, connection

    async def normalize_existing_one_c_records(
        self,
        user: User,
        connection_id: UUID,
        payload: OneCNormalizeRequest,
    ) -> OneCNormalizeResponse:
        self._require_owner(user)
        connection = await self._connection(user.tenant_id, connection_id)
        if connection.provider != ONE_C_PROVIDER:
            raise AppError("INVALID_INTEGRATION_PROVIDER", "This is not a 1C connection", 422)
        branch_code = (
            str(connection.settings["default_branch_code"])
            if connection.settings.get("default_branch_code")
            else await self.repository.single_active_branch_code(user.tenant_id)
        )
        branch_code_map = await self.repository.one_c_branch_code_map(
            user.tenant_id, connection.id
        )
        period_from = datetime.now(UTC) - timedelta(days=payload.history_days)
        reset = 0
        if payload.reset_existing:
            reset = await self.repository.reset_one_c_records_for_reprocessing(
                tenant_id=user.tenant_id,
                connection_id=connection.id,
                source_entities=REPROCESSABLE_ONE_C_ENTITIES,
                period_from=period_from,
            )
        records = await self.repository.pending_one_c_records(
            tenant_id=user.tenant_id,
            connection_id=connection.id,
            source_entities=MAPPABLE_ONE_C_ENTITIES,
            period_from=period_from,
            limit=payload.batch_size,
        )
        normalized = 0
        quarantined = 0
        for raw_record in records:
            outcome = await self._normalize_one_c_raw_record(
                tenant_id=user.tenant_id,
                raw_record=raw_record,
                branch_code=self._one_c_record_branch_code(
                    dict(raw_record.payload), branch_code_map, branch_code
                ),
            )
            normalized += int(outcome == "normalized")
            quarantined += int(outcome == "quarantined")
        remaining = await self.repository.pending_one_c_record_count(
            tenant_id=user.tenant_id,
            connection_id=connection.id,
            source_entities=MAPPABLE_ONE_C_ENTITIES,
            period_from=period_from,
        )
        return OneCNormalizeResponse(
            connection_id=connection.id,
            reset=reset,
            processed=len(records),
            normalized=normalized,
            quarantined=quarantined,
            remaining=remaining,
        )

    async def _normalize_one_c_raw_record(
        self,
        *,
        tenant_id: UUID,
        raw_record,
        branch_code: str | None,
    ) -> str:
        source_identity = raw_record.source_record_id or str(raw_record.id)
        await self.repository.remove_one_c_canonical_record(
            tenant_id=tenant_id,
            source_entity=raw_record.source_entity,
            source_record_id=source_identity,
        )
        mapping = normalize_one_c_operational_record(
            source_entity=raw_record.source_entity,
            source_record_id=source_identity,
            payload=dict(raw_record.payload),
            branch_code=branch_code,
        )
        if mapping is None:
            mapping = normalize_one_c_finance_record(
                source_entity=raw_record.source_entity,
                source_record_id=source_identity,
                payload=dict(raw_record.payload),
                branch_code=branch_code,
            )
        if mapping is None:
            return "skipped"
        if mapping.issues:
            await self.repository.quarantine(
                tenant_id=tenant_id,
                raw_record=raw_record,
                mapping_profile_id=None,
                issues=mapping.issues,
            )
            return "quarantined"
        try:
            await self.canonical_writer.write(
                tenant_id=tenant_id,
                target_entity=mapping.target_entity,
                data=mapping.data,
            )
        except CanonicalWriteError as exc:
            await self.repository.quarantine(
                tenant_id=tenant_id,
                raw_record=raw_record,
                mapping_profile_id=None,
                issues=[MappingIssue(code="ONE_C_CANONICAL_WRITE_FAILED", message=str(exc))],
            )
            return "quarantined"
        await self.repository.mark_raw_normalized(raw_record)
        return "normalized"

    @staticmethod
    def _one_c_record_branch_code(
        payload: dict[str, object],
        branch_code_map: dict[str, str],
        fallback_branch_code: str | None,
    ) -> str | None:
        structure_key = str(payload.get("СтруктурнаяЕдиница_Key") or "").strip().lower()
        empty_guid = "00000000-0000-0000-0000-000000000000"
        if structure_key and structure_key != empty_guid:
            return branch_code_map.get(structure_key)
        return fallback_branch_code

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
