"""The editor scenario from the task video, step by step, through the HTTP API."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.keitaro.client import KeitaroError, KeitaroUnavailableError
from tests.fake_keitaro import FakeKeitaro

CAMPAIGN = 93212
GEO_STREAM = 564220
OFFER_STREAM = 564221


@pytest.fixture
def campaign(keitaro: FakeKeitaro) -> None:
    keitaro.add_campaign(CAMPAIGN, "campaign 2")
    keitaro.add_stream(
        CAMPAIGN,
        stream_id=GEO_STREAM,
        name="Flow 1",
        position=1,
        schema="redirect",
        action_payload="https://google.com",
        filters=[{"name": "country", "mode": "accept", "payload": ["AU"]}],
    )
    keitaro.add_stream(
        CAMPAIGN, stream_id=OFFER_STREAM, name="Flow 2", position=2, offers={11: 33, 12: 33, 13: 34}
    )


async def fetch(client: AsyncClient) -> dict[str, Any]:
    response = await client.post(f"/api/campaigns/{CAMPAIGN}/fetch")
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


async def offer_stream(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(f"/api/campaigns/{CAMPAIGN}")
    assert response.status_code == 200
    stream: dict[str, Any] = next(s for s in response.json()["streams"] if s["id"] == OFFER_STREAM)
    return stream


def view(stream: dict[str, Any]) -> dict[int, tuple[int, str]]:
    """offer_id -> (share, status)"""
    return {o["offer_id"]: (o["share"], o["status"]) for o in stream["offers"]}


def link_id(stream: dict[str, Any], offer_id: int) -> int:
    return int(next(o["id"] for o in stream["offers"] if o["offer_id"] == offer_id))


async def call(client: AsyncClient, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = await client.request(method, url, **kwargs)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


pytestmark = pytest.mark.usefixtures("campaign")


async def test_get_before_fetch_is_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/campaigns/{CAMPAIGN}")
    assert response.status_code == 404


async def test_fetch_imports_streams(client: AsyncClient) -> None:
    data = await fetch(client)
    assert data["name"] == "campaign 2"
    assert data["fetched_at"].endswith("+00:00")  # timezone survives SQLite
    geo, offers = data["streams"]
    # A stream without offers is listed but not parsed.
    assert (geo["name"], geo["has_offers"], geo["offers"]) == ("Flow 1", False, [])
    assert offers["has_offers"] is True
    assert offers["is_dirty"] is False
    assert view(offers) == {11: (33, "active"), 12: (33, "active"), 13: (34, "active")}
    assert offers["offers"][0]["offer_name"] == "Miaflow [BEAUTY-RO-BE_0009]"


async def test_fetch_unknown_campaign_is_404(client: AsyncClient) -> None:
    response = await client.post("/api/campaigns/1/fetch")
    assert response.status_code == 404


async def test_add_offer_is_a_draft_until_pushed(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    await fetch(client)
    stream = await call(
        client, "POST", f"/api/streams/{OFFER_STREAM}/offers", json={"offer_id": 14}
    )
    assert view(stream) == {
        11: (25, "active"),
        12: (25, "active"),
        13: (25, "active"),
        14: (25, "pending_add"),
    }
    assert stream["is_dirty"] is True
    assert keitaro.stream_offers(OFFER_STREAM) == {11: 33, 12: 33, 13: 34}  # untouched

    stream = await call(client, "POST", f"/api/streams/{OFFER_STREAM}/push")
    assert stream["is_dirty"] is False
    assert view(stream) == {o: (25, "active") for o in (11, 12, 13, 14)}
    assert keitaro.stream_offers(OFFER_STREAM) == {11: 25, 12: 25, 13: 25, 14: 25}


async def test_cancel_drops_the_draft(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    await fetch(client)
    await call(client, "POST", f"/api/streams/{OFFER_STREAM}/offers", json={"offer_id": 14})
    stream = await call(client, "POST", f"/api/streams/{OFFER_STREAM}/cancel")
    assert stream["is_dirty"] is False
    assert view(stream) == {11: (33, "active"), 12: (33, "active"), 13: (34, "active")}
    assert "update_stream" not in keitaro.calls


async def test_remove_push_bring_back(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    await fetch(client)
    stream = await offer_stream(client)

    stream = await call(client, "POST", f"/api/stream-offers/{link_id(stream, 12)}/remove")
    assert view(stream) == {11: (50, "active"), 12: (0, "pending_remove"), 13: (50, "active")}
    assert stream["is_dirty"] is True

    stream = await call(client, "POST", f"/api/streams/{OFFER_STREAM}/push")
    assert keitaro.stream_offers(OFFER_STREAM) == {11: 50, 13: 50}
    assert view(stream)[12] == (0, "removed")  # kept in our archive, grey
    assert stream["is_dirty"] is False

    stream = await call(client, "POST", f"/api/stream-offers/{link_id(stream, 12)}/bring-back")
    assert view(stream) == {11: (34, "active"), 12: (33, "pending_add"), 13: (33, "active")}

    await call(client, "POST", f"/api/streams/{OFFER_STREAM}/push")
    assert keitaro.stream_offers(OFFER_STREAM) == {11: 34, 12: 33, 13: 33}


async def test_cancel_restores_a_pending_removal(client: AsyncClient) -> None:
    await fetch(client)
    stream = await offer_stream(client)
    await call(client, "POST", f"/api/stream-offers/{link_id(stream, 12)}/remove")
    stream = await call(client, "POST", f"/api/streams/{OFFER_STREAM}/cancel")
    assert view(stream) == {11: (33, "active"), 12: (33, "active"), 13: (34, "active")}


async def test_removing_an_unpublished_offer_forgets_it(client: AsyncClient) -> None:
    await fetch(client)
    stream = await call(
        client, "POST", f"/api/streams/{OFFER_STREAM}/offers", json={"offer_id": 14}
    )
    stream = await call(client, "POST", f"/api/stream-offers/{link_id(stream, 14)}/remove")
    assert 14 not in view(stream)
    assert stream["is_dirty"] is True  # the rebalanced shares differ from Keitaro
    assert view(stream) == {11: (34, "active"), 12: (33, "active"), 13: (33, "active")}


async def test_offer_deleted_in_keitaro_becomes_removed_on_fetch(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await fetch(client)
    keitaro.streams[OFFER_STREAM]["offers"] = [{"offer_id": 11, "share": 100, "state": "active"}]

    data = await fetch(client)
    stream = data["streams"][1]
    assert view(stream) == {11: (100, "active"), 12: (0, "removed"), 13: (0, "removed")}
    assert stream["is_dirty"] is False

    stream = await call(client, "POST", f"/api/stream-offers/{link_id(stream, 13)}/bring-back")
    assert view(stream)[13] == (50, "pending_add")


async def test_offer_added_in_keitaro_appears_on_fetch(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await fetch(client)
    keitaro.streams[OFFER_STREAM]["offers"].append({"offer_id": 14, "share": 0, "state": "active"})
    stream = (await fetch(client))["streams"][1]
    assert view(stream)[14] == (0, "active")
    assert stream["offers"][-1]["offer_name"] == "Oxys [BEAUTY-CL-BE_0155]"


async def test_fetch_keeps_pending_drafts(client: AsyncClient) -> None:
    await fetch(client)
    await call(client, "POST", f"/api/streams/{OFFER_STREAM}/offers", json={"offer_id": 14})
    stream = (await fetch(client))["streams"][1]
    assert view(stream)[14] == (25, "pending_add")
    assert stream["is_dirty"] is True


async def test_stream_deleted_in_keitaro_disappears(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await fetch(client)
    del keitaro.streams[GEO_STREAM]
    data = await fetch(client)
    assert [s["id"] for s in data["streams"]] == [OFFER_STREAM]


async def test_pinned_share_survives_rebalancing(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    await fetch(client)
    await call(client, "POST", f"/api/streams/{OFFER_STREAM}/offers", json={"offer_id": 14})
    stream = await call(client, "POST", f"/api/streams/{OFFER_STREAM}/push")

    stream = await call(
        client, "PATCH", f"/api/stream-offers/{link_id(stream, 12)}", json={"pinned": True}
    )
    assert next(o for o in stream["offers"] if o["offer_id"] == 12)["pinned"] is True

    stream = await call(client, "POST", f"/api/stream-offers/{link_id(stream, 13)}/remove")
    assert view(stream) == {
        11: (38, "active"),
        12: (25, "active"),
        13: (0, "pending_remove"),
        14: (37, "active"),
    }

    await call(client, "POST", f"/api/streams/{OFFER_STREAM}/push")
    assert keitaro.stream_offers(OFFER_STREAM) == {11: 38, 12: 25, 14: 37}


async def test_set_share_explicitly_pins_it(client: AsyncClient) -> None:
    await fetch(client)
    stream = await offer_stream(client)
    stream = await call(
        client, "PATCH", f"/api/stream-offers/{link_id(stream, 13)}", json={"share": 60}
    )
    assert view(stream) == {11: (20, "active"), 12: (20, "active"), 13: (60, "active")}

    stream = await call(
        client, "PATCH", f"/api/stream-offers/{link_id(stream, 13)}", json={"pinned": False}
    )
    assert view(stream) == {11: (34, "active"), 12: (33, "active"), 13: (33, "active")}


async def test_impossible_pins_are_rejected_and_nothing_changes(client: AsyncClient) -> None:
    await fetch(client)
    stream = await offer_stream(client)
    await call(client, "PATCH", f"/api/stream-offers/{link_id(stream, 11)}", json={"share": 70})
    response = await client.patch(f"/api/stream-offers/{link_id(stream, 12)}", json={"share": 40})
    assert response.status_code == 422
    assert "more than 100" in response.json()["detail"]
    stream = await offer_stream(client)
    assert view(stream) == {11: (70, "active"), 12: (15, "active"), 13: (15, "active")}


async def test_push_refuses_to_overwrite_changes_made_in_keitaro(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await fetch(client)
    await call(client, "POST", f"/api/streams/{OFFER_STREAM}/offers", json={"offer_id": 14})
    keitaro.streams[OFFER_STREAM]["offers"].pop()  # someone edits the stream in Keitaro

    response = await client.post(f"/api/streams/{OFFER_STREAM}/push")
    assert response.status_code == 409
    assert "changed in Keitaro" in response.json()["detail"]
    assert "update_stream" not in keitaro.calls


async def test_push_without_changes_is_a_no_op(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    await fetch(client)
    stream = await call(client, "POST", f"/api/streams/{OFFER_STREAM}/push")
    assert stream["is_dirty"] is False
    assert "update_stream" not in keitaro.calls


async def test_removing_every_offer_publishes_an_empty_stream(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await fetch(client)
    stream = await offer_stream(client)
    for offer_id in (11, 12, 13):
        stream = await call(
            client, "POST", f"/api/stream-offers/{link_id(stream, offer_id)}/remove"
        )
    await call(client, "POST", f"/api/streams/{OFFER_STREAM}/push")
    assert keitaro.stream_offers(OFFER_STREAM) == {}


@pytest.mark.parametrize(
    ("method", "url", "body", "status", "detail"),
    [
        ("POST", f"/api/streams/{OFFER_STREAM}/offers", {"offer_id": 11}, 409, "already in"),
        ("POST", f"/api/streams/{OFFER_STREAM}/offers", {"offer_id": 999}, 404, "not found"),
        ("POST", f"/api/streams/{GEO_STREAM}/offers", {"offer_id": 14}, 422, "does not send"),
        ("POST", "/api/streams/1/push", None, 404, "not found"),
        ("POST", "/api/stream-offers/9999/remove", None, 404, "not found"),
    ],
)
async def test_errors(
    client: AsyncClient,
    method: str,
    url: str,
    body: dict[str, Any] | None,
    status: int,
    detail: str,
) -> None:
    await fetch(client)
    response = await client.request(method, url, json=body)
    assert response.status_code == status
    assert detail in response.json()["detail"]


async def test_state_conflicts(client: AsyncClient) -> None:
    await fetch(client)
    stream = await offer_stream(client)
    lid = link_id(stream, 11)
    assert (await client.post(f"/api/stream-offers/{lid}/bring-back")).status_code == 409
    await call(client, "POST", f"/api/stream-offers/{lid}/remove")
    assert (await client.post(f"/api/stream-offers/{lid}/remove")).status_code == 409
    response = await client.patch(f"/api/stream-offers/{lid}", json={"pinned": True})
    assert response.status_code == 422


async def test_adding_a_removed_offer_brings_it_back(client: AsyncClient) -> None:
    await fetch(client)
    stream = await offer_stream(client)
    await call(client, "POST", f"/api/stream-offers/{link_id(stream, 12)}/remove")
    stream = await call(
        client, "POST", f"/api/streams/{OFFER_STREAM}/offers", json={"offer_id": 12}
    )
    assert view(stream) == {11: (34, "active"), 12: (33, "active"), 13: (33, "active")}


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (KeitaroError(401, "Invalid API key"), 502, "check KEITARO_API_KEY"),
        (KeitaroError(500, "internal"), 502, "Keitaro: internal"),
        (KeitaroUnavailableError("Keitaro is unreachable"), 503, "unreachable"),
    ],
)
async def test_keitaro_errors_are_mapped(
    client: AsyncClient, keitaro: FakeKeitaro, error: Exception, status: int, detail: str
) -> None:
    keitaro.fail["get_campaign"] = error
    response = await client.post(f"/api/campaigns/{CAMPAIGN}/fetch")
    assert response.status_code == status
    assert detail in response.json()["detail"]


async def test_failed_push_keeps_the_draft(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    await fetch(client)
    await call(client, "POST", f"/api/streams/{OFFER_STREAM}/offers", json={"offer_id": 14})
    keitaro.fail["update_stream"] = KeitaroUnavailableError("timeout")
    assert (await client.post(f"/api/streams/{OFFER_STREAM}/push")).status_code == 503
    stream = await offer_stream(client)
    assert stream["is_dirty"] is True
    assert view(stream)[14] == (25, "pending_add")
