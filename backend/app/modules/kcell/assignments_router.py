"""HTTP endpoints for administering Kcell extension assignments.

Separate from kcell/router.py on purpose: that one is the unauthenticated
webhook Kcell itself calls, this one is an authenticated admin surface.
They must not share a prefix or a dependency chain.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.dependencies import CurrentUser
from app.modules.kcell.repository import KcellAssignmentsRepository
from app.modules.kcell.schemas import (
    KcellAssignmentAuditResponse,
    KcellAssignmentItem,
    KcellAssignmentListResponse,
    KcellAssignmentSetRequest,
    KcellBackfillPreview,
    KcellBackfillResult,
)
from app.modules.kcell.service import KcellAssignmentsService

router = APIRouter(prefix="/kcell/assignments", tags=["kcell-assignments"])

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_assignments_service(session: SessionDependency) -> KcellAssignmentsService:
    return KcellAssignmentsService(KcellAssignmentsRepository(session))


ServiceDependency = Annotated[
    KcellAssignmentsService, Depends(get_assignments_service)
]

# An extension is an opaque string from Kcell and may contain characters
# that are awkward in a path segment, so writes take it in the path but
# always url-encoded by the client; FastAPI decodes it before we see it.
ExtensionPath = Annotated[str, Path(min_length=1, max_length=150)]


@router.get("", response_model=KcellAssignmentListResponse)
async def list_assignments(
    user: CurrentUser, service: ServiceDependency
) -> KcellAssignmentListResponse:
    return await service.list_assignments(user)


@router.put("/{external_user}", response_model=KcellAssignmentItem)
async def set_assignment(
    external_user: ExtensionPath,
    payload: KcellAssignmentSetRequest,
    user: CurrentUser,
    service: ServiceDependency,
) -> KcellAssignmentItem:
    return await service.set_assignment(user, external_user, payload.assigned_user_id)


@router.post("/{external_user}/ambiguous", response_model=KcellAssignmentItem)
async def mark_ambiguous(
    external_user: ExtensionPath,
    user: CurrentUser,
    service: ServiceDependency,
) -> KcellAssignmentItem:
    return await service.mark_ambiguous(user, external_user)


@router.delete("/{external_user}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment(
    external_user: ExtensionPath,
    user: CurrentUser,
    service: ServiceDependency,
) -> None:
    await service.delete_assignment(user, external_user)


@router.get("/backfill/preview", response_model=KcellBackfillPreview)
async def preview_backfill(
    user: CurrentUser, service: ServiceDependency
) -> KcellBackfillPreview:
    return await service.preview_backfill(user)


@router.post("/backfill", response_model=KcellBackfillResult)
async def run_backfill(
    user: CurrentUser, service: ServiceDependency
) -> KcellBackfillResult:
    return await service.run_backfill(user)


@router.get("/audit", response_model=KcellAssignmentAuditResponse)
async def audit_trail(
    user: CurrentUser,
    service: ServiceDependency,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> KcellAssignmentAuditResponse:
    return await service.audit_trail(user, limit)
