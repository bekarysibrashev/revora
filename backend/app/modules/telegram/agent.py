"""Telegram interface to the read-only analyst and confirmed staff-task drafts."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import re
from time import perf_counter
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.database import AsyncSessionFactory
from app.core.errors import AppError
from app.modules.ai.analyst.dependencies import build_analyst_service
from app.modules.ai.analyst.security import check_user_input, redact_personal_data
from app.modules.ai.llm_provider import LLMProviderError
from app.modules.auth.models import User, UserRole
from app.modules.telegram.models import (
    TelegramAgentDraftStatus,
    TelegramAgentTaskDraft,
    TelegramEmployee,
    TelegramEmployeeRoute,
    TelegramTask,
    TelegramTaskPriority,
    TelegramTaskStatus,
)
from app.modules.telegram.repository import TelegramRepository
from app.modules.tenancy.models import Tenant


TASK_INTENT = re.compile(
    r"\b(постав(?:ь|ить)?|назнач(?:ь|ить)?|поруч(?:и|ить)?|"
    r"созда(?:й|ть)\s+задач|отправ(?:ь|ить)?\s+задач|assign|delegate)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TelegramAgentReply:
    text: str
    draft: TelegramAgentTaskDraft | None = None
    assignee_name: str | None = None


class DraftTaskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=250)
    description: str = Field(min_length=1, max_length=4000)
    priority: TelegramTaskPriority = TelegramTaskPriority.NORMAL
    due_at: datetime | None = None

    @field_validator("title", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()


class TelegramAgentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def respond(self, telegram_user_id: int, content: str) -> TelegramAgentReply:
        content = content.strip()
        if len(content) < 2 or len(content) > 4000:
            raise AppError("AI_INPUT_INVALID", "Сообщение должно содержать от 2 до 4000 символов", 422)

        async with AsyncSessionFactory() as session, session.begin():
            employee, user = await self._leader_context(session, telegram_user_id)
            analyst = build_analyst_service(session, self.settings)
            session_id = await self._ensure_session(employee, user, analyst)
            if TASK_INTENT.search(content):
                return await self._draft_task(
                    session, employee, user, session_id, analyst, content
                )
            turn = await analyst.send(user, session_id, content, None, None)
            return TelegramAgentReply(turn.assistant_message.content)

    async def reset(self, telegram_user_id: int) -> None:
        async with AsyncSessionFactory() as session, session.begin():
            employee, user = await self._leader_context(session, telegram_user_id)
            if employee.agent_session_id is not None:
                analyst = build_analyst_service(session, self.settings)
                try:
                    await analyst.archive(user, employee.agent_session_id)
                except AppError as exc:
                    if exc.code != "AI_SESSION_NOT_FOUND":
                        raise
            employee.agent_session_id = None

    async def confirm(self, telegram_user_id: int, draft_id: UUID) -> TelegramTask:
        async with AsyncSessionFactory() as session, session.begin():
            employee, user = await self._leader_context(session, telegram_user_id)
            draft = await session.scalar(
                select(TelegramAgentTaskDraft)
                .where(
                    TelegramAgentTaskDraft.tenant_id == employee.tenant_id,
                    TelegramAgentTaskDraft.id == draft_id,
                    TelegramAgentTaskDraft.requested_by_employee_id == employee.id,
                )
                .with_for_update()
            )
            if draft is None:
                raise AppError("AGENT_DRAFT_NOT_FOUND", "Черновик задания не найден", 404)
            now = datetime.now(UTC)
            if draft.status != TelegramAgentDraftStatus.PENDING:
                raise AppError("AGENT_DRAFT_USED", "Этот черновик уже обработан", 409)
            if draft.expires_at <= now:
                draft.status = TelegramAgentDraftStatus.EXPIRED
                raise AppError("AGENT_DRAFT_EXPIRED", "Время подтверждения истекло", 409)
            assignee = await session.scalar(
                select(TelegramEmployee).where(
                    TelegramEmployee.tenant_id == employee.tenant_id,
                    TelegramEmployee.id == draft.assignee_employee_id,
                    TelegramEmployee.is_active.is_(True),
                )
            )
            if assignee is None:
                raise AppError("TELEGRAM_EMPLOYEE_NOT_FOUND", "Исполнитель больше недоступен", 404)

            repository = TelegramRepository(session)
            task = await repository.create_task(
                tenant_id=employee.tenant_id,
                employee_id=assignee.id,
                assigned_by_user_id=user.id,
                title=draft.title,
                description=draft.description,
                priority=draft.priority,
                due_at=draft.due_at,
            )
            draft.status = TelegramAgentDraftStatus.CONFIRMED
            draft.confirmed_at = now
            draft.created_task_id = task.id
            await repository.add_audit(
                tenant_id=employee.tenant_id,
                actor_user_id=user.id,
                action="telegram.agent_task.confirmed",
                entity_type="telegram_task",
                entity_id=task.id,
                changes={"draft_id": str(draft.id), "employee_id": str(assignee.id)},
            )
            return task

    async def cancel(self, telegram_user_id: int, draft_id: UUID) -> None:
        async with AsyncSessionFactory() as session, session.begin():
            employee, user = await self._leader_context(session, telegram_user_id)
            draft = await session.scalar(
                select(TelegramAgentTaskDraft)
                .where(
                    TelegramAgentTaskDraft.tenant_id == employee.tenant_id,
                    TelegramAgentTaskDraft.id == draft_id,
                    TelegramAgentTaskDraft.requested_by_employee_id == employee.id,
                )
                .with_for_update()
            )
            if draft is None:
                raise AppError("AGENT_DRAFT_NOT_FOUND", "Черновик задания не найден", 404)
            if draft.status != TelegramAgentDraftStatus.PENDING:
                raise AppError("AGENT_DRAFT_USED", "Этот черновик уже обработан", 409)
            draft.status = TelegramAgentDraftStatus.CANCELLED
            await TelegramRepository(session).add_audit(
                tenant_id=employee.tenant_id,
                actor_user_id=user.id,
                action="telegram.agent_task.cancelled",
                entity_type="telegram_agent_task_draft",
                entity_id=draft.id,
            )

    @staticmethod
    async def _set_tenant(session, tenant_id: UUID) -> None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    async def _leader_context(self, session, telegram_user_id: int) -> tuple[TelegramEmployee, User]:
        route = await session.get(TelegramEmployeeRoute, telegram_user_id)
        if route is None:
            raise AppError("TELEGRAM_NOT_REGISTERED", "Сначала зарегистрируйтесь в боте", 401)
        await self._set_tenant(session, route.tenant_id)
        employee = await session.get(TelegramEmployee, route.employee_id)
        if employee is None or not employee.is_active:
            raise AppError("TELEGRAM_ACCESS_DISABLED", "Доступ к боту отключён", 403)
        if employee.linked_user_id is None:
            raise AppError(
                "TELEGRAM_USER_NOT_LINKED",
                "Попросите владельца привязать Telegram-профиль к пользователю Revora",
                403,
            )
        user = await session.scalar(
            select(User)
            .options(selectinload(User.branch_links))
            .where(User.tenant_id == route.tenant_id, User.id == employee.linked_user_id)
        )
        if user is None or not user.is_active:
            raise AppError("REVORA_USER_UNAVAILABLE", "Пользователь Revora недоступен", 403)
        if user.role not in {UserRole.OWNER, UserRole.MANAGER} or employee.role != user.role:
            raise AppError(
                "TELEGRAM_AGENT_FORBIDDEN",
                "ИИ-агент в Telegram доступен владельцу и руководителю",
                403,
            )
        return employee, user

    @staticmethod
    async def _ensure_session(employee: TelegramEmployee, user: User, analyst) -> UUID:
        if employee.agent_session_id is not None:
            return employee.agent_session_id
        created = await analyst.create_session(user, "Telegram · ИИ-агент", employee.branch_id)
        employee.agent_session_id = created.id
        return created.id

    async def _draft_task(
        self, session, requester: TelegramEmployee, user: User, session_id: UUID,
        analyst, content: str,
    ) -> TelegramAgentReply:
        check = check_user_input(content)
        if not check.allowed:
            raise AppError(
                check.code or "AI_INPUT_REJECTED",
                "Сообщение похоже на попытку изменить правила ИИ-агента",
                422,
            )
        employees = list(
            (
                await session.scalars(
                    select(TelegramEmployee).where(
                        TelegramEmployee.tenant_id == requester.tenant_id,
                        TelegramEmployee.is_active.is_(True),
                    )
                )
            ).all()
        )
        allowed_branches = {link.branch_id for link in user.branch_links}
        if user.role == UserRole.MANAGER and allowed_branches:
            employees = [item for item in employees if item.branch_id in allowed_branches]
        assignee = match_assignee(content, employees)
        if assignee is None:
            available = ", ".join(item.full_name for item in employees[:12]) or "нет активных сотрудников"
            return TelegramAgentReply(
                "Не удалось однозначно определить исполнителя. "
                f"Укажите имя или @username. Доступны: {available}."
            )

        safe_content = replace_assignee(content, assignee)
        safe_content, _ = redact_personal_data(safe_content)
        repository = analyst.repository
        if await repository.recent_user_message_count(user.tenant_id, user.id) >= self.settings.ai_messages_per_minute:
            raise AppError("AI_RATE_LIMIT", "Слишком много сообщений. Повторите через минуту", 429)
        ai_session = await repository.get_session(user.tenant_id, user.id, session_id)
        if ai_session is None:
            raise AppError("AI_SESSION_NOT_FOUND", "Сессия ИИ-агента не найдена", 404)
        await repository.add_message(
            tenant_id=user.tenant_id,
            session=ai_session,
            user_id=user.id,
            role="user",
            content=safe_content,
        )

        tenant = await session.get(Tenant, user.tenant_id)
        timezone_name = tenant.timezone if tenant else self.settings.timezone
        now = datetime.now(UTC)
        instructions = (
            "Ты извлекаешь только черновик рабочего задания из сообщения руководителя клиники. "
            "Исполнитель уже определён сервером и обозначен словом 'исполнитель'. "
            "Не выполняй действие и не добавляй фактов. Вызови draft_staff_task ровно один раз. "
            "Не включай сведения о пациентах, телефоны, email или медицинские данные. "
            f"Текущее время: {now.isoformat()}, часовой пояс клиники: {timezone_name}. "
            "Если срок не указан, верни due_at=null."
        )
        tool = {
            "type": "function",
            "name": "draft_staff_task",
            "description": "Подготовить безопасный черновик задания для подтверждения руководителем.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 2, "maxLength": 250},
                    "description": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                    "due_at": {"type": ["string", "null"], "description": "ISO 8601 со смещением UTC"},
                },
                "required": ["title", "description", "priority", "due_at"],
                "additionalProperties": False,
            },
        }
        started = perf_counter()
        try:
            decision = await analyst.provider.respond(
                instructions=instructions,
                input_items=[{"role": "user", "content": safe_content}],
                tools=[tool],
                safety_identifier=sha256(f"{user.tenant_id}:{user.id}".encode()).hexdigest(),
            )
            call = next(
                (item for item in decision.tool_calls if item.name == "draft_staff_task"),
                None,
            )
            if call is None:
                raise LLMProviderError("AI_DRAFT_INVALID", "ИИ не сформировал черновик задания")
            try:
                args = DraftTaskArgs.model_validate(call.arguments)
            except ValidationError as exc:
                raise LLMProviderError("AI_DRAFT_INVALID", "ИИ вернул некорректный черновик") from exc
            safe_title, _ = redact_personal_data(args.title)
            safe_description, _ = redact_personal_data(args.description)
            if len(safe_title.strip()) < 2 or not safe_description.strip():
                raise LLMProviderError(
                    "AI_DRAFT_INVALID", "После удаления персональных данных черновик пуст"
                )
            due_at = normalize_due_at(args.due_at, timezone_name)
            if due_at is not None and due_at <= now:
                raise AppError("TASK_DUE_AT_INVALID", "Уточните будущий срок выполнения задания", 422)
            draft = TelegramAgentTaskDraft(
                tenant_id=user.tenant_id,
                requested_by_employee_id=requester.id,
                assignee_employee_id=assignee.id,
                title=safe_title.strip(),
                description=safe_description.strip(),
                priority=args.priority,
                due_at=due_at,
                status=TelegramAgentDraftStatus.PENDING,
                expires_at=now + timedelta(minutes=30),
            )
            session.add(draft)
            await session.flush()
            await repository.add_message(
                tenant_id=user.tenant_id,
                session=ai_session,
                user_id=None,
                role="assistant",
                content="Подготовлен черновик задания. Ожидается подтверждение в Telegram.",
                tool_calls=["draft_staff_task"],
                model=analyst.provider.model,
                input_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
            )
            await repository.add_audit(
                tenant_id=user.tenant_id,
                session_id=session_id,
                message_id=None,
                user_id=user.id,
                provider=analyst.provider.provider_name,
                model=analyst.provider.model,
                status="completed",
                tool_names=["draft_staff_task"],
                input_characters=len(safe_content),
                output_characters=len(safe_title) + len(safe_description),
                input_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
                latency_ms=int((perf_counter() - started) * 1000),
                error_code=None,
            )
            return TelegramAgentReply(
                "Черновик готов. Проверьте исполнителя, текст и срок перед отправкой.",
                draft=draft,
                assignee_name=assignee.full_name,
            )
        except LLMProviderError as exc:
            await repository.add_audit(
                tenant_id=user.tenant_id,
                session_id=session_id,
                message_id=None,
                user_id=user.id,
                provider=analyst.provider.provider_name,
                model=analyst.provider.model,
                status="failed",
                tool_names=["draft_staff_task"],
                input_characters=len(safe_content),
                output_characters=0,
                input_tokens=None,
                output_tokens=None,
                latency_ms=int((perf_counter() - started) * 1000),
                error_code=exc.code,
            )
            status = 503 if exc.code == "AI_NOT_CONFIGURED" else 502
            raise AppError(exc.code, str(exc), status) from exc


def employee_aliases(employee: TelegramEmployee) -> list[str]:
    aliases = [employee.full_name.strip()]
    aliases.extend(part for part in employee.full_name.split() if len(part) >= 3)
    if employee.username:
        aliases.extend([employee.username, f"@{employee.username}"])
    return list(dict.fromkeys(alias.casefold() for alias in aliases if len(alias) >= 3))


def match_assignee(content: str, employees: list[TelegramEmployee]) -> TelegramEmployee | None:
    normalized = content.casefold()
    scored: list[tuple[int, TelegramEmployee]] = []
    for employee in employees:
        matches = [alias for alias in employee_aliases(employee) if alias in normalized]
        if matches:
            scored.append((max(len(alias) for alias in matches), employee))
    if not scored:
        return None
    best = max(score for score, _ in scored)
    winners = [employee for score, employee in scored if score == best]
    return winners[0] if len(winners) == 1 else None


def replace_assignee(content: str, employee: TelegramEmployee) -> str:
    output = content
    for alias in sorted(employee_aliases(employee), key=len, reverse=True):
        output = re.sub(re.escape(alias), "исполнитель", output, flags=re.IGNORECASE)
    return output


def normalize_due_at(value: datetime | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        try:
            value = value.replace(tzinfo=ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
