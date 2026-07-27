from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.modules.marketing.meta_client import MetaAdsClient
from app.modules.marketing.repository import MarketingRepository
from app.modules.marketing.service import MarketingService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_marketing_service(
    session: SessionDependency,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MarketingService:
    token = settings.meta_access_token.get_secret_value()
    client = (
        MetaAdsClient(token, settings.meta_graph_api_version)
        if token and settings.meta_ad_account_ids
        else None
    )
    return MarketingService(
        MarketingRepository(session),
        meta_client=client,
        meta_account_ids=settings.meta_ad_account_ids,
    )
