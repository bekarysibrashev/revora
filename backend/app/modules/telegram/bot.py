"""Dependency-light Telegram Bot API client and database-backed worker."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from html import escape
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import UUID

import httpx
from sqlalchemy import distinct, func, select, text

from app.core.config import Settings
from app.core.database import AsyncSessionFactory
from app.core.errors import AppError
from app.modules.ai.models import AIInsight
from app.modules.auth.models import UserRole
from app.modules.telegram.agent import TelegramAgentReply, TelegramAgentService
from app.modules.telegram.models import (
    TelegramEmployee,
    TelegramEmployeeRoute,
    TelegramInvitation,
    TelegramInviteRoute,
    TelegramReportCadence,
    TelegramReportSubscription,
    TelegramTask,
    TelegramTaskStatus,
)
from app.modules.tenancy.models import Tenant

logger = logging.getLogger(__name__)

ROLE_LABELS = {
    UserRole.OWNER: "Владелец",
    UserRole.MANAGER: "Руководитель",
    UserRole.ADMINISTRATOR: "Администратор",
    UserRole.SALES_MANAGER: "Менеджер по продажам",
}
PRIORITY_LABELS = {"low": "Низкий", "normal": "Обычный", "high": "Высокий", "urgent": "Срочный"}


class TelegramAPIError(RuntimeError):
    pass


class RegistrationError(ValueError):
    pass


@dataclass(frozen=True)
class OutboundTask:
    id: UUID
    tenant_id: UUID
    chat_id: int
    title: str
    description: str
    priority: str
    due_at: datetime | None


@dataclass(frozen=True)
class DueReport:
    subscription_id: UUID
    tenant_id: UUID
    chat_id: int
    period_key: str
    text: str


class TelegramAPI:
    def __init__(self, token: str, timeout_seconds: int) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds + 10))
        self._poll_timeout = timeout_seconds

    async def close(self) -> None:
        await self._client.aclose()

    async def call(self, method: str, payload: dict | None = None) -> object:
        try:
            response = await self._client.post(f"{self._base_url}/{method}", json=payload or {})
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramAPIError("Telegram API is temporarily unavailable") from exc
        if response.status_code >= 400 or not data.get("ok"):
            description = str(data.get("description", "Telegram API rejected the request"))[:300]
            raise TelegramAPIError(description)
        return data.get("result")

    async def get_updates(self, offset: int | None) -> list[dict]:
        payload: dict[str, object] = {
            "timeout": self._poll_timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self.call("getUpdates", payload)
        return result if isinstance(result, list) else []

    async def send_message(
        self, chat_id: int, message: str, reply_markup: dict | None = None
    ) -> int | None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result = await self.call("sendMessage", payload)
        return result.get("message_id") if isinstance(result, dict) else None

    async def answer_callback(self, callback_id: str, message: str) -> None:
        await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": message})


class TelegramBotStore:
    @staticmethod
    async def _set_tenant(session, tenant_id: UUID) -> None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    async def register(
        self,
        *,
        code: str,
        telegram_user_id: int,
        telegram_chat_id: int,
        username: str | None,
        full_name: str,
    ) -> TelegramEmployee:
        code_hash = sha256(code.strip().encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        async with AsyncSessionFactory() as session, session.begin():
            route = await session.get(TelegramInviteRoute, code_hash)
            if route is None:
                raise RegistrationError("Код приглашения не найден.")
            await self._set_tenant(session, route.tenant_id)
            invitation = await session.scalar(
                select(TelegramInvitation)
                .where(
                    TelegramInvitation.tenant_id == route.tenant_id,
                    TelegramInvitation.id == route.invitation_id,
                )
                .with_for_update()
            )
            if invitation is None or invitation.revoked_at is not None:
                raise RegistrationError("Приглашение отозвано.")
            if invitation.expires_at <= now:
                raise RegistrationError("Срок действия приглашения истёк.")
            if invitation.uses >= invitation.max_uses:
                raise RegistrationError("Лимит активаций приглашения исчерпан.")

            linked_employee = None
            if invitation.linked_user_id is not None:
                linked_employee = await session.scalar(
                    select(TelegramEmployee).where(
                        TelegramEmployee.tenant_id == route.tenant_id,
                        TelegramEmployee.linked_user_id == invitation.linked_user_id,
                    )
                )

            existing_route = await session.get(TelegramEmployeeRoute, telegram_user_id)
            if existing_route is not None:
                if existing_route.tenant_id != route.tenant_id:
                    raise RegistrationError("Этот Telegram уже связан с другой клиникой.")
                employee = await session.get(TelegramEmployee, existing_route.employee_id)
                if employee is None:
                    raise RegistrationError("Не удалось проверить существующую регистрацию.")
                if linked_employee is not None and linked_employee.id != employee.id:
                    raise RegistrationError("Пользователь Revora уже связан с другим Telegram.")
                employee.telegram_chat_id = telegram_chat_id
                if invitation.linked_user_id is not None:
                    employee.linked_user_id = invitation.linked_user_id
                employee.role = invitation.role
                employee.branch_id = invitation.branch_id
                employee.username = username
                employee.full_name = full_name
                employee.last_seen_at = now
                existing_route.telegram_chat_id = telegram_chat_id
                invitation.uses += 1
                return employee

            if linked_employee is not None:
                raise RegistrationError("Пользователь Revora уже связан с другим Telegram.")

            employee = TelegramEmployee(
                tenant_id=route.tenant_id,
                branch_id=invitation.branch_id,
                linked_user_id=invitation.linked_user_id,
                agent_session_id=None,
                role=invitation.role,
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                username=username,
                full_name=full_name,
                is_active=True,
                registered_at=now,
                last_seen_at=now,
            )
            session.add(employee)
            await session.flush()
            session.add(
                TelegramEmployeeRoute(
                    telegram_user_id=telegram_user_id,
                    telegram_chat_id=telegram_chat_id,
                    tenant_id=route.tenant_id,
                    employee_id=employee.id,
                )
            )
            invitation.uses += 1
            if invitation.role in {UserRole.OWNER, UserRole.MANAGER}:
                session.add_all(
                    [
                        TelegramReportSubscription(
                            tenant_id=route.tenant_id,
                            employee_id=employee.id,
                            cadence=TelegramReportCadence.DAILY,
                            local_time=time(19, 0),
                            weekday=None,
                            is_active=True,
                        ),
                        TelegramReportSubscription(
                            tenant_id=route.tenant_id,
                            employee_id=employee.id,
                            cadence=TelegramReportCadence.WEEKLY,
                            local_time=time(9, 0),
                            weekday=0,
                            is_active=True,
                        ),
                    ]
                )
            return employee

    async def get_employee(self, telegram_user_id: int) -> TelegramEmployee | None:
        async with AsyncSessionFactory() as session, session.begin():
            route = await session.get(TelegramEmployeeRoute, telegram_user_id)
            if route is None:
                return None
            await self._set_tenant(session, route.tenant_id)
            employee = await session.get(TelegramEmployee, route.employee_id)
            if employee:
                employee.last_seen_at = datetime.now(UTC)
            return employee

    async def list_employee_tasks(self, telegram_user_id: int) -> list[TelegramTask]:
        async with AsyncSessionFactory() as session, session.begin():
            route = await session.get(TelegramEmployeeRoute, telegram_user_id)
            if route is None:
                return []
            await self._set_tenant(session, route.tenant_id)
            return list(
                (
                    await session.scalars(
                        select(TelegramTask)
                        .where(
                            TelegramTask.tenant_id == route.tenant_id,
                            TelegramTask.employee_id == route.employee_id,
                            TelegramTask.status.in_(
                                [TelegramTaskStatus.PENDING, TelegramTaskStatus.ACCEPTED]
                            ),
                        )
                        .order_by(TelegramTask.due_at.asc().nullslast(), TelegramTask.created_at.desc())
                        .limit(10)
                    )
                ).all()
            )

    async def transition_task(
        self, telegram_user_id: int, task_id: UUID, action: str
    ) -> TelegramTask | None:
        async with AsyncSessionFactory() as session, session.begin():
            route = await session.get(TelegramEmployeeRoute, telegram_user_id)
            if route is None:
                return None
            await self._set_tenant(session, route.tenant_id)
            task = await session.scalar(
                select(TelegramTask).where(
                    TelegramTask.tenant_id == route.tenant_id,
                    TelegramTask.id == task_id,
                    TelegramTask.employee_id == route.employee_id,
                )
            )
            if task is None or task.status == TelegramTaskStatus.CANCELLED:
                return None
            now = datetime.now(UTC)
            if action == "accept" and task.status == TelegramTaskStatus.PENDING:
                task.status = TelegramTaskStatus.ACCEPTED
                task.accepted_at = now
            elif action == "done" and task.status in {
                TelegramTaskStatus.PENDING,
                TelegramTaskStatus.ACCEPTED,
            }:
                task.status = TelegramTaskStatus.COMPLETED
                task.accepted_at = task.accepted_at or now
                task.completed_at = now
            return task

    async def pending_deliveries(self) -> list[OutboundTask]:
        now = datetime.now(UTC)
        async with AsyncSessionFactory() as routing_session:
            tenant_ids = list(
                (
                    await routing_session.scalars(
                        select(distinct(TelegramEmployeeRoute.tenant_id))
                    )
                ).all()
            )
        output: list[OutboundTask] = []
        for tenant_id in tenant_ids:
            async with AsyncSessionFactory() as session, session.begin():
                await self._set_tenant(session, tenant_id)
                rows = (
                    await session.execute(
                        select(TelegramTask, TelegramEmployeeRoute.telegram_chat_id)
                        .join(TelegramEmployee, TelegramEmployee.id == TelegramTask.employee_id)
                        .join(TelegramEmployeeRoute, TelegramEmployeeRoute.employee_id == TelegramEmployee.id)
                        .where(
                            TelegramTask.tenant_id == tenant_id,
                            TelegramTask.status == TelegramTaskStatus.PENDING,
                            TelegramTask.delivered_at.is_(None),
                            TelegramEmployee.is_active.is_(True),
                            (TelegramTask.next_delivery_at.is_(None) | (TelegramTask.next_delivery_at <= now)),
                        )
                        .order_by(TelegramTask.created_at)
                        .limit(50)
                    )
                ).all()
                output.extend(
                    OutboundTask(
                        id=task.id,
                        tenant_id=tenant_id,
                        chat_id=chat_id,
                        title=task.title,
                        description=task.description,
                        priority=str(task.priority),
                        due_at=task.due_at,
                    )
                    for task, chat_id in rows
                )
        return output

    async def mark_delivery(
        self, item: OutboundTask, message_id: int | None, error: str | None
    ) -> None:
        async with AsyncSessionFactory() as session, session.begin():
            await self._set_tenant(session, item.tenant_id)
            task = await session.get(TelegramTask, item.id)
            if task is None:
                return
            task.delivery_attempts += 1
            if error is None:
                task.delivered_at = datetime.now(UTC)
                task.telegram_message_id = message_id
                task.last_delivery_error = None
                task.next_delivery_at = None
            else:
                task.last_delivery_error = error[:500]
                delay_minutes = min(60, 2 ** min(task.delivery_attempts, 5))
                task.next_delivery_at = datetime.now(UTC) + timedelta(minutes=delay_minutes)

    async def due_reports(self) -> list[DueReport]:
        now = datetime.now(UTC)
        async with AsyncSessionFactory() as routing_session:
            tenant_ids = list(
                (await routing_session.scalars(select(distinct(TelegramEmployeeRoute.tenant_id)))).all()
            )
        reports: list[DueReport] = []
        for tenant_id in tenant_ids:
            async with AsyncSessionFactory() as session, session.begin():
                await self._set_tenant(session, tenant_id)
                tenant = await session.get(Tenant, tenant_id)
                if tenant is None or not tenant.is_active:
                    continue
                try:
                    local_now = now.astimezone(ZoneInfo(tenant.timezone))
                except ZoneInfoNotFoundError:
                    local_now = now
                rows = (
                    await session.execute(
                        select(TelegramReportSubscription, TelegramEmployeeRoute.telegram_chat_id)
                        .join(TelegramEmployee, TelegramEmployee.id == TelegramReportSubscription.employee_id)
                        .join(TelegramEmployeeRoute, TelegramEmployeeRoute.employee_id == TelegramEmployee.id)
                        .where(
                            TelegramReportSubscription.tenant_id == tenant_id,
                            TelegramReportSubscription.is_active.is_(True),
                            TelegramEmployee.is_active.is_(True),
                        )
                    )
                ).all()
                for subscription, chat_id in rows:
                    period = self._due_period(subscription, local_now)
                    if period is None or period == subscription.last_period_key:
                        continue
                    start_local = (
                        local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                        if subscription.cadence == TelegramReportCadence.DAILY
                        else (local_now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                    )
                    report_text = await self._build_report(session, tenant_id, tenant.name, subscription.cadence, start_local.astimezone(UTC))
                    reports.append(DueReport(subscription.id, tenant_id, chat_id, period, report_text))
        return reports

    @staticmethod
    def _due_period(subscription: TelegramReportSubscription, local_now: datetime) -> str | None:
        if local_now.time().replace(tzinfo=None) < subscription.local_time:
            return None
        if subscription.cadence == TelegramReportCadence.DAILY:
            return local_now.date().isoformat()
        if local_now.weekday() != subscription.weekday:
            return None
        iso = local_now.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    @staticmethod
    async def _build_report(session, tenant_id: UUID, tenant_name: str, cadence, start_utc: datetime) -> str:
        counts = dict(
            (
                await session.execute(
                    select(TelegramTask.status, func.count(TelegramTask.id))
                    .where(TelegramTask.tenant_id == tenant_id, TelegramTask.created_at >= start_utc)
                    .group_by(TelegramTask.status)
                )
            ).all()
        )
        insights = list(
            (
                await session.scalars(
                    select(AIInsight)
                    .where(AIInsight.tenant_id == tenant_id, AIInsight.detected_at >= start_utc)
                    .order_by(AIInsight.detected_at.desc())
                    .limit(5)
                )
            ).all()
        )
        label = "Ежедневный" if cadence == TelegramReportCadence.DAILY else "Еженедельный"
        lines = [
            f"<b>{label} отчёт · {escape(tenant_name)}</b>",
            "",
            f"Заданий создано: <b>{sum(counts.values())}</b>",
            f"В работе: <b>{counts.get(TelegramTaskStatus.ACCEPTED, 0)}</b>",
            f"Выполнено: <b>{counts.get(TelegramTaskStatus.COMPLETED, 0)}</b>",
            f"Ожидают: <b>{counts.get(TelegramTaskStatus.PENDING, 0)}</b>",
        ]
        if insights:
            lines.extend(["", "<b>Сигналы Revora:</b>"])
            lines.extend(f"• {escape(item.title)}" for item in insights)
        else:
            lines.extend(["", "Новых сигналов Revora за период нет."])
        return "\n".join(lines)

    async def mark_report_sent(self, report: DueReport) -> None:
        async with AsyncSessionFactory() as session, session.begin():
            await self._set_tenant(session, report.tenant_id)
            subscription = await session.get(TelegramReportSubscription, report.subscription_id)
            if subscription:
                subscription.last_period_key = report.period_key
                subscription.last_sent_at = datetime.now(UTC)


class TelegramBotRunner:
    def __init__(self, settings: Settings) -> None:
        token = settings.telegram_bot_token.get_secret_value()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        self.api = TelegramAPI(token, settings.telegram_poll_timeout_seconds)
        self.store = TelegramBotStore()
        self.agent = TelegramAgentService(settings)
        self.offset: int | None = None

    async def run_forever(self) -> None:
        await self.api.call("deleteWebhook", {"drop_pending_updates": False})
        await self.api.call(
            "setMyCommands",
            {
                "commands": [
                    {"command": "tasks", "description": "Мои активные задания"},
                    {"command": "agent", "description": "Задать вопрос ИИ-агенту"},
                    {"command": "new", "description": "Новый диалог с ИИ"},
                    {"command": "me", "description": "Мой профиль и роль"},
                    {"command": "help", "description": "Помощь"},
                ]
            },
        )
        logger.info("Telegram staff bot started")
        try:
            while True:
                try:
                    updates, _ = await asyncio.gather(
                        self.api.get_updates(self.offset), self._dispatch_outbound()
                    )
                    for update in updates:
                        self.offset = int(update["update_id"]) + 1
                        await self._handle_update(update)
                except TelegramAPIError:
                    logger.warning("Telegram API request failed; retrying")
                    await asyncio.sleep(3)
                except Exception:
                    logger.exception("Unexpected Telegram worker error")
                    await asyncio.sleep(3)
        finally:
            await self.api.close()

    async def _dispatch_outbound(self) -> None:
        for item in await self.store.pending_deliveries():
            try:
                message_id = await self.api.send_message(
                    item.chat_id,
                    self._task_text(item),
                    self._task_keyboard(item.id),
                )
                await self.store.mark_delivery(item, message_id, None)
            except TelegramAPIError as exc:
                await self.store.mark_delivery(item, None, str(exc))
        for report in await self.store.due_reports():
            try:
                await self.api.send_message(report.chat_id, report.text)
                await self.store.mark_report_sent(report)
            except TelegramAPIError:
                logger.warning("Could not deliver Telegram management report")

    async def _handle_update(self, update: dict) -> None:
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
        elif "message" in update:
            await self._handle_message(update["message"])

    async def _handle_message(self, message: dict) -> None:
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private" or not sender.get("id") or not chat.get("id"):
            return
        raw_text = str(message.get("text") or "").strip()
        telegram_user_id = int(sender["id"])
        employee = await self.store.get_employee(telegram_user_id)
        command, _, argument = raw_text.partition(" ")
        if command.startswith("/start"):
            if employee and employee.is_active:
                await self.api.send_message(int(chat["id"]), self._welcome(employee))
                return
            if argument:
                await self._register(message, argument)
            else:
                await self.api.send_message(
                    int(chat["id"]),
                    "Здравствуйте! Отправьте одноразовый код приглашения, который выдал руководитель клиники.",
                )
            return
        if employee is None:
            if raw_text.startswith("RV-"):
                await self._register(message, raw_text)
            else:
                await self.api.send_message(int(chat["id"]), "Сначала нажмите /start и введите код приглашения.")
            return
        if not employee.is_active:
            await self.api.send_message(int(chat["id"]), "Доступ отключён. Обратитесь к руководителю.")
        elif command == "/tasks":
            tasks = await self.store.list_employee_tasks(telegram_user_id)
            if not tasks:
                await self.api.send_message(int(chat["id"]), "Активных заданий сейчас нет.")
            for task in tasks:
                await self.api.send_message(
                    int(chat["id"]), self._task_text(task), self._task_keyboard(task.id)
                )
        elif command == "/me":
            await self.api.send_message(int(chat["id"]), self._welcome(employee))
        elif command == "/agent":
            if argument:
                await self.api.call("sendChatAction", {"chat_id": int(chat["id"]), "action": "typing"})
                try:
                    reply = await self.agent.respond(telegram_user_id, argument)
                    await self._send_agent_reply(int(chat["id"]), reply)
                except AppError as exc:
                    await self.api.send_message(int(chat["id"]), escape(exc.message))
            else:
                await self.api.send_message(
                    int(chat["id"]),
                    "Напишите вопрос об аналитике клиники или поручение, например:\n"
                    "<i>Покажи проблемы за вчера</i>\n"
                    "<i>Поставь Айжан задачу проверить неподтверждённые записи до 17:00</i>",
                )
        elif command == "/new":
            try:
                await self.agent.reset(telegram_user_id)
                await self.api.send_message(int(chat["id"]), "Начат новый диалог с ИИ-агентом.")
            except AppError as exc:
                await self.api.send_message(int(chat["id"]), escape(exc.message))
        elif command.startswith("/"):
            await self.api.send_message(int(chat["id"]), self._help(employee))
        elif employee.role in {UserRole.OWNER, UserRole.MANAGER}:
            await self.api.call("sendChatAction", {"chat_id": int(chat["id"]), "action": "typing"})
            try:
                reply = await self.agent.respond(telegram_user_id, raw_text)
                await self._send_agent_reply(int(chat["id"]), reply)
            except AppError as exc:
                await self.api.send_message(int(chat["id"]), escape(exc.message))
        else:
            await self.api.send_message(int(chat["id"]), self._help(employee))

    async def _register(self, message: dict, code: str) -> None:
        sender = message["from"]
        full_name = " ".join(
            part for part in [sender.get("first_name", ""), sender.get("last_name", "")] if part
        )[:200] or "Сотрудник"
        try:
            employee = await self.store.register(
                code=code,
                telegram_user_id=int(sender["id"]),
                telegram_chat_id=int(message["chat"]["id"]),
                username=sender.get("username"),
                full_name=full_name,
            )
        except RegistrationError as exc:
            await self.api.send_message(int(message["chat"]["id"]), escape(str(exc)))
            return
        await self.api.send_message(int(message["chat"]["id"]), self._welcome(employee))

    async def _handle_callback(self, callback: dict) -> None:
        sender = callback.get("from") or {}
        data = str(callback.get("data") or "")
        try:
            prefix, action, raw_id = data.split(":", 2)
            item_id = UUID(raw_id)
        except ValueError:
            await self.api.answer_callback(str(callback.get("id")), "Неизвестная команда")
            return
        telegram_user_id = int(sender.get("id", 0))
        if prefix == "task" and action in {"accept", "done"}:
            task = await self.store.transition_task(telegram_user_id, item_id, action)
            if task is None:
                await self.api.answer_callback(str(callback.get("id")), "Задание недоступно")
            else:
                label = "Задание принято" if action == "accept" else "Задание выполнено"
                await self.api.answer_callback(str(callback.get("id")), label)
            return
        if prefix == "agent" and action in {"confirm", "cancel"}:
            try:
                if action == "confirm":
                    task = await self.agent.confirm(telegram_user_id, item_id)
                    await self.api.answer_callback(str(callback.get("id")), "Задание отправлено")
                    chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
                    if chat_id:
                        await self.api.send_message(
                            int(chat_id), f"✅ Задание <b>{escape(task.title)}</b> поставлено в очередь доставки."
                        )
                else:
                    await self.agent.cancel(telegram_user_id, item_id)
                    await self.api.answer_callback(str(callback.get("id")), "Черновик отменён")
            except AppError as exc:
                await self.api.answer_callback(str(callback.get("id")), exc.message[:180])
            return
        await self.api.answer_callback(str(callback.get("id")), "Неизвестная команда")

    @staticmethod
    def _welcome(employee: TelegramEmployee) -> str:
        role = ROLE_LABELS.get(employee.role, str(employee.role))
        return (
            f"Вы зарегистрированы как <b>{escape(employee.full_name)}</b>.\n"
            f"Роль: <b>{escape(role)}</b>\n\n"
            + TelegramBotRunner._help(employee)
        )

    @staticmethod
    def _help(employee: TelegramEmployee) -> str:
        commands = "Команды: /tasks — задания, /me — мой профиль"
        if employee.role in {UserRole.OWNER, UserRole.MANAGER}:
            commands += ", /agent — ИИ-агент, /new — новый диалог"
        return commands + ", /help — помощь."

    async def _send_agent_reply(self, chat_id: int, reply: TelegramAgentReply) -> None:
        if reply.draft is None:
            for start in range(0, len(reply.text), 3600):
                await self.api.send_message(chat_id, escape(reply.text[start:start + 3600]))
            return
        draft = reply.draft
        priority = PRIORITY_LABELS.get(str(draft.priority), str(draft.priority))
        due = (
            draft.due_at.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")
            if draft.due_at else "не указан"
        )
        message = (
            f"<b>Черновик задания</b>\n\n"
            f"Исполнитель: <b>{escape(reply.assignee_name or '—')}</b>\n"
            f"Приоритет: <b>{escape(priority)}</b>\n"
            f"Срок: <b>{escape(due)}</b>\n\n"
            f"<b>{escape(draft.title)}</b>\n{escape(draft.description)}\n\n"
            "Ничего ещё не отправлено. Черновик действует 30 минут."
        )
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Подтвердить", "callback_data": f"agent:confirm:{draft.id}"},
                {"text": "❌ Отмена", "callback_data": f"agent:cancel:{draft.id}"},
            ]]
        }
        await self.api.send_message(chat_id, message, keyboard)

    @staticmethod
    def _task_text(task) -> str:
        priority = PRIORITY_LABELS.get(str(task.priority), str(task.priority))
        due = ""
        if task.due_at:
            due = f"\nСрок: <b>{task.due_at.astimezone(UTC).strftime('%d.%m.%Y %H:%M UTC')}</b>"
        return (
            f"<b>Новое задание · {escape(priority)}</b>\n"
            f"<b>{escape(task.title)}</b>\n\n{escape(task.description)}{due}"
        )

    @staticmethod
    def _task_keyboard(task_id: UUID) -> dict:
        return {
            "inline_keyboard": [
                [
                    {"text": "✅ Принять", "callback_data": f"task:accept:{task_id}"},
                    {"text": "🏁 Выполнено", "callback_data": f"task:done:{task_id}"},
                ]
            ]
        }
