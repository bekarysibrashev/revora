"""Central model registry used by Alembic without coupling business modules."""

from app.modules.auth.models import RefreshToken, User, UserBranch
from app.modules.admin.models import AuditLog
from app.modules.ai.models import (
    AIClassificationFeedback,
    AIInsight,
    AIInsightRead,
    AIChatSession,
    AIChatMessage,
    AILLMCallAudit,
)
from app.modules.ai.call_quality.models import CallQualityAnalysis, CallQualityRuleSet
from app.modules.contacts.models import ContactIdentity
from app.modules.doctors.models import Doctor, DoctorCompensationRule, DoctorRating
from app.modules.finance.models import (
    AccountBalance, BankStatementUpload, CashFlowFact, ExpenseCategory, ExpenseFact,
    PayrollFact, RawBankTransaction, RevenueFact,
)
from app.modules.integrations.models import (
    IntegrationConnection,
    MappingProfile,
    NormalizationError,
    OneCMetadataSnapshot,
    RawRecord,
    RecordLineage,
    SyncRun,
)
from app.modules.marketing.models import (
    AttributionFact,
    MarketingSpendFact,
    MetaAdsAccount,
    MetaCampaignDailyMetric,
)
from app.modules.sales.models import Appointment, Call, Lead, Patient, ServiceDirection, TreatmentPlan
from app.modules.kcell.models import KcellWebhookReceipt
from app.modules.losses.models import LossOpportunity
from app.modules.ml.models import MLDatasetSnapshot, MLExperiment, MLModelVersion, MLPrediction
from app.modules.reports.models import OfficialReportImport, OfficialReportMetric
from app.modules.tenancy.models import Branch, Tenant
from app.modules.whatsapp.models import (
    WhatsAppAIUsage,
    WhatsAppChannel,
    WhatsAppConversation,
    WhatsAppKnowledgeItem,
    WhatsAppMessage,
    WhatsAppQrSession,
)

__all__ = [name for name in globals() if not name.startswith("_")]
