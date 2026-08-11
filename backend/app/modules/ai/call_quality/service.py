"""Business rules for owner-managed, versioned call scoring."""
from datetime import UTC, date, datetime, time
from uuid import UUID
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.ai.call_quality.models import CallQualityAnalysis, CallQualityRuleSet
from app.modules.ai.call_quality.schemas import (
    CallAnalysisResponse, CallerContactItem, CallerContactListResponse,
    CallerContactSummary, CallListItem, CallListResponse, CallQualityStatusResponse,
    OperatorPerformanceItem, OperatorPerformanceResponse, RuleSetRequest, RuleSetResponse,
)
from app.modules.auth.models import User, UserRole
from app.modules.sales.models import Call
from app.modules.kcell.models import KcellWebhookReceipt


class CallQualityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _owner(user: User) -> None:
        if user.role != UserRole.OWNER:
            raise AppError("FORBIDDEN", "Only the owner can manage call quality control", 403)

    async def status(self, user: User) -> CallQualityStatusResponse:
        self._owner(user)
        rules = await self.session.scalar(select(CallQualityRuleSet).where(CallQualityRuleSet.tenant_id == user.tenant_id, CallQualityRuleSet.is_active.is_(True)).order_by(CallQualityRuleSet.version.desc()))
        calls_received = await self.session.scalar(select(func.count()).select_from(Call).where(Call.tenant_id == user.tenant_id)) or 0
        analyses_ready = await self.session.scalar(select(func.count()).select_from(CallQualityAnalysis).where(CallQualityAnalysis.tenant_id == user.tenant_id, CallQualityAnalysis.status == "ready")) or 0
        status_rows = dict((await self.session.execute(
            select(CallQualityAnalysis.status, func.count())
            .where(CallQualityAnalysis.tenant_id == user.tenant_id)
            .group_by(CallQualityAnalysis.status)
        )).all())
        return CallQualityStatusResponse(
            rule_set=self._response(rules) if rules else None,
            calls_received=calls_received,
            analyses_ready=analyses_ready,
            integration_status="connected" if calls_received else "waiting_for_kcell",
            queued=sum(status_rows.get(item, 0) for item in ("pending", "queued", "retrying", "waiting_for_recording")),
            processing=status_rows.get("processing", 0),
            needs_review=status_rows.get("needs_review", 0),
            failed=status_rows.get("failed", 0),
        )

    async def create_rule_set(self, user: User, payload: RuleSetRequest) -> RuleSetResponse:
        self._owner(user)
        total_weight = sum(item.weight for item in payload.criteria)
        if total_weight != 100:
            raise AppError("INVALID_WEIGHTS", "The total criterion weight must equal 100", 422)
        version = (await self.session.scalar(select(func.max(CallQualityRuleSet.version)).where(CallQualityRuleSet.tenant_id == user.tenant_id))) or 0
        await self.session.execute(update(CallQualityRuleSet).where(CallQualityRuleSet.tenant_id == user.tenant_id, CallQualityRuleSet.is_active.is_(True)).values(is_active=False))
        item = CallQualityRuleSet(tenant_id=user.tenant_id, version=version + 1, created_by_id=user.id, name=payload.name, success_definition=payload.success_definition, partial_success_definition=payload.partial_success_definition, loss_definition=payload.loss_definition, criteria=[criterion.model_dump() for criterion in payload.criteria], loss_reasons=payload.loss_reasons, is_active=True)
        self.session.add(item)
        await self.session.flush()
        return self._response(item)

    async def list_calls(
        self,
        user: User,
        *,
        page: int,
        page_size: int,
        extension: str | None = None,
        direction: str | None = None,
        outcome: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        duration_min: int | None = None,
        duration_max: int | None = None,
        phone: str | None = None,
        sort_by: str = "started_at",
        sort_order: str = "desc",
    ) -> CallListResponse:
        self._owner(user)
        filters = [Call.tenant_id == user.tenant_id]
        if extension:
            filters.append(Call.external_user == extension)
        if direction:
            filters.append(Call.direction == direction)
        if outcome:
            filters.append(Call.outcome == outcome)
        if date_from:
            filters.append(
                Call.started_at >= datetime.combine(date_from, time.min, tzinfo=UTC)
            )
        if date_to:
            filters.append(
                Call.started_at <= datetime.combine(date_to, time.max, tzinfo=UTC)
            )
        if duration_min is not None:
            filters.append(Call.duration_seconds >= duration_min)
        if duration_max is not None:
            filters.append(Call.duration_seconds <= duration_max)
        order_columns = {
            "started_at": Call.started_at,
            "duration": Call.duration_seconds,
            "extension": Call.external_user,
            "outcome": Call.outcome,
        }
        order_column = order_columns.get(sort_by, Call.started_at)
        order_expression = order_column.asc() if sort_order == "asc" else order_column.desc()
        statement = (
            select(Call, CallQualityAnalysis, KcellWebhookReceipt.payload)
            .outerjoin(
                CallQualityAnalysis,
                (CallQualityAnalysis.call_id == Call.id)
                & (CallQualityAnalysis.tenant_id == user.tenant_id),
            )
            .outerjoin(
                KcellWebhookReceipt,
                (KcellWebhookReceipt.tenant_id == user.tenant_id)
                & (KcellWebhookReceipt.call_id == Call.external_id)
                & (KcellWebhookReceipt.command == "history"),
            )
            .where(*filters)
            .order_by(order_expression, Call.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(statement)).all()
        if phone:
            needle = "".join(character for character in phone if character.isdigit())
            rows = [
                row for row in rows
                if needle in "".join(
                    character for character in str((row.payload or {}).get("phone", ""))
                    if character.isdigit()
                )
            ]
        items = [
            CallListItem(
                id=call.id,
                started_at=call.started_at,
                direction=call.direction,
                employee=call.external_user,
                phone_masked=call.phone_masked,
                phone_number=str((payload or {}).get("phone") or "") or None,
                duration_seconds=call.duration_seconds,
                outcome=call.outcome,
                recording_url=call.recording_url,
                analysis_status=analysis.status if analysis else None,
                score=analysis.score if analysis else None,
                result=analysis.result if analysis else None,
                summary=analysis.summary if analysis else None,
                needs_review=analysis.needs_review if analysis else False,
                error_code=analysis.error_code if analysis else None,
            )
            for call, analysis, payload in rows
        ]
        total = await self.session.scalar(
            select(func.count()).select_from(Call).where(*filters)
        ) or 0
        option_rows = (
            await self.session.execute(
                select(Call.external_user, Call.direction, Call.outcome)
                .where(Call.tenant_id == user.tenant_id)
                .distinct()
            )
        ).all()
        return CallListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=max(1, (total + page_size - 1) // page_size),
            available_extensions=sorted(
                {row.external_user for row in option_rows if row.external_user}
            ),
            available_directions=sorted(
                {row.direction for row in option_rows if row.direction}
            ),
            available_outcomes=sorted(
                {row.outcome for row in option_rows if row.outcome}
            ),
        )

    async def caller_contacts(
        self,
        user: User,
        *,
        page: int,
        page_size: int,
        date_from: date | None = None,
        date_to: date | None = None,
        search: str | None = None,
        contact_type: str | None = None,
        sort_by: str = "last_call_at",
        sort_order: str = "desc",
    ) -> CallerContactListResponse:
        self._owner(user)
        filters = [Call.tenant_id == user.tenant_id]
        if date_from:
            filters.append(Call.started_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
        if date_to:
            filters.append(Call.started_at <= datetime.combine(date_to, time.max, tzinfo=UTC))
        rows = (await self.session.execute(
            select(Call, KcellWebhookReceipt.payload)
            .join(
                KcellWebhookReceipt,
                (KcellWebhookReceipt.tenant_id == user.tenant_id)
                & (KcellWebhookReceipt.call_id == Call.external_id)
                & (KcellWebhookReceipt.command == "history"),
            )
            .where(*filters)
            .order_by(Call.started_at.asc())
        )).all()
        contacts: dict[str, dict] = {}
        needle = "".join(character for character in (search or "") if character.isdigit())
        for call, payload in rows:
            raw_phone = str((payload or {}).get("phone") or "").strip()
            digits = "".join(character for character in raw_phone if character.isdigit())
            if not digits or (needle and needle not in digits):
                continue
            phone_number = digits
            item = contacts.setdefault(phone_number, {
                "phone_number": phone_number,
                "call_count": 0,
                "qualified_calls": 0,
                "first_call_at": call.started_at,
                "last_call_at": call.started_at,
                "first_call_duration_seconds": call.duration_seconds,
                "total_duration_seconds": 0,
                "last_outcome": call.outcome,
                "extensions": set(),
            })
            item["call_count"] += 1
            duration = int(call.duration_seconds or 0)
            item["total_duration_seconds"] += duration
            if duration > 20 and call.outcome == "Success":
                item["qualified_calls"] += 1
            if call.started_at >= item["last_call_at"]:
                item["last_call_at"] = call.started_at
                item["last_outcome"] = call.outcome
            if call.external_user:
                item["extensions"].add(call.external_user)
        prepared = []
        for value in contacts.values():
            value["extensions"] = sorted(value["extensions"])
            value["contact_type"] = "repeat" if value["call_count"] > 1 else "first"
            if not contact_type or value["contact_type"] == contact_type:
                prepared.append(CallerContactItem(**value))
        sort_fields = {
            "last_call_at": lambda item: item.last_call_at,
            "first_call_at": lambda item: item.first_call_at,
            "call_count": lambda item: item.call_count,
            "duration": lambda item: item.total_duration_seconds,
            "phone": lambda item: item.phone_number,
        }
        prepared.sort(key=sort_fields.get(sort_by, sort_fields["last_call_at"]), reverse=sort_order != "asc")
        summary = CallerContactSummary(
            unique_contacts=len(contacts),
            first_only=sum(1 for item in contacts.values() if item["call_count"] == 1),
            repeat_contacts=sum(1 for item in contacts.values() if item["call_count"] > 1),
            total_calls=sum(item["call_count"] for item in contacts.values()),
            qualified_calls=sum(item["qualified_calls"] for item in contacts.values()),
        )
        total = len(prepared)
        start = (page - 1) * page_size
        return CallerContactListResponse(
            items=prepared[start:start + page_size], summary=summary, total=total,
            page=page, page_size=page_size, pages=max(1, (total + page_size - 1) // page_size),
        )

    async def analysis(self, user: User, call_id: UUID) -> CallAnalysisResponse:
        self._owner(user)
        item = await self.session.scalar(
            select(CallQualityAnalysis).where(
                CallQualityAnalysis.tenant_id == user.tenant_id,
                CallQualityAnalysis.call_id == call_id,
            )
        )
        if item is None:
            raise AppError("CALL_ANALYSIS_NOT_FOUND", "Call analysis not found", 404)
        return self._analysis_response(item)

    async def reanalyze(self, user: User, call_id: UUID) -> CallAnalysisResponse:
        self._owner(user)
        row = await self.session.execute(
            select(Call, CallQualityAnalysis)
            .join(CallQualityAnalysis, CallQualityAnalysis.call_id == Call.id)
            .where(Call.tenant_id == user.tenant_id, Call.id == call_id)
            .with_for_update()
        )
        pair = row.first()
        if pair is None:
            raise AppError("CALL_ANALYSIS_NOT_FOUND", "Call analysis not found", 404)
        call, item = pair
        if not call.recording_url:
            raise AppError("CALL_RECORDING_MISSING", "The original recording is no longer available", 409)
        item.status = "queued"
        item.queued_at = datetime.now(UTC)
        item.processing_started_at = None
        item.completed_at = None
        item.error_code = None
        item.error_message = None
        item.needs_review = False
        item.result = None
        item.score = None
        item.summary = None
        item.criteria_scores = None
        item.strengths = None
        item.loss_reasons = None
        item.recommendations = None
        item.flags = None
        item.evidence = None
        item.languages = None
        item.mixed_language = None
        item.confidence = None
        return self._analysis_response(item)

    async def operator_performance(
        self, user: User, date_from: date | None, date_to: date | None
    ) -> OperatorPerformanceResponse:
        self._owner(user)
        statement = (
            select(
                func.coalesce(Call.external_user, "Не определён").label("employee"),
                func.count(CallQualityAnalysis.id).label("calls_analyzed"),
                func.avg(CallQualityAnalysis.score).label("average_score"),
                func.sum(case((CallQualityAnalysis.result == "success", 1), else_=0)).label("successful_calls"),
                func.sum(case((CallQualityAnalysis.needs_review.is_(True), 1), else_=0)).label("needs_review"),
            )
            .join(CallQualityAnalysis, CallQualityAnalysis.call_id == Call.id)
            .where(
                Call.tenant_id == user.tenant_id,
                CallQualityAnalysis.status.in_(("ready", "needs_review")),
            )
            .group_by(Call.external_user)
            .order_by(func.avg(CallQualityAnalysis.score).desc())
        )
        if date_from:
            statement = statement.where(Call.started_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
        if date_to:
            statement = statement.where(Call.started_at <= datetime.combine(date_to, time.max, tzinfo=UTC))
        rows = (await self.session.execute(statement)).all()
        items = [
            OperatorPerformanceItem(
                employee=row.employee,
                calls_analyzed=row.calls_analyzed,
                average_score=round(float(row.average_score or 0), 1),
                successful_calls=int(row.successful_calls or 0),
                success_rate=round(100 * int(row.successful_calls or 0) / row.calls_analyzed, 1),
                needs_review=int(row.needs_review or 0),
            )
            for row in rows
        ]
        return OperatorPerformanceResponse(date_from=date_from, date_to=date_to, items=items)

    @staticmethod
    def _response(item: CallQualityRuleSet) -> RuleSetResponse:
        return RuleSetResponse(id=item.id, version=item.version, name=item.name, success_definition=item.success_definition, partial_success_definition=item.partial_success_definition, loss_definition=item.loss_definition, criteria=item.criteria, loss_reasons=item.loss_reasons, is_active=item.is_active, created_at=item.created_at)

    @staticmethod
    def _analysis_response(item: CallQualityAnalysis) -> CallAnalysisResponse:
        return CallAnalysisResponse(
            id=item.id,
            call_id=item.call_id,
            status=item.status,
            result=item.result,
            score=item.score,
            summary=item.summary,
            criteria_scores=item.criteria_scores or [],
            strengths=item.strengths or [],
            loss_reasons=item.loss_reasons or [],
            recommendations=item.recommendations or [],
            flags=item.flags or {},
            evidence=item.evidence or [],
            languages=item.languages or [],
            mixed_language=item.mixed_language,
            confidence=item.confidence,
            needs_review=item.needs_review,
            attempt_count=item.attempt_count,
            error_code=item.error_code,
            model_version=item.model_version,
            completed_at=item.completed_at,
        )
