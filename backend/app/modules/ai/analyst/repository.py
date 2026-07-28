from datetime import UTC, datetime, timedelta
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.ai.models import AIChatMessage, AIChatSession, AILLMCallAudit

class AnalystRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_session(self, tenant_id: UUID, user_id: UUID, title: str, branch_id: UUID | None) -> AIChatSession:
        item = AIChatSession(tenant_id=tenant_id, user_id=user_id, title=title, branch_id=branch_id, is_archived=False)
        self.session.add(item); await self.session.flush(); return item

    async def list_sessions(self, tenant_id: UUID, user_id: UUID) -> list[AIChatSession]:
        return list((await self.session.scalars(select(AIChatSession).where(
            AIChatSession.tenant_id == tenant_id, AIChatSession.user_id == user_id,
            AIChatSession.is_archived.is_(False)).order_by(AIChatSession.last_message_at.desc().nullslast(), AIChatSession.created_at.desc()).limit(100))).all())

    async def get_session(self, tenant_id: UUID, user_id: UUID, session_id: UUID) -> AIChatSession | None:
        return await self.session.scalar(select(AIChatSession).where(
            AIChatSession.tenant_id == tenant_id, AIChatSession.user_id == user_id,
            AIChatSession.id == session_id))

    async def messages(self, tenant_id: UUID, session_id: UUID, limit: int = 100) -> list[AIChatMessage]:
        return list((await self.session.scalars(select(AIChatMessage).where(
            AIChatMessage.tenant_id == tenant_id, AIChatMessage.session_id == session_id
        ).order_by(AIChatMessage.created_at.asc()).limit(limit))).all())

    async def add_message(self, *, tenant_id: UUID, session: AIChatSession, user_id: UUID | None,
                          role: str, content: str, sources: list | None = None,
                          tool_calls: list | None = None, model: str | None = None,
                          input_tokens: int | None = None, output_tokens: int | None = None) -> AIChatMessage:
        message = AIChatMessage(tenant_id=tenant_id, session_id=session.id, user_id=user_id,
            role=role, content=content, sources=sources or [], tool_calls=tool_calls or [],
            model=model, input_tokens=input_tokens, output_tokens=output_tokens)
        self.session.add(message); session.last_message_at = datetime.now(UTC)
        await self.session.flush(); return message

    async def recent_user_message_count(self, tenant_id: UUID, user_id: UUID, seconds: int = 60) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=seconds)
        return int(await self.session.scalar(select(func.count(AIChatMessage.id)).where(
            AIChatMessage.tenant_id == tenant_id, AIChatMessage.user_id == user_id,
            AIChatMessage.role == "user", AIChatMessage.created_at >= cutoff)) or 0)

    async def add_audit(self, **values) -> AILLMCallAudit:
        item = AILLMCallAudit(**values); self.session.add(item); await self.session.flush(); return item

    async def archive(self, item: AIChatSession) -> None:
        item.is_archived = True; await self.session.flush()
