"""Default owner-editable call-quality standard."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.call_quality.models import CallQualityRuleSet
from app.modules.auth.models import User, UserRole


DEFAULT_CRITERIA = [
    {"name": "Приветствие", "weight": 10, "description": "Представился, назвал клинику и вежливо начал разговор."},
    {"name": "Выявление потребности", "weight": 20, "description": "Задал уточняющие вопросы и понял цель обращения."},
    {"name": "Качество консультации", "weight": 20, "description": "Дал понятную, корректную и полезную информацию без медицинских обещаний."},
    {"name": "Работа с возражениями", "weight": 15, "description": "Спокойно уточнил сомнения и предложил подходящее решение."},
    {"name": "Предложение записи", "weight": 25, "description": "Предложил конкретный следующий шаг, дату или время записи."},
    {"name": "Завершение разговора", "weight": 10, "description": "Подтвердил договорённости и корректно завершил разговор."},
]
DEFAULT_LOSS_REASONS = [
    "Не выявлена потребность",
    "Не предложена запись",
    "Не обработано возражение",
    "Недостаточно информации",
    "Конфликт или грубость",
    "Клиент отказался",
    "Техническая проблема",
]


async def ensure_default_rule_set(
    session: AsyncSession, tenant_id: UUID
) -> CallQualityRuleSet | None:
    existing = await session.scalar(
        select(CallQualityRuleSet)
        .where(
            CallQualityRuleSet.tenant_id == tenant_id,
            CallQualityRuleSet.is_active.is_(True),
        )
        .order_by(CallQualityRuleSet.version.desc())
    )
    if existing is not None:
        return existing
    owner = await session.scalar(
        select(User)
        .where(
            User.tenant_id == tenant_id,
            User.role == UserRole.OWNER,
            User.is_active.is_(True),
        )
        .order_by(User.created_at)
    )
    if owner is None:
        return None
    item = CallQualityRuleSet(
        tenant_id=tenant_id,
        version=1,
        name="Базовый стандарт Revora",
        success_definition="Оператор понял потребность и довёл разговор до подтверждённой записи или ясного следующего шага.",
        partial_success_definition="Потребность выявлена, но запись или следующий шаг подтверждены не полностью.",
        loss_definition="Потребность не выявлена, запись не предложена либо клиент потерян из-за качества разговора.",
        criteria=DEFAULT_CRITERIA,
        loss_reasons=DEFAULT_LOSS_REASONS,
        is_active=True,
        created_by_id=owner.id,
    )
    session.add(item)
    await session.flush()
    return item
