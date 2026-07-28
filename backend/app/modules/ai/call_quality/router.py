from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.errors import AppError
from app.modules.ai.call_quality.audio import ALLOWED_AUDIO_TYPES
from app.modules.ai.call_quality.defaults import ensure_default_rule_set
from app.modules.ai.call_quality.models import CallQualityAnalysis
from app.modules.ai.call_quality.pipeline import CallQualityPipeline
from app.modules.ai.call_quality.schemas import (
    CallAnalysisResponse, CallListResponse, CallQualityStatusResponse,
    ManualTestResponse, OperatorPerformanceResponse, RuleSetRequest, RuleSetResponse,
)
from app.modules.ai.call_quality.service import CallQualityService
from app.modules.auth.dependencies import CurrentUser
from app.modules.auth.models import UserRole
from app.modules.sales.models import Call

router = APIRouter(prefix="/call-quality", tags=["call-quality"])
Session = Annotated[AsyncSession, Depends(get_db_session)]
RuntimeSettings = Annotated[Settings, Depends(get_settings)]

@router.get("/status", response_model=CallQualityStatusResponse)
async def get_status(user: CurrentUser, session: Session) -> CallQualityStatusResponse:
    return await CallQualityService(session).status(user)

@router.get("/calls", response_model=CallListResponse)
async def list_calls(
    user: CurrentUser, session: Session, limit: int = 100
) -> CallListResponse:
    return await CallQualityService(session).list_calls(user, max(1, min(limit, 500)))

@router.post("/rule-sets", response_model=RuleSetResponse, status_code=status.HTTP_201_CREATED)
async def create_rule_set(payload: RuleSetRequest, user: CurrentUser, session: Session) -> RuleSetResponse:
    return await CallQualityService(session).create_rule_set(user, payload)


@router.get("/calls/{call_id}/analysis", response_model=CallAnalysisResponse)
async def get_analysis(
    call_id: UUID, user: CurrentUser, session: Session
) -> CallAnalysisResponse:
    return await CallQualityService(session).analysis(user, call_id)


@router.post("/calls/{call_id}/reanalyze", response_model=CallAnalysisResponse)
async def reanalyze(
    call_id: UUID, user: CurrentUser, session: Session
) -> CallAnalysisResponse:
    return await CallQualityService(session).reanalyze(user, call_id)


@router.get("/operators", response_model=OperatorPerformanceResponse)
async def operator_performance(
    user: CurrentUser,
    session: Session,
    date_from: date | None = None,
    date_to: date | None = None,
) -> OperatorPerformanceResponse:
    if date_from and date_to and date_from > date_to:
        raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
    return await CallQualityService(session).operator_performance(user, date_from, date_to)


@router.post(
    "/manual-tests",
    response_model=ManualTestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def manual_test(
    request: Request,
    user: CurrentUser,
    session: Session,
    settings: RuntimeSettings,
) -> ManualTestResponse:
    if user.role != UserRole.OWNER:
        raise AppError("FORBIDDEN", "Only the owner can test call analysis", 403)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in ALLOWED_AUDIO_TYPES:
        raise AppError("AUDIO_TYPE_UNSUPPORTED", "Upload MP3, M4A, WAV, OGG or WEBM audio", 415)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > settings.call_max_audio_bytes:
            raise AppError("AUDIO_TOO_LARGE", "Audio file exceeds the configured size limit", 413)
        chunks.append(chunk)
    if not size:
        raise AppError("AUDIO_EMPTY", "Audio file is empty", 422)
    filename = Path(request.headers.get("x-filename", "manual-test.mp3")).name[:200]
    employee = request.headers.get("x-operator-name", "Ручной тест").strip()[:150] or "Ручной тест"
    rules = await ensure_default_rule_set(session, user.tenant_id)
    if rules is None:
        raise AppError("CALL_RULE_SET_MISSING", "A call quality rule set could not be created", 409)
    external_id = f"manual:{uuid4()}"
    call = Call(
        tenant_id=user.tenant_id,
        external_id=external_id,
        phone_hash=sha256(external_id.encode()).hexdigest(),
        direction="manual",
        started_at=datetime.now(UTC),
        duration_seconds=None,
        outcome="manual_test",
        external_user=employee,
        phone_masked=None,
        recording_url=None,
    )
    session.add(call)
    await session.flush()
    analysis = CallQualityAnalysis(
        tenant_id=user.tenant_id,
        call_id=call.id,
        rule_set_id=rules.id,
        status="processing",
        queued_at=datetime.now(UTC),
    )
    session.add(analysis)
    await session.flush()
    await session.commit()
    final_status = await CallQualityPipeline(session, settings).run_inline_audio(
        user.tenant_id,
        analysis.id,
        b"".join(chunks),
        filename=filename,
        content_type=content_type,
    )
    return ManualTestResponse(
        call_id=call.id, analysis_id=analysis.id, status=final_status
    )
