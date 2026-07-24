"""Receiver for Kcell's form-encoded REST API callbacks."""
from datetime import UTC, datetime
import hmac
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.errors import AppError
from app.core.security import phone_hash
from app.modules.ai.call_quality.models import CallQualityAnalysis, CallQualityRuleSet
from app.modules.kcell.models import KcellWebhookReceipt
from app.modules.sales.models import Call
from app.modules.tenancy.models import Tenant

router = APIRouter(prefix="/webhooks/kcell", tags=["kcell"])
Session = Annotated[AsyncSession, Depends(get_db_session)]


def _parse_start(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise AppError("INVALID_KCELL_PAYLOAD", "Invalid Kcell call start time", 400) from exc


@router.post("/history")
async def receive_history(
    request: Request,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Persist Kcell history callbacks idempotently and create an analysis job record."""
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    values = {key: items[-1] for key, items in parse_qs(raw_body, keep_blank_values=True).items()}
    if not values and request.headers.get("content-type", "").startswith("application/json"):
        values = await request.json()
    if values.get("cmd") != "history":
        raise AppError("INVALID_KCELL_COMMAND", "Expected Kcell history command", 400)
    expected_token = settings.kcell_crm_token.get_secret_value()
    if not expected_token or not hmac.compare_digest(str(values.get("crm_token", "")), expected_token):
        raise AppError("INVALID_KCELL_TOKEN", "Invalid Kcell token", 401)
    required = ("type", "user", "phone", "start", "duration", "callid", "status")
    if any(not values.get(field) for field in required):
        raise AppError("INVALID_KCELL_PAYLOAD", "Kcell request has required fields missing", 400)
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == settings.kcell_tenant_slug, Tenant.is_active.is_(True)))
    if tenant is None:
        raise AppError("KCELL_TENANT_NOT_FOUND", "Kcell tenant is not configured", 503)
    await session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant.id)})
    call = await session.scalar(select(Call).where(Call.tenant_id == tenant.id, Call.external_id == str(values["callid"])))
    if call is None:
        call = Call(tenant_id=tenant.id, external_id=str(values["callid"]), phone_hash=phone_hash(str(values["phone"])), direction=str(values["type"]), started_at=_parse_start(str(values["start"])), duration_seconds=int(values["duration"]), outcome=str(values["status"]), external_user=str(values["user"]), recording_url=str(values.get("link") or "") or None)
        session.add(call)
        await session.flush()
        rules = await session.scalar(select(CallQualityRuleSet).where(CallQualityRuleSet.tenant_id == tenant.id, CallQualityRuleSet.is_active.is_(True)).order_by(CallQualityRuleSet.version.desc()))
        if rules is not None:
            session.add(CallQualityAnalysis(tenant_id=tenant.id, call_id=call.id, rule_set_id=rules.id, status="pending"))
    else:
        call.duration_seconds = int(values["duration"])
        call.outcome = str(values["status"])
        call.recording_url = str(values.get("link") or "") or call.recording_url
    payload = {key: value for key, value in values.items() if key != "crm_token"}
    receipt = await session.scalar(select(KcellWebhookReceipt).where(KcellWebhookReceipt.tenant_id == tenant.id, KcellWebhookReceipt.call_id == str(values["callid"]), KcellWebhookReceipt.command == "history"))
    if receipt is None:
        session.add(KcellWebhookReceipt(tenant_id=tenant.id, call_id=str(values["callid"]), command="history", payload=payload))
    return {"status": "ok"}
