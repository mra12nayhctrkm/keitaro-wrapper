"""Per-offer statistics and daily trends from Keitaro reports."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.keitaro.client import KeitaroApi

Period = Literal["today", "7d", "30d"]
PERIOD_DAYS: dict[Period, int] = {"today": 1, "7d": 7, "30d": 30}


@dataclass(slots=True)
class Metrics:
    clicks: int = 0
    conversions: int = 0
    revenue: float = 0.0

    def add(self, row: dict[str, Any]) -> None:
        self.clicks += int(row.get("clicks") or 0)
        self.conversions += int(row.get("conversions") or 0)
        self.revenue += float(row.get("revenue") or 0)

    @property
    def cr(self) -> float:
        """Conversion rate, %."""
        return round(self.conversions / self.clicks * 100, 2) if self.clicks else 0.0

    @property
    def epc(self) -> float:
        """Earnings per click."""
        return round(self.revenue / self.clicks, 4) if self.clicks else 0.0


@dataclass(slots=True)
class OfferStats:
    offer_id: int
    total: Metrics = field(default_factory=Metrics)
    daily: dict[date, Metrics] = field(default_factory=lambda: defaultdict(Metrics))


@dataclass(slots=True)
class StreamStats:
    stream_id: int
    total: Metrics = field(default_factory=Metrics)
    offers: dict[int, OfferStats] = field(default_factory=dict)


@dataclass(slots=True)
class CampaignStats:
    period: Period
    days: list[date]
    streams: dict[int, StreamStats]


def period_days(period: Period, timezone: str, now: datetime | None = None) -> list[date]:
    today = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone)).date()
    n = PERIOD_DAYS[period]
    return [today - timedelta(days=n - 1 - i) for i in range(n)]


async def campaign_stats(
    keitaro: KeitaroApi,
    campaign_id: int,
    period: Period,
    timezone: str,
    now: datetime | None = None,
) -> CampaignStats:
    days = period_days(period, timezone, now)
    rows = await keitaro.build_report(
        {
            "range": {
                "from": days[0].isoformat(),
                "to": days[-1].isoformat(),
                "timezone": timezone,
            },
            "dimensions": ["stream_id", "offer_id", "day"],
            "measures": ["clicks", "conversions", "revenue"],
            "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id}],
        }
    )

    streams: dict[int, StreamStats] = {}
    for row in rows:
        stream_id = int(row.get("stream_id") or 0)
        offer_id = int(row.get("offer_id") or 0)
        stream = streams.setdefault(stream_id, StreamStats(stream_id))
        stream.total.add(row)
        if offer_id:  # 0 = the click did not reach an offer (e.g. a redirect stream)
            offer = stream.offers.setdefault(offer_id, OfferStats(offer_id))
            offer.total.add(row)
            day = _parse_day(row.get("day"))
            if day is not None:
                offer.daily[day].add(row)
    return CampaignStats(period=period, days=days, streams=streams)


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
