from dataclasses import replace
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
    def __init__(self):
        self.last_date_from = None
        self.last_date_to = None

    async def account(self, account_id):
        return MetaAccountData(account_id, "San Dental", 1, "USD", "Asia/Almaty")

    async def campaign_days(self, account_id, date_from, date_to):
        self.last_date_from = date_from
        self.last_date_to = date_to
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
    client = FakeMetaClient()
    response = await MarketingService(
        repository,
        meta_client=client,
        meta_account_ids=["act_1", "act_2"],
    ).sync_meta(make_user(), date(2026, 7, 1), date(2026, 7, 27))

    assert response.accounts_synced == 2
    assert response.rows_written == 2
    assert len(repository.rows) == 2
    assert client.last_date_from == date(2026, 6, 4)
    assert client.last_date_to == date(2026, 7, 27)


@pytest.mark.asyncio
async def test_meta_overview_calculates_business_metrics() -> None:
    response = await MarketingService(FakeMetaRepository()).meta_overview(
        make_user(), date(2026, 7, 1), date(2026, 7, 27)
    )

    assert response.total_spend == Decimal("100")
    assert response.ctr == Decimal("0.05")
    assert response.cpc == Decimal("1")
    assert response.cpm == Decimal("50")
    assert response.cost_per_lead == Decimal("10")
    assert response.cost_per_conversation == Decimal("5")
    assert response.click_to_conversation_rate == Decimal("0.25")
    assert response.landing_page_view_rate == Decimal(
        "0.8571428571428571428571428571"
    )
    assert response.video_thruplay_rate == Decimal("0.2")
    assert response.comparison.spend_change == Decimal("0")
    assert response.recommendations[0].campaign_name == "Имплантация"
    assert response.recommendations[0].result_metric == "WhatsApp-диалоги"
    assert response.recommendations[0].cost_per_result == Decimal("5")


@pytest.mark.asyncio
async def test_meta_overview_flags_spend_without_results_and_compares_periods() -> None:
    class AlertRepository(FakeMetaRepository):
        async def meta_campaign_totals(
            self, tenant_id, date_from, date_to, account_external_id=None
        ):
            rows = await super().meta_campaign_totals(
                tenant_id, date_from, date_to, account_external_id
            )
            if date_to < date(2026, 7, 1):
                return [
                    replace(
                        rows[0],
                        spend=Decimal("50"),
                        conversations_started=10,
                        leads=5,
                    )
                ]
            return [
                replace(
                    rows[0],
                    spend=Decimal("100"),
                    conversations_started=0,
                    leads=0,
                )
            ]

    response = await MarketingService(AlertRepository()).meta_overview(
        make_user(), date(2026, 7, 1), date(2026, 7, 27)
    )

    assert response.comparison.spend_change == Decimal("1")
    assert response.comparison.conversations_change == Decimal("-1")
    assert response.alerts[0].code == "SPEND_WITHOUT_RESULTS"


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


@pytest.mark.asyncio
async def test_budget_recommendations_rank_and_reallocate() -> None:
    class RankedRepository(FakeMetaRepository):
        async def meta_campaign_totals(
            self, tenant_id, date_from, date_to, account_external_id=None
        ):
            base = (await super().meta_campaign_totals(
                tenant_id, date_from, date_to, account_external_id
            ))[0]
            if date_to < date(2026, 7, 1):
                return []
            return [
                replace(
                    base,
                    campaign_external_id="best",
                    campaign_name="Лучшая",
                    spend=Decimal("60"),
                    conversations_started=12,
                ),
                replace(
                    base,
                    campaign_external_id="weak",
                    campaign_name="Слабая",
                    spend=Decimal("120"),
                    conversations_started=2,
                ),
                replace(
                    base,
                    campaign_external_id="empty",
                    campaign_name="Без результата",
                    spend=Decimal("50"),
                    conversations_started=0,
                    leads=0,
                ),
            ]

    response = await MarketingService(RankedRepository()).meta_overview(
        make_user(), date(2026, 7, 1), date(2026, 7, 27)
    )

    by_name = {item.campaign_name: item for item in response.recommendations}
    assert response.recommendations[0].campaign_name == "Лучшая"
    assert by_name["Лучшая"].action == "increase"
    assert by_name["Слабая"].action == "reduce"
    assert by_name["Без результата"].action == "pause"


@pytest.mark.asyncio
async def test_stopped_meta_campaign_is_excluded_from_budget_advice() -> None:
    class StoppedRepository(FakeMetaRepository):
        async def meta_campaign_totals(
            self, tenant_id, date_from, date_to, account_external_id=None
        ):
            rows = await super().meta_campaign_totals(
                tenant_id, date_from, date_to, account_external_id
            )
            if date_to < date(2026, 7, 1):
                return []
            return [replace(rows[0], effective_status="PAUSED")]

    response = await MarketingService(StoppedRepository()).meta_overview(
        make_user(), date(2026, 7, 1), date(2026, 7, 27)
    )

    assert response.campaigns[0].effective_status == "PAUSED"
    assert response.recommendations == []
    assert response.alerts == []
