from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.ai.call_quality.schemas import CallListResponse, CallQualityStatusResponse, RuleSetRequest, RuleSetResponse
from app.modules.ai.call_quality.service import CallQualityService
from app.modules.auth.dependencies import CurrentUser

router = APIRouter(prefix="/call-quality", tags=["call-quality"])
Session = Annotated[AsyncSession, Depends(get_db_session)]

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
