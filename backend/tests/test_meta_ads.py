from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.marketing.meta_client import (
    MetaAccountData,
    MetaAdsClient,
    MetaCampaignDay,
)
from app.modules.marketing.repository import MetaCampaignTotals
from app.modules.marketing.service import MarketingService


def make_user(role: UserRole = UserRole.OWNER) -> User:
    user = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="meta@example.test",
        full_name="Meta Owner",
        password_hash="unused",
        role=role,
        is_active=True,
    )
    user.branch_links = []
    return user


class FakeMetaClient:
    async def account(self, account_id):
        return MetaAccountData(account_id, "San Dental", 1, "USD", "Asia/Almaty")

    async def campaign_days(self, account_id, date_from, date_to):
        return [
            MetaCampaignDay(
                campaign_external_id="campaign-1",
                campaign_name="Имплантация",
                metric_date=date_from,
                spend=Decimal("25.50"),
                impressions=1000,
                reach=700,
                clicks=50,
                unique_clicks=45,
                link_clicks=40,
                outbound_clicks=35,
                landing_page_views=30,
                leads=4,
                purchases=0,
                conversations_started=5,
                messaging_connections=6,
                video_plays=100,
                video_thruplays=20,
                actions=[],
                action_values=[],
                outbound_clicks_raw=[],
            )
        ]


class FakeMetaRepository:
    def __init__(self):
        self.rows = []

    async def upsert_meta_account(self, tenant_id, data, synced_at):
        return SimpleNamespace(id=uuid4())

    async def upsert_meta_campaign_days(self, tenant_id, account_id, rows):
        self.rows.extend(rows)
        return len(rows)

    async def meta_campaign_totals(
        self, tenant_id, date_from, date_to, account_external_id=None
    ):
        return [
            MetaCampaignTotals(
                account_external_id="act_1",
                account_name="San Dental",
                currency="USD",
                campaign_external_id="campaign-1",
                campaign_name="Имплантация",
                spend=Decimal("100"),
                impressions=2000,
                clicks=100,
                unique_clicks=90,
                link_clicks=80,
                outbound_clicks=70,
                landing_page_views=60,
                leads=10,
                purchases=1,
                conversations_started=20,
                messaging_connections=22,
                video_plays=500,
                video_thruplays=100,
            )
        ]

    async def list_meta_accounts(self, tenant_id):
        return [
            SimpleNamespace(
                external_account_id="act_1",
                name="San Dental",
                account_status=1,
                currency="USD",
                timezone_name="Asia/Almaty",
                last_synced_at=datetime(2026, 7, 27, tzinfo=UTC),
                last_error=None,
            )
        ]


def test_meta_client_extracts_conversations_from_actions() -> None:
    row = MetaAdsClient._parse_day(
        {
            "campaign_id": "campaign-1",
            "campaign_name": "Имплантация",
            "date_start": "2026-07-20",
            "spend": "10.129",
            "impressions": "1000",
            "reach": "700",
            "clicks": "40",
            "actions": [
                {"action_type": "link_click", "value": "31"},
                {
                    "action_type": "onsite_conversion.messaging_conversation_started_7d",
                    "value": "7",
                },
                {
                    "action_type": "onsite_conversion.total_messaging_connection",
                    "value": "8",
                },
            ],
        }
    )

    assert row.spend == Decimal("10.13")
    assert row.link_clicks == 31
    assert row.unique_clicks == 0
    assert row.conversations_started == 7
    assert row.messaging_connections == 8


@pytest.mark.asyncio
async def test_meta_sync_is_idempotent_repository_input() -> None:
    repository = FakeMetaRepository()
    response = await MarketingService(
        repository,
        meta_client=FakeMetaClient(),
        meta_account_ids=["act_1", "act_2"],
    ).sync_meta(make_user(), date(2026, 7, 1), date(2026, 7, 27))

    assert response.accounts_synced == 2
    assert response.rows_written == 2
    assert len(repository.rows) == 2


@pytest.mark.asyncio
async def test_meta_overview_calculates_business_metrics() -> None:
    response = await MarketingService(FakeMetaRepository()).meta_overview(
        make_user(), date(2026, 7, 1), date(2026, 7, 27)
    )

    assert response.total_spend == Decimal("100")
    assert response.ctr == Decimal("0.05")
    assert response.cpc == Decimal("1")
    assert response.cost_per_conversation == Decimal("5")


@pytest.mark.asyncio
async def test_only_owner_can_trigger_meta_sync() -> None:
    with pytest.raises(AppError) as error:
        await MarketingService(
            FakeMetaRepository(),
            meta_client=FakeMetaClient(),
            meta_account_ids=["act_1"],
        ).sync_meta(
            make_user(UserRole.MANAGER), date(2026, 7, 1), date(2026, 7, 27)
        )

    assert error.value.code == "FORBIDDEN"
