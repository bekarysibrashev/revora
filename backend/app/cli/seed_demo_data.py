"""Заполняет каноническую схему реалистичными фейковыми данными для демонстрации
Dashboard/ОПиУ/ДДС/продаж/врачей/маркетинга без реальных интеграций (1С, банки, Kcell).

Использование:
    python -m app.cli.seed_demo_data --tenant-slug san-dental-demo --reset

Идея: создаёт (или переиспользует) tenant с двумя филиалами SAN Dental, пользователей
на все 4 роли, врачей, услуги, пациентов/лиды/звонки/записи/планы лечения, финансовые
факты (выручка по начислению и оплате), расходы (пост./перем.), маркетинговые расходы
и атрибуцию, ДДС и остатки на счетах, рейтинги врачей. Всё это — только для проверки
API/дашбордов, НЕ для прод-окружения.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from app.core.database import AsyncSessionFactory
from app.core.security import hash_password
from app.modules.auth.models import User, UserBranch, UserRole
from app.modules.auth.repository import AuthRepository
from app.modules.doctors.models import Doctor, DoctorCompensationRule, DoctorRating
from app.modules.finance.models import (
    AccountBalance,
    CashFlowFact,
    ExpenseCategory,
    ExpenseFact,
    RevenueFact,
)
from app.modules.marketing.models import AttributionFact, MarketingSpendFact
from app.modules.sales.models import (
    Appointment,
    Call,
    Lead,
    Patient,
    ServiceDirection,
    TreatmentPlan,
)
from app.modules.tenancy.models import Branch, Tenant

RNG = random.Random(42)  # фиксированный seed — воспроизводимые прогоны

DIRECTIONS = [
    ("therapy", "Терапия", (8_000, 45_000)),
    ("orthopedics", "Ортопедия", (60_000, 250_000)),
    ("implants", "Имплантация", (150_000, 600_000)),
    ("surgery", "Хирургия", (25_000, 120_000)),
    ("orthodontics", "Ортодонтия", (100_000, 400_000)),
    ("pediatric", "Детская стоматология", (6_000, 30_000)),
    ("other", "Прочие услуги", (3_000, 15_000)),
]

LEAD_SOURCES = ["facebook", "2gis", "organic", "referral"]
LEAD_SOURCE_WEIGHTS = [0.35, 0.30, 0.25, 0.10]

FIRST_NAMES = ["Айгерим", "Данияр", "Мадина", "Ерлан", "Сая", "Нурлан", "Жанна", "Бекзат",
               "Алия", "Тимур", "Гульнара", "Асхат", "Дана", "Максат", "Инкар", "Санжар"]
LAST_NAMES = ["Ахметова", "Тулегенов", "Байжанова", "Серikов", "Омарова", "Касымов",
              "Нурланова", "Жумабаев", "Сатпаева", "Ибрагимов"]

EXPENSE_CATEGORIES = [
    # (name, cost_behavior, cost_traceability, monthly_range_per_branch)
    ("Аренда", "fixed", "indirect", (450_000, 450_000)),
    ("Коммунальные", "fixed", "indirect", (80_000, 140_000)),
    ("CRM", "fixed", "indirect", (35_000, 35_000)),
    ("IT", "fixed", "indirect", (60_000, 120_000)),
    ("Лицензии", "fixed", "indirect", (25_000, 25_000)),
    ("ФОТ управление", "fixed", "indirect", (600_000, 600_000)),
    ("ФОТ администраторы", "fixed", "direct", (350_000, 450_000)),
    ("ФОТ ассистенты", "fixed", "direct", (400_000, 520_000)),
    ("Материалы", "variable", "direct", (300_000, 900_000)),
    ("Лаборатория", "variable", "direct", (200_000, 700_000)),
    ("Закупки", "variable", "direct", (150_000, 400_000)),
    ("Маркетинг Facebook", "variable", "indirect", (150_000, 350_000)),
    ("Маркетинг 2ГИС", "variable", "indirect", (40_000, 90_000)),
]

DOCTOR_SPECIALTIES = ["Терапевт", "Ортопед", "Имплантолог", "Хирург", "Ортодонт", "Детский стоматолог"]

DOMAIN_TABLES_IN_DELETE_ORDER = [
    AttributionFact, MarketingSpendFact, CashFlowFact, AccountBalance,
    RevenueFact, ExpenseFact, ExpenseCategory,
    TreatmentPlan, Appointment, Call, Lead, DoctorRating, DoctorCompensationRule,
    Doctor, ServiceDirection, Patient,
]


def phone_hash(digits10: str) -> str:
    """Тот же алгоритм, что в integrations/canonical_writer.py — держим demo-данные
    совместимыми с реальным ETL-пайплайном 1С/банков."""
    return sha256(f"+7{digits10}".encode()).hexdigest()


def random_phone() -> str:
    return "".join(str(RNG.randint(0, 9)) for _ in range(10))


def random_name() -> str:
    return f"{RNG.choice(FIRST_NAMES)} {RNG.choice(LAST_NAMES)}"


def weighted_source() -> str:
    return RNG.choices(LEAD_SOURCES, weights=LEAD_SOURCE_WEIGHTS, k=1)[0]


async def reset_tenant_data(session, tenant_id: UUID) -> None:
    for model in DOMAIN_TABLES_IN_DELETE_ORDER:
        await session.execute(delete(model).where(model.tenant_id == tenant_id))
    await session.execute(
        delete(UserBranch).where(
            UserBranch.user_id.in_(select(User.id).where(User.tenant_id == tenant_id))
        )
    )
    await session.execute(delete(User).where(User.tenant_id == tenant_id))


async def get_or_create_tenant(session, slug: str, name: str) -> Tenant:
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant:
        return tenant
    tenant = Tenant(name=name, slug=slug)
    session.add(tenant)
    await session.flush()
    return tenant


async def get_or_create_branches(session, tenant_id: UUID) -> list[Branch]:
    existing = (
        await session.scalars(select(Branch).where(Branch.tenant_id == tenant_id))
    ).all()
    if existing:
        return list(existing)
    branches = [
        Branch(tenant_id=tenant_id, name="SAN Seifullina", code="seifullina"),
        Branch(tenant_id=tenant_id, name="SAN Batysmura", code="batysmura"),
    ]
    session.add_all(branches)
    await session.flush()
    return branches


async def create_users(
    session, tenant_id: UUID, branches: list[Branch], password: str
) -> tuple[list[User], dict[UUID, UUID]]:
    """Возвращает (все пользователи, {branch_id: sales_manager_user_id})."""
    users = [
        User(tenant_id=tenant_id, email="owner@sandental.demo", full_name="Собственник Демо",
             password_hash=hash_password(password), role=UserRole.OWNER, is_active=True),
        User(tenant_id=tenant_id, email="manager@sandental.demo", full_name="Управляющий Демо",
             password_hash=hash_password(password), role=UserRole.MANAGER, is_active=True),
    ]
    for branch in branches:
        users.append(User(
            tenant_id=tenant_id, email=f"admin.{branch.code}@sandental.demo",
            full_name=f"Администратор {branch.name}", password_hash=hash_password(password),
            role=UserRole.ADMINISTRATOR, is_active=True,
        ))
        users.append(User(
            tenant_id=tenant_id, email=f"sales.{branch.code}@sandental.demo",
            full_name=f"Менеджер продаж {branch.name}", password_hash=hash_password(password),
            role=UserRole.SALES_MANAGER, is_active=True,
        ))
    session.add_all(users)
    await session.flush()

    links = []
    for user in users:
        if user.role in (UserRole.OWNER, UserRole.MANAGER):
            for branch in branches:
                links.append(UserBranch(user_id=user.id, branch_id=branch.id))
        else:
            branch = next(b for b in branches if b.code in user.email)
            links.append(UserBranch(user_id=user.id, branch_id=branch.id))
    session.add_all(links)

    sales_manager_by_branch = {
        branch.id: next(
            u.id for u in users
            if u.role == UserRole.SALES_MANAGER and branch.code in u.email
        )
        for branch in branches
    }
    return users, sales_manager_by_branch


async def create_directions(session, tenant_id: UUID) -> dict[str, ServiceDirection]:
    directions = {}
    for code, name, _ in DIRECTIONS:
        direction = ServiceDirection(tenant_id=tenant_id, external_id=f"seed-dir-{code}", name=name)
        session.add(direction)
        directions[code] = direction
    await session.flush()
    return directions


async def create_doctors(session, tenant_id: UUID, branches: list[Branch]) -> list[Doctor]:
    doctors: list[Doctor] = []
    for branch in branches:
        for i in range(5):
            specialty = DOCTOR_SPECIALTIES[i % len(DOCTOR_SPECIALTIES)]
            doctor = Doctor(
                tenant_id=tenant_id,
                external_id=f"seed-doc-{branch.code}-{i}",
                full_name=random_name(),
                specialty=specialty,
            )
            session.add(doctor)
            doctors.append(doctor)
    await session.flush()

    for doctor in doctors:
        if RNG.random() < 0.7:
            rule = DoctorCompensationRule(
                tenant_id=tenant_id, doctor_id=doctor.id,
                valid_from=date.today() - timedelta(days=180), valid_to=None,
                percentage_value=Decimal(RNG.randint(25, 40)), fixed_amount=None,
            )
        else:
            rule = DoctorCompensationRule(
                tenant_id=tenant_id, doctor_id=doctor.id,
                valid_from=date.today() - timedelta(days=180), valid_to=None,
                percentage_value=None, fixed_amount=Decimal(RNG.randint(300_000, 500_000)),
            )
        session.add(rule)

        for _ in range(RNG.randint(1, 4)):
            session.add(DoctorRating(
                tenant_id=tenant_id, doctor_id=doctor.id, source="2gis",
                rating=Decimal(str(round(RNG.uniform(3.8, 5.0), 2))),
                reviews_count=RNG.randint(3, 60),
                rated_at=datetime.now(UTC) - timedelta(days=RNG.randint(1, 300)),
            ))
    return doctors


async def create_expense_categories(session, tenant_id: UUID) -> dict[str, ExpenseCategory]:
    categories = {}
    for name, behavior, traceability, _ in EXPENSE_CATEGORIES:
        category = ExpenseCategory(
            tenant_id=tenant_id, name=name, cost_behavior=behavior, cost_traceability=traceability,
        )
        session.add(category)
        categories[name] = category
    await session.flush()
    return categories


def pick_direction() -> tuple[str, str, tuple[int, int]]:
    return RNG.choice(DIRECTIONS)


async def seed_operational_data(
    session, tenant_id: UUID, branches: list[Branch], doctors: list[Doctor],
    directions: dict[str, ServiceDirection], sales_manager_by_branch: dict[UUID, UUID],
    months: int,
) -> None:
    window_start = date.today() - timedelta(days=30 * months)
    window_end = date.today()
    doctors_by_branch = {
        branch.id: [d for d in doctors if d.external_id.startswith(f"seed-doc-{branch.code}")]
        for branch in branches
    }

    patients_per_branch = 150
    for branch in branches:
        branch_doctors = doctors_by_branch[branch.id]
        for p_index in range(patients_per_branch):
            created_day = window_start + timedelta(days=RNG.randint(0, 30 * months - 1))
            source = weighted_source()
            digits = random_phone()
            patient = Patient(
                tenant_id=tenant_id, external_id=f"seed-pat-{branch.code}-{p_index}",
                full_name=random_name(), phone_e164_encrypted=None,
                phone_hash=phone_hash(digits), lead_source=source,
            )
            session.add(patient)
            await session.flush()

            is_won = RNG.random() < 0.82  # доля лидов, дошедших до пациента/оплаты
            # 70% лидов ведёт менеджер по продажам филиала — остальные (например,
            # пришедшие напрямую к администратору) остаются без персонального владельца
            assigned_user_id = (
                sales_manager_by_branch[branch.id] if RNG.random() < 0.7 else None
            )
            lead = Lead(
                tenant_id=tenant_id, branch_id=branch.id, patient_id=patient.id,
                assigned_user_id=assigned_user_id,
                external_id=f"seed-lead-{branch.code}-{p_index}",
                source=source, status="won" if is_won else RNG.choice(["lost", "new", "qualified"]),
            )
            lead.created_at = datetime.combine(created_day, datetime.min.time(), tzinfo=UTC)
            session.add(lead)
            await session.flush()

            if source in ("facebook", "2gis") and RNG.random() < 0.6:
                session.add(Call(
                    tenant_id=tenant_id, branch_id=branch.id, lead_id=lead.id,
                    external_id=f"seed-call-{branch.code}-{p_index}",
                    phone_hash=patient.phone_hash, direction="in",
                    started_at=datetime.combine(created_day, datetime.min.time(), tzinfo=UTC)
                    + timedelta(minutes=RNG.randint(0, 600)),
                    duration_seconds=RNG.randint(15, 420),
                    outcome=RNG.choice(["answered", "answered", "missed"]),
                ))

            if not is_won:
                continue  # без визитов/выручки для нереализованных лидов

            visits = RNG.randint(1, 5)
            first_visit_day = created_day + timedelta(days=RNG.randint(0, 5))
            revenue_fact_ids: list[UUID] = []
            for visit_index in range(visits):
                visit_day = first_visit_day + timedelta(days=30 * visit_index + RNG.randint(0, 10))
                if visit_day > window_end:
                    break
                doctor = RNG.choice(branch_doctors)
                dir_code, _, price_range = pick_direction()
                direction = directions[dir_code]
                status = RNG.choices(
                    ["completed", "cancelled", "no_show", "confirmed"],
                    weights=[0.78, 0.08, 0.09, 0.05], k=1,
                )[0]
                starts_at = datetime.combine(visit_day, datetime.min.time(), tzinfo=UTC) + timedelta(
                    hours=RNG.randint(9, 18)
                )
                appointment = Appointment(
                    tenant_id=tenant_id, branch_id=branch.id, patient_id=patient.id,
                    doctor_id=doctor.id, direction_id=direction.id,
                    external_id=f"seed-apt-{branch.code}-{p_index}-{visit_index}",
                    starts_at=starts_at, status=status,
                )
                session.add(appointment)
                await session.flush()

                if visit_index == 0 and RNG.random() < 0.9:
                    plan_status = RNG.choice(["accepted", "paid", "completed"])
                    session.add(TreatmentPlan(
                        tenant_id=tenant_id, patient_id=patient.id,
                        external_id=f"seed-plan-{branch.code}-{p_index}",
                        status=plan_status, accepted_at=starts_at,
                    ))

                if status != "completed":
                    continue

                amount = Decimal(RNG.randint(*price_range))
                accrual = RevenueFact(
                    tenant_id=tenant_id, branch_id=branch.id, patient_id=patient.id,
                    doctor_id=doctor.id, external_id=appointment.external_id,
                    recognition_type="accrual", occurred_at=starts_at, amount=amount,
                )
                session.add(accrual)
                if RNG.random() < 0.9:  # часть выручки ещё не оплачена (рассрочка/долг)
                    payment_delay = timedelta(days=RNG.randint(0, 14))
                    payment = RevenueFact(
                        tenant_id=tenant_id, branch_id=branch.id, patient_id=patient.id,
                        doctor_id=doctor.id, external_id=appointment.external_id,
                        recognition_type="payment", occurred_at=starts_at + payment_delay,
                        amount=amount,
                    )
                    session.add(payment)
                    await session.flush()
                    revenue_fact_ids.append(payment.id)

            if source in ("facebook", "2gis") and revenue_fact_ids:
                target = RNG.choice(revenue_fact_ids)
                target_row = await session.get(RevenueFact, target)
                session.add(AttributionFact(
                    tenant_id=tenant_id, lead_id=lead.id, revenue_fact_id=target,
                    source=source, confidence=Decimal("0.85"),
                    attributed_amount=target_row.amount,
                ))


async def seed_expenses_and_cashflow(
    session, tenant_id: UUID, branches: list[Branch], categories: dict[str, ExpenseCategory], months: int,
) -> None:
    window_start = date.today().replace(day=1) - timedelta(days=30 * (months - 1))
    month_starts = []
    cursor = window_start.replace(day=1)
    while cursor <= date.today():
        month_starts.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)

    seq = 0
    for branch in branches:
        for month_start in month_starts:
            for name, _, _, (low, high) in EXPENSE_CATEGORIES:
                seq += 1
                occurred_on = month_start + timedelta(days=RNG.randint(0, 20))
                if occurred_on > date.today():
                    occurred_on = date.today()
                amount = Decimal(RNG.randint(low, high))
                expense = ExpenseFact(
                    tenant_id=tenant_id, branch_id=branch.id, category_id=categories[name].id,
                    external_id=f"seed-exp-{branch.code}-{seq}", occurred_on=occurred_on,
                    amount=amount, counterparty=name, description=f"{name} — {branch.name}",
                )
                session.add(expense)
                session.add(CashFlowFact(
                    tenant_id=tenant_id, branch_id=branch.id, raw_transaction_id=None,
                    external_id=f"seed-cf-out-{branch.code}-{seq}", category_id=categories[name].id,
                    occurred_at=datetime.combine(occurred_on, datetime.min.time(), tzinfo=UTC),
                    direction="out", amount=amount,
                ))

                if "Маркетинг" in name:
                    source = "facebook" if "Facebook" in name else "2gis"
                    session.add(MarketingSpendFact(
                        tenant_id=tenant_id, branch_id=branch.id, source=source,
                        external_id=f"seed-mkt-{branch.code}-{seq}", campaign_name=f"{source}-campaign",
                        spend_date=occurred_on, amount=amount,
                    ))

    # притоки в ДДС — берём из уже созданных RevenueFact(payment) этого тенанта
    payment_rows = (
        await session.scalars(
            select(RevenueFact).where(
                RevenueFact.tenant_id == tenant_id, RevenueFact.recognition_type == "payment"
            )
        )
    ).all()
    for row in payment_rows:
        session.add(CashFlowFact(
            tenant_id=tenant_id, branch_id=row.branch_id, raw_transaction_id=None,
            external_id=f"seed-cf-in-{row.external_id}", category_id=None,
            occurred_at=row.occurred_at, direction="in", amount=row.amount,
        ))

    # остатки на счетах — недельные точки по каждому филиалу
    for branch in branches:
        balance = Decimal(RNG.randint(2_000_000, 5_000_000))
        cursor_date = window_start
        while cursor_date <= date.today():
            balance += Decimal(RNG.randint(-300_000, 500_000))
            if balance < Decimal("0"):
                balance = Decimal("100000")
            session.add(AccountBalance(
                tenant_id=tenant_id, branch_id=branch.id, account_ref=f"kaspi_main_{branch.code}",
                balance_at=datetime.combine(cursor_date, datetime.min.time(), tzinfo=UTC),
                amount=balance,
            ))
            cursor_date += timedelta(days=7)


async def seed(args: argparse.Namespace) -> None:
    async with AsyncSessionFactory() as session, session.begin():
        tenant = await get_or_create_tenant(session, args.tenant_slug, args.tenant_name)
        await AuthRepository(session).set_tenant_context(tenant.id)

        if args.reset:
            await reset_tenant_data(session, tenant.id)
            await session.flush()

        branches = await get_or_create_branches(session, tenant.id)
        users, sales_manager_by_branch = await create_users(session, tenant.id, branches, args.password)
        directions = await create_directions(session, tenant.id)
        doctors = await create_doctors(session, tenant.id, branches)
        categories = await create_expense_categories(session, tenant.id)
        await seed_operational_data(
            session, tenant.id, branches, doctors, directions, sales_manager_by_branch, args.months
        )
        await seed_expenses_and_cashflow(session, tenant.id, branches, categories, args.months)

    print(f"Готово. Tenant slug: {tenant.slug}")
    print(f"Филиалы: {', '.join(b.code for b in branches)}")
    print("Пользователи (пароль одинаковый для всех, см. --password):")
    for user in users:
        print(f"  {user.role.value:<15} {user.email}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-slug", default="san-dental-demo")
    parser.add_argument("--tenant-name", default="SAN Dental Clinic (Demo)")
    parser.add_argument("--password", default="Demo12345!")
    parser.add_argument("--months", type=int, default=4, help="Глубина истории в месяцах")
    parser.add_argument(
        "--reset", action="store_true",
        help="Удалить существующие данные этого tenant перед повторным заполнением",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(seed(parse_args()))
