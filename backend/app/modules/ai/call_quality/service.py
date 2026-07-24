"""Business rules for owner-managed, versioned call scoring."""
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.ai.call_quality.models import CallQualityAnalysis, CallQualityRuleSet
from app.modules.ai.call_quality.schemas import CallQualityStatusResponse, RuleSetRequest, RuleSetResponse
from app.modules.auth.models import User, UserRole
from app.modules.sales.models import Call


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
        return CallQualityStatusResponse(rule_set=self._response(rules) if rules else None, calls_received=calls_received, analyses_ready=analyses_ready, integration_status="connected" if calls_received else "waiting_for_kcell")

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

    @staticmethod
    def _response(item: CallQualityRuleSet) -> RuleSetResponse:
        return RuleSetResponse(id=item.id, version=item.version, name=item.name, success_definition=item.success_definition, partial_success_definition=item.partial_success_definition, loss_definition=item.loss_definition, criteria=item.criteria, loss_reasons=item.loss_reasons, is_active=item.is_active, created_at=item.created_at)
