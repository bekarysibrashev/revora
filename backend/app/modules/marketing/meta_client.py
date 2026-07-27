"""Read-only Meta Marketing API client."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json

import httpx


class MetaAdsError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetaAccountData:
    external_account_id: str
    name: str
    account_status: int
    currency: str
    timezone_name: str


@dataclass(frozen=True)
class MetaCampaignDay:
    campaign_external_id: str
    campaign_name: str
    metric_date: date
    spend: Decimal
    impressions: int
    reach: int
    clicks: int
    unique_clicks: int
    link_clicks: int
    outbound_clicks: int
    landing_page_views: int
    leads: int
    purchases: int
    conversations_started: int
    messaging_connections: int
    video_plays: int
    video_thruplays: int
    actions: list[dict[str, str]]
    action_values: list[dict[str, str]]
    outbound_clicks_raw: list[dict[str, str]]


class MetaAdsClient:
    FIELDS = ",".join(
        (
            "campaign_id",
            "campaign_name",
            "spend",
            "impressions",
            "reach",
            "clicks",
            "unique_clicks",
            "inline_link_clicks",
            "outbound_clicks",
            "actions",
            "action_values",
            "video_play_actions",
            "video_thruplay_watched_actions",
            "date_start",
            "date_stop",
        )
    )

    def __init__(
        self,
        access_token: str,
        graph_api_version: str,
        *,
        timeout_seconds: float = 30,
    ) -> None:
        self.access_token = access_token
        self.base_url = f"https://graph.facebook.com/{graph_api_version}"
        self.timeout_seconds = timeout_seconds

    async def account(self, account_id: str) -> MetaAccountData:
        payload = await self._get(
            f"/{account_id}",
            {"fields": "id,name,account_status,currency,timezone_name"},
        )
        return MetaAccountData(
            external_account_id=str(payload["id"]),
            name=str(payload["name"]),
            account_status=int(payload["account_status"]),
            currency=str(payload["currency"]),
            timezone_name=str(payload["timezone_name"]),
        )

    async def campaign_days(
        self, account_id: str, date_from: date, date_to: date
    ) -> list[MetaCampaignDay]:
        params: dict[str, object] = {
            "fields": self.FIELDS,
            "level": "campaign",
            "time_increment": 1,
            "time_range": json.dumps(
                {"since": date_from.isoformat(), "until": date_to.isoformat()}
            ),
            "limit": 500,
        }
        result: list[MetaCampaignDay] = []
        pages = 0
        while True:
            payload = await self._get(f"/{account_id}/insights", params)
            result.extend(self._parse_day(row) for row in payload.get("data", []))
            pages += 1
            if pages >= 100:
                raise MetaAdsError("Meta pagination exceeded the safety limit")
            cursor = payload.get("paging", {}).get("cursors", {}).get("after")
            if not cursor or not payload.get("paging", {}).get("next"):
                break
            params["after"] = cursor
        return result

    async def _get(self, path: str, params: dict[str, object]) -> dict:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.get(path, params=params)
        except httpx.RequestError as exc:
            raise MetaAdsError("Meta API is temporarily unavailable") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaAdsError("Meta API returned an invalid response") from exc
        if response.is_error or "error" in payload:
            error = payload.get("error", {})
            code = error.get("code", response.status_code)
            message = error.get("message", "Meta API request failed")
            raise MetaAdsError(f"Meta API error {code}: {message}")
        return payload

    @classmethod
    def _parse_day(cls, row: dict) -> MetaCampaignDay:
        actions = cls._action_list(row.get("actions"))
        action_values = cls._action_list(row.get("action_values"))
        outbound_raw = cls._action_list(row.get("outbound_clicks"))
        by_type = {
            item["action_type"]: cls._integer(item["value"]) for item in actions
        }
        return MetaCampaignDay(
            campaign_external_id=str(row["campaign_id"]),
            campaign_name=str(row.get("campaign_name") or "Без названия"),
            metric_date=date.fromisoformat(str(row["date_start"])),
            spend=cls._decimal(row.get("spend")),
            impressions=cls._integer(row.get("impressions")),
            reach=cls._integer(row.get("reach")),
            clicks=cls._integer(row.get("clicks")),
            unique_clicks=cls._integer(row.get("unique_clicks")),
            link_clicks=cls._integer(row.get("inline_link_clicks"))
            or by_type.get("link_click", 0),
            outbound_clicks=cls._sum_actions(outbound_raw),
            landing_page_views=by_type.get("landing_page_view", 0),
            leads=cls._first_action(
                by_type,
                "lead",
                "onsite_conversion.lead_grouped",
                "offsite_conversion.fb_pixel_lead",
            ),
            purchases=cls._first_action(
                by_type,
                "purchase",
                "omni_purchase",
                "offsite_conversion.fb_pixel_purchase",
            ),
            conversations_started=by_type.get(
                "onsite_conversion.messaging_conversation_started_7d", 0
            ),
            messaging_connections=by_type.get(
                "onsite_conversion.total_messaging_connection", 0
            ),
            video_plays=cls._sum_actions(
                cls._action_list(row.get("video_play_actions"))
            ),
            video_thruplays=cls._sum_actions(
                cls._action_list(row.get("video_thruplay_watched_actions"))
            ),
            actions=actions,
            action_values=action_values,
            outbound_clicks_raw=outbound_raw,
        )

    @staticmethod
    def _action_list(value: object) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        return [
            {
                "action_type": str(item.get("action_type", "")),
                "value": str(item.get("value", "0")),
            }
            for item in value
            if isinstance(item, dict) and item.get("action_type")
        ]

    @classmethod
    def _sum_actions(cls, values: list[dict[str, str]]) -> int:
        return sum(cls._integer(item.get("value")) for item in values)

    @staticmethod
    def _first_action(values: dict[str, int], *keys: str) -> int:
        return next((values[key] for key in keys if key in values), 0)

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return int(Decimal(str(value or 0)))
        except (InvalidOperation, ValueError):
            return 0

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            return Decimal(str(value or 0)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return Decimal("0")
