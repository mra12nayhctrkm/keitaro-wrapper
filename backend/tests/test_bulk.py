from typing import Any

import pytest
from httpx import AsyncClient

from app.keitaro.client import KeitaroUnavailableError
from app.services.bulk import plan
from tests.fake_keitaro import FakeKeitaro

GROUP = 3


@pytest.fixture(autouse=True)
def campaigns(keitaro: FakeKeitaro) -> None:
    keitaro.add_campaign(1, "test_a", group_id=GROUP)
    keitaro.add_stream(1, stream_id=10, name="Offers", offers={11: 60, 12: 40})
    keitaro.add_stream(1, stream_id=11, name="Other", offers={12: 100})  # no offer 11
    keitaro.add_campaign(2, "test_b", group_id=GROUP)
    keitaro.add_stream(2, stream_id=20, name="Offers", offers={11: 50, 13: 50})
    keitaro.add_campaign(3, "other_group", group_id=99)
    keitaro.add_stream(3, stream_id=30, offers={11: 100})
    keitaro.add_campaign(4, "test_deleted", group_id=GROUP)
    keitaro.campaigns[4]["state"] = "deleted"
    keitaro.add_stream(4, stream_id=40, offers={11: 100})


def test_plan() -> None:
    assert plan({11: 60, 12: 40}, 11, 14) == {12: 40, 14: 60}
    assert plan({11: 60, 12: 40}, 11, 12) == {12: 100}  # target already there: merged


async def preview(client: AsyncClient, **extra: Any) -> Any:
    response = await client.post(
        "/api/bulk/replace-offer/preview",
        json={
            "group_id": GROUP,
            "from_offer_id": 11,
            "to_offer_id": 14,
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_preview_finds_streams_in_the_group_only(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    data = await preview(client)
    assert data["scanned_campaigns"] == 2
    changes = {c["stream_id"]: c for c in data["changes"]}
    assert set(changes) == {10, 20}
    assert changes[10]["after"] == [{"offer_id": 12, "share": 40}, {"offer_id": 14, "share": 60}]
    assert changes[20]["campaign_name"] == "test_b"
    assert "update_stream" not in keitaro.calls  # read-only

    assert [c["stream_id"] for c in (await preview(client, name_filter="B"))["changes"]] == [20]


async def test_preview_reports_per_campaign_errors(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    keitaro.fail["list_streams"] = KeitaroUnavailableError("timeout")
    data = await preview(client)
    assert len(data["errors"]) == 1
    assert len(data["changes"]) == 1  # the other campaign still came through


async def test_preview_rejects_same_offer(client: AsyncClient) -> None:
    response = await client.post(
        "/api/bulk/replace-offer/preview",
        json={"group_id": GROUP, "from_offer_id": 11, "to_offer_id": 11},
    )
    assert response.status_code == 422


async def test_apply_as_drafts_then_publish(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    targets = [{"campaign_id": 1, "stream_id": 10}, {"campaign_id": 2, "stream_id": 20}]
    response = await client.post(
        "/api/bulk/replace-offer/apply",
        json={
            "from_offer_id": 11,
            "to_offer_id": 14,
            "targets": targets,
        },
    )
    assert [o["status"] for o in response.json()] == ["drafted", "drafted"]
    assert keitaro.stream_offers(10) == {11: 60, 12: 40}  # drafts only

    stream = (await client.get("/api/campaigns/1")).json()["streams"][0]
    assert {o["offer_id"]: (o["share"], o["status"]) for o in stream["offers"]} == {
        11: (0, "pending_remove"),
        12: (40, "active"),
        14: (60, "pending_add"),
    }

    response = await client.post(
        "/api/bulk/replace-offer/apply",
        json={
            "from_offer_id": 11,
            "to_offer_id": 14,
            "targets": targets,
            "publish": True,
        },
    )
    assert [o["status"] for o in response.json()] == ["published", "published"]
    assert keitaro.stream_offers(10) == {12: 40, 14: 60}
    assert keitaro.stream_offers(20) == {13: 50, 14: 50}
    history = (await client.get("/api/streams/20/history")).json()
    assert len(history) == 1


async def test_apply_isolates_failures(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    response = await client.post(
        "/api/bulk/replace-offer/apply",
        json={
            "from_offer_id": 11,
            "to_offer_id": 14,
            "publish": True,
            "targets": [
                {"campaign_id": 1, "stream_id": 11},  # offer 11 isn't there
                {"campaign_id": 2, "stream_id": 20},
            ],
        },
    )
    first, second = response.json()
    assert first["status"] == "error"
    assert "not active" in first["detail"]
    assert second["status"] == "published"
    assert keitaro.stream_offers(11) == {12: 100}


async def test_replace_into_an_existing_offer_merges_shares(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    response = await client.post(
        "/api/bulk/replace-offer/apply",
        json={
            "from_offer_id": 11,
            "to_offer_id": 12,
            "publish": True,
            "targets": [{"campaign_id": 1, "stream_id": 10}],
        },
    )
    assert response.json()[0]["status"] == "published"
    assert keitaro.stream_offers(10) == {12: 100}


async def test_apply_validation(client: AsyncClient) -> None:
    base = {"from_offer_id": 11, "to_offer_id": 14}
    assert (
        await client.post("/api/bulk/replace-offer/apply", json={**base, "targets": []})
    ).status_code == 422
    response = await client.post(
        "/api/bulk/replace-offer/apply",
        json={
            "from_offer_id": 11,
            "to_offer_id": 11,
            "targets": [{"campaign_id": 1, "stream_id": 10}],
        },
    )
    assert response.status_code == 422
