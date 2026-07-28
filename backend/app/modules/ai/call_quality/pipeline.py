"""Idempotent automatic call-intelligence pipeline."""
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.ai.call_quality.audio import RecordingLoader
from app.modules.ai.call_quality.intelligence import (
    CallIntelligenceClient,
    CallIntelligenceError,
    CallReport,
    GroqCallIntelligenceClient,
    OpenAICallIntelligenceClient,
)
from app.modules.ai.call_quality.models import CallQualityAnalysis, CallQualityRuleSet
from app.modules.sales.models import Call


FINAL_STATUSES = {"ready", "needs_review", "skipped_short", "failed"}
RUNNABLE_STATUSES = {"pending", "queued", "retrying"}


class CallQualityPipeline:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        loader: RecordingLoader | None = None,
        client: CallIntelligenceClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.loader = loader or RecordingLoader(settings)
        self.client = client or self._default_client(settings)

    @staticmethod
    def _default_client(settings: Settings) -> CallIntelligenceClient:
        common = {
            "transcription_model": settings.call_transcription_model,
            "analysis_model": settings.call_analysis_model,
            "timeout_seconds": settings.call_analysis_timeout_seconds,
        }
        if settings.call_ai_provider == "groq":
            return GroqCallIntelligenceClient(
                api_key=settings.groq_api_key.get_secret_value(),
                base_url=settings.groq_base_url,
                **common,
            )
        return OpenAICallIntelligenceClient(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            **common,
        )

    async def _set_tenant_context(self, tenant_id: UUID) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    async def _commit_for_tenant(self, tenant_id: UUID) -> None:
        # set_config(..., true) is transaction-local and is cleared by every
        # commit. Disable autoflush while restoring it so PostgreSQL RLS sees
        # the tenant before SQLAlchemy sends pending UPDATE statements.
        with self.session.no_autoflush:
            await self._set_tenant_context(tenant_id)
        await self.session.commit()

    async def run(self, tenant_id: UUID, analysis_id: UUID) -> bool:
        """Process one report. Return True only when a transient retry is needed."""
        await self._set_tenant_context(tenant_id)
        analysis = await self.session.scalar(
            select(CallQualityAnalysis)
            .where(
                CallQualityAnalysis.tenant_id == tenant_id,
                CallQualityAnalysis.id == analysis_id,
            )
            .with_for_update()
        )
        if analysis is None or analysis.status not in RUNNABLE_STATUSES:
            return False
        call = await self.session.scalar(
            select(Call).where(Call.tenant_id == tenant_id, Call.id == analysis.call_id)
        )
        rules = await self.session.scalar(
            select(CallQualityRuleSet).where(
                CallQualityRuleSet.tenant_id == tenant_id,
                CallQualityRuleSet.id == analysis.rule_set_id,
            )
        )
        if call is None or rules is None:
            return await self._fail(analysis, None, "PIPELINE_DATA_MISSING", "Call or rule set no longer exists", False)
        if call.duration_seconds is not None and call.duration_seconds <= self.settings.call_min_duration_seconds:
            analysis.status = "skipped_short"
            analysis.completed_at = datetime.now(UTC)
            await self._commit_for_tenant(tenant_id)
            return False
        if not call.recording_url:
            analysis.status = "waiting_for_recording"
            await self._commit_for_tenant(tenant_id)
            return False

        analysis.status = "processing"
        analysis.processing_started_at = datetime.now(UTC)
        analysis.attempt_count += 1
        analysis.error_code = None
        analysis.error_message = None
        await self._commit_for_tenant(tenant_id)

        audio = transcript = None
        try:
            audio, filename, content_type = await self.loader.load(call.recording_url)
            transcript = await self.client.transcribe(
                audio, filename=filename, content_type=content_type
            )
            if transcript.duration <= self.settings.call_min_duration_seconds:
                call.duration_seconds = round(transcript.duration)
                analysis.status = "skipped_short"
                analysis.completed_at = datetime.now(UTC)
                await self.loader.delete_if_temporary(call.recording_url)
                if call.recording_url.startswith("minio://"):
                    call.recording_url = None
                await self._commit_for_tenant(tenant_id)
                return False
            report = await self.client.analyze(
                transcript,
                {
                    "name": rules.name,
                    "success_definition": rules.success_definition,
                    "partial_success_definition": rules.partial_success_definition,
                    "loss_definition": rules.loss_definition,
                    "criteria": rules.criteria,
                    "loss_reasons": rules.loss_reasons,
                },
            )
            self._validate_and_apply(analysis, report, rules, transcript.duration)
            call.duration_seconds = call.duration_seconds or round(transcript.duration)
            await self.loader.delete_if_temporary(call.recording_url)
            if call.recording_url.startswith("minio://"):
                call.recording_url = None
            await self._commit_for_tenant(tenant_id)
            return False
        except CallIntelligenceError as exc:
            await self.session.rollback()
            await self._set_tenant_context(tenant_id)
            analysis = await self.session.scalar(
                select(CallQualityAnalysis)
                .where(
                    CallQualityAnalysis.tenant_id == tenant_id,
                    CallQualityAnalysis.id == analysis_id,
                )
                .with_for_update()
            )
            call = await self.session.scalar(
                select(Call).where(Call.tenant_id == tenant_id, Call.id == analysis.call_id)
            ) if analysis else None
            return await self._fail(analysis, call, exc.code, str(exc), exc.retryable)
        finally:
            # The transcript and audio bytes have no persistent references and
            # become unreachable when this method returns.
            audio = None
            transcript = None

    async def run_inline_audio(
        self,
        tenant_id: UUID,
        analysis_id: UUID,
        audio: bytes,
        *,
        filename: str,
        content_type: str,
    ) -> str:
        """Run a manual test in the API process without persisting audio or transcript."""
        await self._set_tenant_context(tenant_id)
        analysis = await self.session.scalar(
            select(CallQualityAnalysis)
            .where(
                CallQualityAnalysis.tenant_id == tenant_id,
                CallQualityAnalysis.id == analysis_id,
            )
            .with_for_update()
        )
        if analysis is None:
            raise CallIntelligenceError(
                "PIPELINE_DATA_MISSING", "Manual analysis no longer exists", retryable=False
            )
        call = await self.session.scalar(
            select(Call).where(Call.tenant_id == tenant_id, Call.id == analysis.call_id)
        )
        rules = await self.session.scalar(
            select(CallQualityRuleSet).where(
                CallQualityRuleSet.tenant_id == tenant_id,
                CallQualityRuleSet.id == analysis.rule_set_id,
            )
        )
        if call is None or rules is None:
            await self._fail(
                analysis, call, "PIPELINE_DATA_MISSING",
                "Call or rule set no longer exists", False,
            )
            return "failed"
        analysis.status = "processing"
        analysis.processing_started_at = datetime.now(UTC)
        analysis.attempt_count += 1
        await self._commit_for_tenant(tenant_id)

        transcript = None
        try:
            transcript = await self.client.transcribe(
                audio, filename=filename, content_type=content_type
            )
            call.duration_seconds = round(transcript.duration)
            if transcript.duration <= self.settings.call_min_duration_seconds:
                analysis.status = "skipped_short"
                analysis.completed_at = datetime.now(UTC)
                await self._commit_for_tenant(tenant_id)
                return analysis.status
            report = await self.client.analyze(
                transcript,
                {
                    "name": rules.name,
                    "success_definition": rules.success_definition,
                    "partial_success_definition": rules.partial_success_definition,
                    "loss_definition": rules.loss_definition,
                    "criteria": rules.criteria,
                    "loss_reasons": rules.loss_reasons,
                },
            )
            self._validate_and_apply(analysis, report, rules, transcript.duration)
            await self._commit_for_tenant(tenant_id)
            return analysis.status
        except CallIntelligenceError as exc:
            await self.session.rollback()
            await self._set_tenant_context(tenant_id)
            analysis = await self.session.scalar(
                select(CallQualityAnalysis).where(
                    CallQualityAnalysis.tenant_id == tenant_id,
                    CallQualityAnalysis.id == analysis_id,
                )
            )
            call = await self.session.scalar(
                select(Call).where(Call.tenant_id == tenant_id, Call.id == analysis.call_id)
            ) if analysis else None
            await self._fail(analysis, call, exc.code, str(exc), False)
            return "failed"
        finally:
            transcript = None

    def _validate_and_apply(
        self,
        analysis: CallQualityAnalysis,
        report: CallReport,
        rules: CallQualityRuleSet,
        duration: float,
    ) -> None:
        configured = {item["name"].casefold(): item for item in rules.criteria}
        returned = {item.name.casefold(): item for item in report.criteria_scores}
        if configured.keys() != returned.keys():
            raise CallIntelligenceError(
                "ANALYSIS_CRITERIA_MISMATCH",
                "The report did not score the configured criteria",
                retryable=False,
            )
        for item in report.evidence:
            if item.timestamp_to < item.timestamp_from or item.timestamp_to > duration + 1:
                raise CallIntelligenceError(
                    "ANALYSIS_EVIDENCE_INVALID",
                    "The report contains invalid evidence timestamps",
                    retryable=False,
                )
        weighted = round(sum(
            returned[name].score * int(criterion["weight"]) / 100
            for name, criterion in configured.items()
        ))
        analysis.result = report.result
        analysis.score = weighted
        analysis.summary = report.summary
        analysis.operator_speaker = report.operator_speaker
        analysis.customer_speaker = report.customer_speaker
        analysis.languages = report.languages
        analysis.mixed_language = report.mixed_language
        analysis.confidence = Decimal(str(report.confidence))
        analysis.needs_review = report.needs_review or report.confidence < 0.65
        analysis.criteria_scores = [
            {**item.model_dump(), "weight": configured[item.name.casefold()]["weight"]}
            for item in report.criteria_scores
        ]
        analysis.strengths = report.strengths
        analysis.loss_reasons = report.loss_reasons
        analysis.recommendations = report.recommendations
        analysis.flags = report.flags
        analysis.evidence = [item.model_dump() for item in report.evidence]
        analysis.model_version = f"{self.settings.call_transcription_model}+{self.settings.call_analysis_model}"
        analysis.status = "needs_review" if analysis.needs_review else "ready"
        analysis.completed_at = datetime.now(UTC)
        analysis.error_code = None
        analysis.error_message = None

    async def _fail(
        self,
        analysis: CallQualityAnalysis | None,
        call: Call | None,
        code: str,
        message: str,
        retryable: bool,
    ) -> bool:
        if analysis is None:
            return False
        should_retry = retryable and analysis.attempt_count < self.settings.call_analysis_max_attempts
        analysis.status = "retrying" if should_retry else "failed"
        analysis.error_code = code
        analysis.error_message = message[:500]
        if not should_retry:
            analysis.completed_at = datetime.now(UTC)
            if call and call.recording_url and call.recording_url.startswith("minio://"):
                try:
                    await self.loader.delete_if_temporary(call.recording_url)
                    call.recording_url = None
                except Exception:
                    pass
        await self._commit_for_tenant(analysis.tenant_id)
        return should_retry
