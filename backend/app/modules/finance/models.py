"""Canonical accrual, payment, expense and bank statement facts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RevenueFact(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "revenue_facts"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id", "recognition_type"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    patient_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("patients.id"))
    doctor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("doctors.id"))
    external_id: Mapped[str] = mapped_column(String(150))
    recognition_type: Mapped[str] = mapped_column(String(20))  # accrual | payment
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KZT")


class ExpenseCategory(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "expense_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    parent_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("expense_categories.id"))
    cost_behavior: Mapped[str | None] = mapped_column(String(20))
    cost_traceability: Mapped[str | None] = mapped_column(String(20))


class ExpenseFact(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "expense_facts"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    category_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("expense_categories.id"))
    external_id: Mapped[str] = mapped_column(String(150))
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
    counterparty: Mapped[str | None] = mapped_column(String(250))
    description: Mapped[str | None] = mapped_column(Text)


class BankStatementUpload(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "bank_statement_uploads"
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"))
    uploaded_by_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    bank: Mapped[str] = mapped_column(String(30))
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)


class RawBankTransaction(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "raw_bank_transactions"
    __table_args__ = (UniqueConstraint("tenant_id", "transaction_hash"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    upload_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("bank_statement_uploads.id", ondelete="CASCADE"), index=True)
    transaction_hash: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
    counterparty: Mapped[str | None] = mapped_column(String(250))
    purpose: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSONB)


class CashFlowFact(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "cash_flow_facts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "raw_transaction_id", name="uq_cash_flow_facts_tenant_raw_transaction"),
        UniqueConstraint("tenant_id", "external_id", name="uq_cash_flow_facts_tenant_external_id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    raw_transaction_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("raw_bank_transactions.id"))
    external_id: Mapped[str | None] = mapped_column(String(150))
    category_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("expense_categories.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KZT")


class AccountBalance(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "account_balances"
    __table_args__ = (UniqueConstraint("tenant_id", "account_ref", "balance_at"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"))
    account_ref: Mapped[str] = mapped_column(String(100))
    balance_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
