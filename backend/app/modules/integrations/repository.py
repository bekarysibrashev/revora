"""Persistence for connections, raw rows, mapping and normalization state."""

from datetime import UTC, datetime
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy import Numeric, case, cast, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations.models import (
    IntegrationConnection,
    MappingProfile,
    NormalizationError,
    OneCMetadataSnapshot,
    RawRecord,
    RecordLineage,
    SyncRun,
)
from app.modules.finance.models import CashFlowFact, ExpenseFact, PayrollFact, RevenueFact
from app.modules.integrations.one_c_finance import (
    EXPENSE_ENTITY,
    MONEY_ENTITY,
    PAYROLL_ENTITY,
    PAYROLL_REGISTER_ENTITY,
    REVENUE_ENTITY,
    SALES_ENTITY,
    one_c_finance_external_id,
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

    async def upsert_one_c_metadata(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        schema_version: str,
        fingerprint: str,
        entities: list[dict[str, object]],
        discovered_at: datetime,
    ) -> OneCMetadataSnapshot:
        statement = insert(OneCMetadataSnapshot).values(
            id=uuid4(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            schema_version=schema_version,
            fingerprint=fingerprint,
            entities=entities,
            discovered_at=discovered_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["tenant_id", "connection_id"],
            set_={
                "schema_version": statement.excluded.schema_version,
                "fingerprint": statement.excluded.fingerprint,
                "entities": statement.excluded.entities,
                "discovered_at": statement.excluded.discovered_at,
                "updated_at": func.now(),
            },
        ).returning(OneCMetadataSnapshot)
        return (await self.session.execute(statement)).scalar_one()

    async def get_one_c_metadata(
        self, tenant_id: UUID, connection_id: UUID
    ) -> OneCMetadataSnapshot | None:
        return await self.session.scalar(
            select(OneCMetadataSnapshot).where(
                OneCMetadataSnapshot.tenant_id == tenant_id,
                OneCMetadataSnapshot.connection_id == connection_id,
            )
        )

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
        connection.status = "connected"
        await self.session.flush()

    async def raw_record_counts(
        self, tenant_id: UUID, connection_id: UUID
    ) -> list[tuple[str, int]]:
        rows = await self.session.execute(
            select(RawRecord.source_entity, func.count(RawRecord.id))
            .where(
                RawRecord.tenant_id == tenant_id,
                RawRecord.connection_id == connection_id,
            )
            .group_by(RawRecord.source_entity)
            .order_by(RawRecord.source_entity)
        )
        return [(str(entity), int(count)) for entity, count in rows.all()]

    async def raw_record_status_counts(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        *,
        source_entities: tuple[str, ...] | None = None,
        period_from: datetime | None = None,
    ) -> dict[str, int]:
        conditions = [
            RawRecord.tenant_id == tenant_id,
            RawRecord.connection_id == connection_id,
        ]
        if source_entities:
            conditions.append(RawRecord.source_entity.in_(source_entities))
        if period_from:
            conditions.append(self._one_c_history_condition(period_from))
        rows = await self.session.execute(
            select(RawRecord.status, func.count(RawRecord.id))
            .where(*conditions)
            .group_by(RawRecord.status)
        )
        return {str(status): int(count) for status, count in rows.all()}

    async def one_c_quarantine_reasons(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        *,
        source_entities: tuple[str, ...],
        period_from: datetime,
        limit: int = 20,
    ) -> list[tuple[str, str, str | None, str, int]]:
        rows = await self.session.execute(
            select(
                RawRecord.source_entity,
                NormalizationError.error_code,
                NormalizationError.field_name,
                NormalizationError.message,
                func.count(func.distinct(RawRecord.id)).label("records"),
            )
            .join(
                NormalizationError,
                NormalizationError.raw_record_id == RawRecord.id,
            )
            .where(
                RawRecord.tenant_id == tenant_id,
                RawRecord.connection_id == connection_id,
                RawRecord.source_entity.in_(source_entities),
                RawRecord.status == "quarantined",
                NormalizationError.status == "open",
                self._one_c_history_condition(period_from),
            )
            .group_by(
                RawRecord.source_entity,
                NormalizationError.error_code,
                NormalizationError.field_name,
                NormalizationError.message,
            )
            .order_by(func.count(func.distinct(RawRecord.id)).desc())
            .limit(limit)
        )
        return [
            (str(entity), str(code), field, str(message), int(count))
            for entity, code, field, message, count in rows.all()
        ]

    async def one_c_source_summaries(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        *,
        period_from: datetime,
    ) -> list[tuple[str, str, str, int, object]]:
        """Return non-PII control totals for mapped SAN branches from raw 1C rows."""

        definitions = (
            (REVENUE_ENTITY, "Месяц / вид операции", "Сумма"),
            (SALES_ENTITY, "Месяц", "Стоимость"),
            (PAYROLL_ENTITY, "Месяц начисления / документы", "СуммаДокумента"),
            (PAYROLL_REGISTER_ENTITY, "Месяц начисления / движение", "Сумма"),
        )
        mapped_structure_keys = tuple(
            (await self.one_c_branch_code_map(tenant_id, connection_id)).keys()
        )
        if not mapped_structure_keys:
            return []
        summaries: list[tuple[str, str, str, int, object]] = []
        for entity, dimension, amount_field in definitions:
            if entity == REVENUE_ENTITY:
                value_expression = func.concat(
                    func.substr(RawRecord.payload["Period"].astext, 1, 7),
                    " · ",
                    func.coalesce(RawRecord.payload["ВидОперации"].astext, "(не указано)"),
                )
            elif entity == SALES_ENTITY:
                value_expression = func.substr(RawRecord.payload["Period"].astext, 1, 7)
            elif entity == PAYROLL_ENTITY:
                value_expression = func.concat(
                    func.substr(
                        func.coalesce(
                            RawRecord.payload["ДатаОкончанияПериода"].astext,
                            RawRecord.payload["Date"].astext,
                        ),
                        1,
                        7,
                    ),
                    " · документы",
                )
            else:
                value_expression = func.concat(
                    func.substr(
                        func.coalesce(
                            RawRecord.payload["МесяцНачисления"].astext,
                            RawRecord.payload["Period"].astext,
                        ),
                        1,
                        7,
                    ),
                    " · ",
                    func.coalesce(RawRecord.payload["RecordType"].astext, "(не указано)"),
                )
            amount_expression = cast(
                func.nullif(RawRecord.payload[amount_field].astext, ""), Numeric(20, 2)
            )
            rows = await self.session.execute(
                select(
                    value_expression,
                    func.count(RawRecord.id),
                    func.coalesce(func.sum(amount_expression), 0),
                )
                .where(
                    RawRecord.tenant_id == tenant_id,
                    RawRecord.connection_id == connection_id,
                    RawRecord.source_entity == entity,
                    RawRecord.status != "superseded",
                    func.lower(RawRecord.payload["СтруктурнаяЕдиница_Key"].astext).in_(
                        mapped_structure_keys
                    ),
                    self._one_c_history_condition(period_from),
                )
                .group_by(value_expression)
                .order_by(value_expression)
            )
            summaries.extend(
                (entity, dimension, str(value), int(count), amount)
                for value, count, amount in rows.all()
            )
        return summaries

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

    async def pending_one_c_records(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        source_entities: tuple[str, ...],
        period_from: datetime,
        limit: int,
    ) -> list[RawRecord]:
        dependency_order = case(
            {
                "Catalog_СтруктурныеЕдиницы": 0,
                "Catalog_Контрагенты": 1,
                "Catalog_Сотрудники": 1,
                "Catalog_Номенклатура": 1,
                "Document_Событие": 2,
                "AccumulationRegister_Продажи_RecordType": 3,
                "AccumulationRegister_Выручка_RecordType": 4,
                "AccumulationRegister_РасчетыСПерсоналом_RecordType": 4,
                "Document_НачислениеЗарплаты": 5,
            },
            value=RawRecord.source_entity,
            else_=10,
        )
        return list(
            (
                await self.session.scalars(
                    select(RawRecord)
                    .where(
                        RawRecord.tenant_id == tenant_id,
                        RawRecord.connection_id == connection_id,
                        RawRecord.source_entity.in_(source_entities),
                        RawRecord.status == "pending",
                        self._one_c_history_condition(period_from),
                    )
                    .order_by(dependency_order, RawRecord.received_at, RawRecord.id)
                    .limit(limit)
                )
            ).all()
        )

    async def pending_one_c_record_count(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        source_entities: tuple[str, ...],
        period_from: datetime,
    ) -> int:
        count = await self.session.scalar(
            select(func.count(RawRecord.id)).where(
                RawRecord.tenant_id == tenant_id,
                RawRecord.connection_id == connection_id,
                RawRecord.source_entity.in_(source_entities),
                RawRecord.status == "pending",
                self._one_c_history_condition(period_from),
            )
        )
        return int(count or 0)

    async def reset_one_c_records_for_reprocessing(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        source_entities: tuple[str, ...],
        period_from: datetime,
    ) -> int:
        records = list(
            (
                await self.session.scalars(
                    select(RawRecord).where(
                        RawRecord.tenant_id == tenant_id,
                        RawRecord.connection_id == connection_id,
                        RawRecord.source_entity.in_(source_entities),
                        self._one_c_history_condition(period_from),
                    )
                )
            ).all()
        )
        latest_ids, superseded_ids = self._latest_one_c_record_versions(records)
        all_ids = [record.id for record in records]

        for chunk in self._chunks(latest_ids):
            await self.session.execute(
                update(RawRecord)
                .where(RawRecord.id.in_(chunk))
                .values(status="pending")
                .execution_options(synchronize_session=False)
            )
        for chunk in self._chunks(superseded_ids):
            await self.session.execute(
                update(RawRecord)
                .where(RawRecord.id.in_(chunk))
                .values(status="superseded")
                .execution_options(synchronize_session=False)
            )
        for chunk in self._chunks(all_ids):
            await self.session.execute(
                update(NormalizationError)
                .where(
                    NormalizationError.raw_record_id.in_(chunk),
                    NormalizationError.status == "open",
                )
                .values(status="resolved", resolved_at=datetime.now(UTC))
                .execution_options(synchronize_session=False)
            )
        await self.session.flush()
        return len(latest_ids)

    async def remove_one_c_canonical_record(
        self,
        *,
        tenant_id: UUID,
        source_entity: str,
        source_record_id: str,
    ) -> None:
        """Remove the prior canonical value immediately before rebuilding it.

        The delete and replacement write run in one request transaction. If a
        newer source version is quarantined, a stale older amount cannot remain
        visible in analytics.
        """

        model_by_entity = {
            REVENUE_ENTITY: RevenueFact,
            SALES_ENTITY: RevenueFact,
            MONEY_ENTITY: CashFlowFact,
            EXPENSE_ENTITY: ExpenseFact,
            PAYROLL_ENTITY: PayrollFact,
            PAYROLL_REGISTER_ENTITY: PayrollFact,
        }
        model = model_by_entity.get(source_entity)
        if model is None:
            return
        external_id = one_c_finance_external_id(source_entity, source_record_id)
        await self.session.execute(
            delete(model).where(
                model.tenant_id == tenant_id,
                model.external_id == external_id,
            )
        )

    @staticmethod
    def _latest_one_c_record_versions(
        records: list[RawRecord],
    ) -> tuple[list[UUID], list[UUID]]:
        latest: dict[tuple[str, str], RawRecord] = {}
        for record in records:
            identity = record.source_record_id or record.record_hash or str(record.id)
            key = (record.source_entity, identity)
            current = latest.get(key)
            record_order = (record.received_at or record.created_at, str(record.id))
            current_order = (
                (current.received_at or current.created_at, str(current.id))
                if current is not None
                else None
            )
            if current_order is None or record_order > current_order:
                latest[key] = record
        latest_ids = {record.id for record in latest.values()}
        return (
            list(latest_ids),
            [record.id for record in records if record.id not in latest_ids],
        )

    @staticmethod
    def _chunks(values: list[UUID], size: int = 1000):
        for index in range(0, len(values), size):
            yield values[index : index + size]

    @staticmethod
    def _one_c_history_condition(period_from: datetime):
        period_text = period_from.replace(tzinfo=None).isoformat(timespec="seconds")
        business_date = func.coalesce(
            RawRecord.payload["Period"].astext,
            RawRecord.payload["Date"].astext,
            RawRecord.payload["Дата"].astext,
            RawRecord.payload["ДатаСоздания"].astext,
        )
        # Catalogs are dependencies for documents and usually have no business
        # period. They must be available before appointments are retried.
        return or_(
            RawRecord.source_entity.startswith("Catalog_", autoescape=True),
            business_date >= period_text,
        )

    async def mark_raw_normalized(self, raw_record: RawRecord) -> None:
        raw_record.status = "normalized"
        await self.session.flush()

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
