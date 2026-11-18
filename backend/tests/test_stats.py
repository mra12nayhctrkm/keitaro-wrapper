from datetime import UTC, date, datetime

from httpx import AsyncClient

from app.services.stats import Metrics, campaign_stats, period_days
from tests.fake_keitaro import FakeKeitaro

NOW = datetime(2026, 11, 18, 21, 30, tzinfo=UTC)  # 2026-11-19 00:30 in Moscow


def test_period_days_use_the_stats_timezone() -> None:
    assert period_days("today", "Europe/Moscow", NOW) == [date(2026, 11, 19)]
    assert period_days("today", "UTC", NOW) == [date(2026, 11, 18)]
    days = period_days("7d", "UTC", NOW)
    assert (days[0], days[-1], len(days)) == (date(2026, 11, 12), date(2026, 11, 18), 7)
    assert len(period_days("30d", "UTC", NOW)) == 30


def test_metrics_rates() -> None:
    m = Metrics(clicks=200, conversions=5, revenue=50.0)
    assert (m.cr, m.epc) == (2.5, 0.25)
    assert (Metrics().cr, Metrics().epc) == (0.0, 0.0)


async def test_aggregates_rows_per_stream_offer_and_day(keitaro: FakeKeitaro) -> None:
    keitaro.report_rows = [
        {
            "stream_id": 2,
            "offer_id": 11,
            "day": "2026-11-17",
            "clicks": 10,
            "conversions": 1,
            "revenue": 5,
        },
        {
            "stream_id": 2,
            "offer_id": 11,
            "day": "2026-11-18",
            "clicks": 30,
            "conversions": 2,
            "revenue": "7.5",
        },
        {
            "stream_id": 2,
            "offer_id": 12,
            "day": "2026-11-18",
            "clicks": 5,
            "conversions": 0,
            "revenue": 0,
        },
        {"stream_id": 1, "offer_id": 0, "day": "2026-11-18", "clicks": 8},  # geo redirect
        {"stream_id": 2, "offer_id": 13, "day": "bad", "clicks": 1},
    ]
    stats = await campaign_stats(keitaro, 5, "7d", "UTC", NOW)

    request = keitaro.report_requests[0]
    assert request["range"] == {"from": "2026-11-12", "to": "2026-11-18", "timezone": "UTC"}
    assert request["dimensions"] == ["stream_id", "offer_id", "day"]
    assert request["filters"] == [{"name": "campaign_id", "operator": "EQUALS", "expression": 5}]

    geo, offers = stats.streams[1], stats.streams[2]
    assert (geo.total.clicks, geo.offers) == (8, {})
    assert offers.total.clicks == 46
    o11 = offers.offers[11]
    assert (o11.total.clicks, o11.total.conversions, o11.total.revenue) == (40, 3, 12.5)
    assert o11.daily[date(2026, 11, 18)].clicks == 30
    assert offers.offers[13].daily == {}  # unparseable day is counted in totals only


async def test_stats_endpoint(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    today = period_days("today", "Europe/Moscow")[0].isoformat()
    keitaro.report_rows = [
        {
            "stream_id": 2,
            "offer_id": 11,
            "day": today,
            "clicks": 40,
            "conversions": 2,
            "revenue": 10,
        },
    ]
    response = await client.get("/api/campaigns/5/stats", params={"period": "7d"})
    assert response.status_code == 200
    data = response.json()
    assert data["period"] == "7d"
    assert len(data["days"]) == 7
    assert data["days"][-1] == today
    (stream,) = data["streams"]
    assert (stream["stream_id"], stream["clicks"], stream["cr"]) == (2, 40, 5.0)
    (offer,) = stream["offers"]
    assert offer["daily_clicks"] == [0, 0, 0, 0, 0, 0, 40]
    assert offer["epc"] == 0.25

    assert (
        await client.get("/api/campaigns/5/stats", params={"period": "year"})
    ).status_code == 422
