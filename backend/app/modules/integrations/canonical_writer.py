"""Load normalized dictionaries into the source-agnostic canonical model."""

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.doctors.models import Doctor, DoctorRating
from app.modules.finance.models import AccountBalance, CashFlowFact, ExpenseCategory, ExpenseFact, RevenueFact
from app.modules.marketing.models import AttributionFact, MarketingSpendFact
from app.modules.sales.models import Appointment, Lead, Patient, ServiceDirection
from app.modules.tenancy.models import Branch


class CanonicalWriteError(ValueError):
    pass


class CanonicalWriter:
    """Explicit target registry; mapping profiles cannot select arbitrary tables."""

    SUPPORTED_TARGETS = {
        "patient",
        "doctor",
        "service_direction",
        "lead",
        "appointment",
        "revenue_fact",
        "expense_fact",
        "cash_flow_fact",
        "marketing_spend_fact",
        "attribution_fact",
        "account_balance",
        "doctor_rating",
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(
        self, *, tenant_id: UUID, target_entity: str, data: dict[str, object]
    ) -> UUID:
        target = target_entity.strip().lower()
        if target not in self.SUPPORTED_TARGETS:
            raise CanonicalWriteError(f"Unsupported canonical target '{target}'")
        handler = getattr(self, f"_write_{target}")
        return await handler(tenant_id, data)

    async def _write_patient(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        external_id = self._string(data, "external_id")
        phone = self._optional_string(data, "phone")
        values = {
            "tenant_id": tenant_id,
            "external_id": external_id,
            "full_name": self._optional_string(data, "full_name"),
            "phone_e164_encrypted": None,
            "phone_hash": self._phone_hash(phone) if phone else None,
            "lead_source": self._optional_string(data, "lead_source"),
        }
        return await self._upsert(
            Patient,
            values,
            ["tenant_id", "external_id"],
            ["full_name", "phone_hash", "lead_source"],
        )

    async def _write_doctor(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        values = {
            "tenant_id": tenant_id,
            "external_id": self._string(data, "external_id"),
            "full_name": self._string(data, "full_name"),
            "specialty": self._optional_string(data, "specialty"),
        }
        return await self._upsert(
            Doctor,
            values,
            ["tenant_id", "external_id"],
            ["full_name", "specialty"],
        )

    async def _write_service_direction(
        self, tenant_id: UUID, data: dict[str, object]
    ) -> UUID:
        values = {
            "tenant_id": tenant_id,
            "external_id": self._string(data, "external_id"),
            "name": self._string(data, "name"),
        }
        return await self._upsert(
            ServiceDirection,
            values,
            ["tenant_id", "external_id"],
            ["name"],
        )

    async def _write_lead(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        values = {
            "tenant_id": tenant_id,
            "branch_id": await self._branch_id(tenant_id, data),
            "patient_id": await self._optional_external_id(
                Patient, tenant_id, self._optional_string(data, "patient_external_id")
            ),
            "assigned_user_id": await self._optional_user_id(
                tenant_id, self._optional_string(data, "assigned_user_email")
            ),
            "external_id": self._string(data, "external_id"),
            "source": self._string(data, "source"),
            "status": self._string(data, "status"),
        }
        return await self._upsert(
            Lead,
            values,
            ["tenant_id", "external_id"],
            ["branch_id", "patient_id", "assigned_user_id", "source", "status"],
        )

    async def _write_appointment(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        patient_id = await self._required_external_id(
            Patient, tenant_id, self._string(data, "patient_external_id"), "patient"
        )
        doctor_id = await self._optional_external_id(
            Doctor, tenant_id, self._optional_string(data, "doctor_external_id")
        )
        direction_id = await self._optional_external_id(
            ServiceDirection,
            tenant_id,
            self._optional_string(data, "direction_external_id"),
        )
        values = {
            "tenant_id": tenant_id,
            "branch_id": await self._branch_id(tenant_id, data),
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "direction_id": direction_id,
            "external_id": self._string(data, "external_id"),
            "starts_at": self._datetime(data, "starts_at"),
            "status": self._string(data, "status"),
        }
        return await self._upsert(
            Appointment,
            values,
            ["tenant_id", "external_id"],
            ["branch_id", "patient_id", "doctor_id", "direction_id", "starts_at", "status"],
        )

    async def _write_revenue_fact(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        recognition_type = self._string(data, "recognition_type").lower()
        if recognition_type not in {"accrual", "payment"}:
            raise CanonicalWriteError("recognition_type must be 'accrual' or 'payment'")
        values = {
            "tenant_id": tenant_id,
            "branch_id": await self._branch_id(tenant_id, data),
            "patient_id": await self._optional_external_id(
                Patient, tenant_id, self._optional_string(data, "patient_external_id")
            ),
            "doctor_id": await self._optional_external_id(
                Doctor, tenant_id, self._optional_string(data, "doctor_external_id")
            ),
            "external_id": self._string(data, "external_id"),
            "recognition_type": recognition_type,
            "occurred_at": self._datetime(data, "occurred_at"),
            "amount": self._decimal(data, "amount"),
            "currency": self._optional_string(data, "currency") or "KZT",
        }
        return await self._upsert(
            RevenueFact,
            values,
            ["tenant_id", "external_id", "recognition_type"],
            ["branch_id", "patient_id", "doctor_id", "occurred_at", "amount", "currency"],
        )

    async def _write_expense_fact(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        category_name = self._optional_string(data, "category_name")
        category_id = await self._expense_category_id(
            tenant_id, category_name, self._optional_string(data, "cost_behavior")
        )
        values = {
            "tenant_id": tenant_id,
            "branch_id": await self._optional_branch_id(tenant_id, data),
            "category_id": category_id,
            "external_id": self._string(data, "external_id"),
            "occurred_on": self._date(data, "occurred_on"),
            "amount": self._decimal(data, "amount"),
            "currency": self._optional_string(data, "currency") or "KZT",
            "counterparty": self._optional_string(data, "counterparty"),
            "description": self._optional_string(data, "description"),
        }
        return await self._upsert(
            ExpenseFact,
            values,
            ["tenant_id", "external_id"],
            [
                "branch_id",
                "category_id",
                "occurred_on",
                "amount",
                "currency",
                "counterparty",
                "description",
            ],
        )

    async def _write_cash_flow_fact(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        direction = self._string(data, "direction").lower()
        if direction not in {"in", "out"}:
            raise CanonicalWriteError("direction must be 'in' or 'out'")
        category_id = await self._expense_category_id(
            tenant_id,
            self._optional_string(data, "category_name"),
            self._optional_string(data, "cost_behavior"),
        )
        values = {
            "tenant_id": tenant_id,
            "raw_transaction_id": None,
            "external_id": self._string(data, "external_id"),
            "branch_id": await self._optional_branch_id(tenant_id, data),
            "category_id": category_id,
            "occurred_at": self._datetime(data, "occurred_at"),
            "direction": direction,
            "amount": self._decimal(data, "amount"),
            "currency": self._optional_string(data, "currency") or "KZT",
        }
        return await self._upsert(
            CashFlowFact, values, ["tenant_id", "external_id"],
            ["branch_id", "category_id", "occurred_at", "direction", "amount", "currency"],
        )

    async def _write_marketing_spend_fact(
        self, tenant_id: UUID, data: dict[str, object]
    ) -> UUID:
        values = {
            "tenant_id": tenant_id,
            "branch_id": await self._optional_branch_id(tenant_id, data),
            "source": self._string(data, "source"),
            "external_id": self._string(data, "external_id"),
            "campaign_name": self._optional_string(data, "campaign_name"),
            "spend_date": self._date(data, "spend_date"),
            "amount": self._decimal(data, "amount"),
            "currency": self._optional_string(data, "currency") or "KZT",
        }
        return await self._upsert(
            MarketingSpendFact,
            values,
            ["tenant_id", "source", "external_id", "spend_date"],
            ["branch_id", "campaign_name", "amount", "currency"],
        )

    async def _write_account_balance(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        values = {
            "tenant_id": tenant_id,
            "branch_id": await self._optional_branch_id(tenant_id, data),
            "account_ref": self._string(data, "account_ref"),
            "balance_at": self._datetime(data, "balance_at"),
            "amount": self._decimal(data, "amount"),
            "currency": self._optional_string(data, "currency") or "KZT",
        }
        return await self._upsert(
            AccountBalance,
            values,
            ["tenant_id", "account_ref", "balance_at"],
            ["branch_id", "amount", "currency"],
        )

    async def _write_attribution_fact(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        lead_id = await self._required_external_id(
            Lead, tenant_id, self._string(data, "lead_external_id"), "lead"
        )
        revenue_external_id = self._string(data, "revenue_external_id")
        revenue_id = await self.session.scalar(select(RevenueFact.id).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.external_id == revenue_external_id,
        ).order_by((RevenueFact.recognition_type == "payment").desc()))
        if revenue_id is None:
            raise CanonicalWriteError(f"Unknown revenue external_id '{revenue_external_id}'")
        values = {
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "revenue_fact_id": revenue_id,
            "source": self._string(data, "source"),
            "confidence": self._decimal(data, "confidence") if data.get("confidence") is not None else Decimal("1"),
            "attributed_amount": self._decimal(data, "attributed_amount"),
            "currency": self._optional_string(data, "currency") or "KZT",
        }
        return await self._upsert(
            AttributionFact, values, ["tenant_id", "lead_id", "revenue_fact_id"],
            ["source", "confidence", "attributed_amount", "currency"],
        )

    async def _write_doctor_rating(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        doctor_id = await self._required_external_id(
            Doctor, tenant_id, self._string(data, "doctor_external_id"), "doctor"
        )
        values = {
            "tenant_id": tenant_id,
            "doctor_id": doctor_id,
            "source": self._string(data, "source"),
            "rating": self._decimal(data, "rating"),
            "reviews_count": int(data.get("reviews_count") or 0),
            "rated_at": self._datetime(data, "rated_at"),
        }
        return await self._upsert(
            DoctorRating, values, ["tenant_id", "doctor_id", "source", "rated_at"],
            ["rating", "reviews_count"],
        )

    async def _upsert(
        self,
        model,
        values: dict[str, object],
        conflict_columns: list[str],
        update_columns: list[str],
    ) -> UUID:
        statement = insert(model).values(id=uuid4(), **values)
        statement = statement.on_conflict_do_update(
            index_elements=conflict_columns,
            set_={column: getattr(statement.excluded, column) for column in update_columns},
        ).returning(model.id)
        return (await self.session.execute(statement)).scalar_one()

    async def _branch_id(self, tenant_id: UUID, data: dict[str, object]) -> UUID:
        branch_id = await self._optional_branch_id(tenant_id, data)
        if branch_id is None:
            raise CanonicalWriteError("branch_code is required")
        return branch_id

    async def _optional_branch_id(
        self, tenant_id: UUID, data: dict[str, object]
    ) -> UUID | None:
        code = self._optional_string(data, "branch_code")
        if not code:
            return None
        branch_id = await self.session.scalar(
            select(Branch.id).where(Branch.tenant_id == tenant_id, Branch.code == code)
        )
        if branch_id is None:
            raise CanonicalWriteError(f"Unknown branch_code '{code}'")
        return branch_id

    async def _required_external_id(
        self, model, tenant_id: UUID, external_id: str, label: str
    ) -> UUID:
        record_id = await self._optional_external_id(model, tenant_id, external_id)
        if record_id is None:
            raise CanonicalWriteError(f"Unknown {label} external_id '{external_id}'")
        return record_id

    async def _optional_external_id(
        self, model, tenant_id: UUID, external_id: str | None
    ) -> UUID | None:
        if not external_id:
            return None
        return await self.session.scalar(
            select(model.id).where(model.tenant_id == tenant_id, model.external_id == external_id)
        )

    async def _optional_user_id(self, tenant_id: UUID, email: str | None) -> UUID | None:
        if not email:
            return None
        return await self.session.scalar(
            select(User.id).where(User.tenant_id == tenant_id, User.email == email.lower())
        )

    async def _expense_category_id(
        self, tenant_id: UUID, name: str | None, behavior: str | None = None
    ) -> UUID | None:
        if not name:
            return None
        if behavior is not None:
            behavior = behavior.lower()
            if behavior not in {"fixed", "variable"}:
                raise CanonicalWriteError("cost_behavior must be 'fixed' or 'variable'")
        values = {"id": uuid4(), "tenant_id": tenant_id, "name": name, "cost_behavior": behavior}
        statement = insert(ExpenseCategory).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["tenant_id", "name"],
            set_={"name": statement.excluded.name, "cost_behavior": statement.excluded.cost_behavior},
        ).returning(ExpenseCategory.id)
        return (await self.session.execute(statement)).scalar_one()

    @staticmethod
    def _string(data: dict[str, object], field: str) -> str:
        value = data.get(field)
        if value is None or not str(value).strip():
            raise CanonicalWriteError(f"{field} is required")
        return str(value).strip()

    @classmethod
    def _optional_string(cls, data: dict[str, object], field: str) -> str | None:
        value = data.get(field)
        return str(value).strip() if value is not None and str(value).strip() else None

    @staticmethod
    def _decimal(data: dict[str, object], field: str) -> Decimal:
        value = data.get(field)
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception as exc:
            raise CanonicalWriteError(f"{field} must be a decimal") from exc

    @staticmethod
    def _date(data: dict[str, object], field: str) -> date:
        value = data.get(field)
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise CanonicalWriteError(f"{field} must be an ISO date") from exc

    @staticmethod
    def _datetime(data: dict[str, object], field: str) -> datetime:
        value = data.get(field)
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise CanonicalWriteError(f"{field} must be an ISO datetime") from exc

    @staticmethod
    def _phone_hash(phone: str) -> str:
        digits = "".join(character for character in phone if character.isdigit())
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        elif len(digits) == 10:
            digits = "7" + digits
        if len(digits) < 10:
            raise CanonicalWriteError("phone has too few digits")
        return sha256(f"+{digits}".encode()).hexdigest()
