from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, status
from app.modules.ai.analyst.dependencies import get_analyst_service
from app.modules.ai.analyst.schemas import ArchiveResponse, ChatMessageCreate, ChatMessageList, ChatSessionCreate, ChatSessionList, ChatSessionResponse, ChatTurnResponse
from app.modules.ai.analyst.service import AnalystService
from app.modules.auth.dependencies import CurrentUser

router=APIRouter(prefix="/ai/analyst",tags=["ai-analyst"])
Service=Annotated[AnalystService,Depends(get_analyst_service)]

@router.post("/sessions",response_model=ChatSessionResponse,status_code=status.HTTP_201_CREATED)
async def create_session(payload:ChatSessionCreate,user:CurrentUser,service:Service): return await service.create_session(user,payload.title,payload.branch_id)
@router.get("/sessions",response_model=ChatSessionList)
async def list_sessions(user:CurrentUser,service:Service):
    items=await service.list_sessions(user);return ChatSessionList(items=items,total=len(items))
@router.get("/sessions/{session_id}/messages",response_model=ChatMessageList)
async def list_messages(session_id:UUID,user:CurrentUser,service:Service):
    items=await service.list_messages(user,session_id);return ChatMessageList(items=items,total=len(items))
@router.post("/sessions/{session_id}/messages",response_model=ChatTurnResponse)
async def send_message(session_id:UUID,payload:ChatMessageCreate,user:CurrentUser,service:Service):
    return await service.send(user,session_id,payload.content,payload.date_from,payload.date_to)
@router.post("/sessions/{session_id}/archive",response_model=ArchiveResponse)
async def archive_session(session_id:UUID,user:CurrentUser,service:Service):
    await service.archive(user,session_id);return ArchiveResponse()
