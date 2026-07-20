"""Central model registry used by Alembic without coupling business modules."""

from app.modules.auth.models import RefreshToken, User, UserBranch
from app.modules.admin.models import AuditLog
from app.modules.ai.models import AIClassificationFeedback, AIInsight, AIInsightRead
from app.modules.doctors.models import Doctor, DoctorCompensationRule, DoctorRating
from app.modules.finance.models import (
    AccountBalance, BankStatementUpload, CashFlowFact, ExpenseCategory, ExpenseFact,
    RawBankTransaction, RevenueFact,
)
from app.modules.integrations.models import (
    IntegrationConnection,
    MappingProfile,
    NormalizationError,
    RawRecord,
    RecordLineage,
    SyncRun,
)
from app.modules.marketing.models import AttributionFact, MarketingSpendFact
from app.modules.sales.models import Appointment, Call, Lead, Patient, ServiceDirection, TreatmentPlan
from app.modules.tenancy.models import Branch, Tenant

__all__ = [name for name in globals() if not name.startswith("_")]
