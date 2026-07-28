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
from app.modules.ai.call_quality.defaults import ensure_default_rule_set
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


def _mask_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


@router.post("")
@router.post("/history")
async def receive_kcell_callback(
    request: Request,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Persist Kcell history callbacks idempotently and create an analysis job record."""
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    values = {key: items[-1] for key, items in parse_qs(raw_body, keep_blank_values=True).items()}
    if not values and request.headers.get("content-type", "").startswith("application/json"):
        values = await request.json()
    expected_token = settings.kcell_crm_token.get_secret_value()
    if not expected_token or not hmac.compare_digest(str(values.get("crm_token", "")), expected_token):
        raise AppError("INVALID_KCELL_TOKEN", "Invalid Kcell token", 401)
    command = str(values.get("cmd", ""))
    # The Kcell CRM address is shared by all enabled scenarios. These two
    # scenarios are enabled by default in the Kcell panel, so acknowledge them
    # even though Revora does not yet use the live pop-up card functionality.
    if command == "event":
        return {"status": "ok"}
    if command == "contact":
        return {"contact_name": "", "responsible": ""}
    if command != "history":
        raise AppError("INVALID_KCELL_COMMAND", "Unsupported Kcell command", 400)
    required = ("type", "user", "phone", "start", "duration", "callid", "status")
    if any(not values.get(field) for field in required):
        raise AppError("INVALID_KCELL_PAYLOAD", "Kcell request has required fields missing", 400)
    tenant = await session.scalar(
        select(Tenant).where(
            Tenant.slug == settings.kcell_tenant_slug, Tenant.is_active.is_(True)
        )
    )
    # The first Render deployment may have created a tenant with a custom slug.
    # A single-clinic deployment is unambiguous, so accept its only active tenant.
    if tenant is None:
        active_tenants = list(
            (await session.scalars(select(Tenant).where(Tenant.is_active.is_(True)))).all()
        )
        if len(active_tenants) == 1:
            tenant = active_tenants[0]
    if tenant is None:
        raise AppError("KCELL_TENANT_NOT_FOUND", "Kcell tenant is not configured", 503)
    await session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant.id)})
    call = await session.scalar(select(Call).where(Call.tenant_id == tenant.id, Call.external_id == str(values["callid"])))
    if call is None:
        call = Call(tenant_id=tenant.id, external_id=str(values["callid"]), phone_hash=phone_hash(str(values["phone"])), phone_masked=_mask_phone(str(values["phone"])), direction=str(values["type"]), started_at=_parse_start(str(values["start"])), duration_seconds=int(values["duration"]), outcome=str(values["status"]), external_user=str(values["user"]), recording_url=str(values.get("link") or "") or None)
        session.add(call)
        await session.flush()
        rules = await ensure_default_rule_set(session, tenant.id)
        if rules is not None:
            duration = int(values["duration"])
            recording_url = str(values.get("link") or "") or None
            analysis_status = (
                "skipped_short"
                if duration <= settings.call_min_duration_seconds
                else "queued" if recording_url else "waiting_for_recording"
            )
            session.add(CallQualityAnalysis(
                tenant_id=tenant.id,
                call_id=call.id,
                rule_set_id=rules.id,
                status=analysis_status,
                queued_at=datetime.now(UTC) if analysis_status == "queued" else None,
                completed_at=datetime.now(UTC) if analysis_status == "skipped_short" else None,
            ))
    else:
        call.duration_seconds = int(values["duration"])
        call.outcome = str(values["status"])
        call.phone_masked = _mask_phone(str(values["phone"]))
        call.recording_url = str(values.get("link") or "") or call.recording_url
        analysis = await session.scalar(
            select(CallQualityAnalysis).where(
                CallQualityAnalysis.tenant_id == tenant.id,
                CallQualityAnalysis.call_id == call.id,
            )
        )
        if analysis is None:
            rules = await ensure_default_rule_set(session, tenant.id)
            if rules is not None:
                analysis = CallQualityAnalysis(
                    tenant_id=tenant.id,
                    call_id=call.id,
                    rule_set_id=rules.id,
                    status="pending",
                )
                session.add(analysis)
        if analysis is not None and analysis.status in {"pending", "waiting_for_recording", "skipped_short"}:
            if call.duration_seconds <= settings.call_min_duration_seconds:
                analysis.status = "skipped_short"
                analysis.completed_at = datetime.now(UTC)
            elif call.recording_url:
                analysis.status = "queued"
                analysis.queued_at = datetime.now(UTC)
                analysis.completed_at = None
            else:
                analysis.status = "waiting_for_recording"
    payload = {key: value for key, value in values.items() if key != "crm_token"}
    receipt = await session.scalar(select(KcellWebhookReceipt).where(KcellWebhookReceipt.tenant_id == tenant.id, KcellWebhookReceipt.call_id == str(values["callid"]), KcellWebhookReceipt.command == "history"))
    if receipt is None:
        session.add(KcellWebhookReceipt(tenant_id=tenant.id, call_id=str(values["callid"]), command="history", payload=payload))
    return {"status": "ok"}
