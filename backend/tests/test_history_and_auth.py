"""Publish history, restore, Basic auth, and per-app settings."""

import base64
from collections.abc import AsyncIterator
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from tests.fake_keitaro import FakeKeitaro

CAMPAIGN = 7
STREAM = 70


@pytest.fixture
def campaign(keitaro: FakeKeitaro) -> None:
    keitaro.add_campaign(CAMPAIGN, "history")
    keitaro.add_stream(CAMPAIGN, stream_id=STREAM, name="Offers", offers={11: 50, 12: 50})


async def call(client: AsyncClient, method: str, url: str, **kwargs: Any) -> Any:
    response = await client.request(method, url, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def view(stream: dict[str, Any]) -> dict[int, tuple[int, str]]:
    return {o["offer_id"]: (o["share"], o["status"]) for o in stream["offers"]}


@pytest.mark.usefixtures("campaign")
async def test_push_is_recorded_and_can_be_restored(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await call(client, "POST", f"/api/campaigns/{CAMPAIGN}/fetch")
    assert await call(client, "GET", f"/api/streams/{STREAM}/history") == []

    await call(client, "POST", f"/api/streams/{STREAM}/offers", json={"offer_id": 13})
    await call(client, "POST", f"/api/streams/{STREAM}/push")  # v1: 34/33/33
    stream = await call(client, "POST", f"/api/streams/{STREAM}/offers", json={"offer_id": 14})
    await call(client, "POST", f"/api/streams/{STREAM}/push")  # v2: 25 x 4

    history = await call(client, "GET", f"/api/streams/{STREAM}/history")
    assert len(history) == 2
    newest, oldest = history
    assert [(o["offer_id"], o["share"]) for o in oldest["before"]] == [(11, 50), (12, 50)]
    assert [(o["offer_id"], o["share"]) for o in oldest["after"]] == [(11, 34), (12, 33), (13, 33)]
    assert [o["share"] for o in newest["after"]] == [25, 25, 25, 25]
    assert newest["after"][0]["offer_name"] == "Miaflow [BEAUTY-RO-BE_0009]"
    assert newest["actor"] is None  # auth is off
    assert newest["created_at"].endswith("+00:00")

    # Restore v1 as a draft: offer 14 goes away, shares come back exactly.
    stream = await call(client, "POST", f"/api/streams/{STREAM}/history/{oldest['id']}/restore")
    assert stream["is_dirty"] is True
    assert view(stream) == {
        11: (34, "active"),
        12: (33, "active"),
        13: (33, "active"),
        14: (0, "pending_remove"),
    }
    assert keitaro.stream_offers(STREAM) == {11: 25, 12: 25, 13: 25, 14: 25}  # not yet

    await call(client, "POST", f"/api/streams/{STREAM}/push")
    assert keitaro.stream_offers(STREAM) == {11: 34, 12: 33, 13: 33}

    # "Undo" the first push: back to the original 50/50.
    stream = await call(
        client, "POST", f"/api/streams/{STREAM}/history/{oldest['id']}/restore?version=before"
    )
    assert view(stream) == {
        11: (50, "active"),
        12: (50, "active"),
        13: (0, "pending_remove"),
        14: (0, "removed"),
    }
    response = await client.post(
        f"/api/streams/{STREAM}/history/{oldest['id']}/restore?version=sideways"
    )
    assert response.status_code == 422


@pytest.mark.usefixtures("campaign")
async def test_restore_brings_back_an_offer_we_never_saw(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await call(client, "POST", f"/api/campaigns/{CAMPAIGN}/fetch")
    stream = await call(client, "POST", f"/api/streams/{STREAM}/offers", json={"offer_id": 13})
    await call(client, "POST", f"/api/streams/{STREAM}/push")
    (entry,) = await call(client, "GET", f"/api/streams/{STREAM}/history")

    # Remove offer 13 and publish: v2 without it.
    link = next(o["id"] for o in stream["offers"] if o["offer_id"] == 13)
    await call(client, "POST", f"/api/stream-offers/{link}/remove")
    await call(client, "POST", f"/api/streams/{STREAM}/push")

    stream = await call(client, "POST", f"/api/streams/{STREAM}/history/{entry['id']}/restore")
    assert view(stream)[13] == (33, "pending_add")


@pytest.mark.usefixtures("campaign")
async def test_restore_errors(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    keitaro.add_stream(CAMPAIGN, stream_id=71, name="Other", offers={11: 100})
    await call(client, "POST", f"/api/campaigns/{CAMPAIGN}/fetch")
    await call(client, "POST", "/api/streams/71/offers", json={"offer_id": 12})
    await call(client, "POST", "/api/streams/71/push")
    (other,) = await call(client, "GET", "/api/streams/71/history")

    response = await client.post(f"/api/streams/{STREAM}/history/{other['id']}/restore")
    assert response.status_code == 404  # entry belongs to another stream
    response = await client.post(f"/api/streams/{STREAM}/history/999/restore")
    assert response.status_code == 404
    assert (await client.get("/api/streams/999/history")).status_code == 404


@pytest.mark.usefixtures("campaign")
async def test_fetch_refreshes_offer_names(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    await call(client, "POST", f"/api/campaigns/{CAMPAIGN}/fetch")
    keitaro.add_offer(11, "Miaflow RENAMED")
    data = await call(client, "POST", f"/api/campaigns/{CAMPAIGN}/fetch")
    names = {o["offer_id"]: o["offer_name"] for o in data["streams"][0]["offers"]}
    assert names[11] == "Miaflow RENAMED"


# ---- auth -----------------------------------------------------------------


@pytest.fixture
async def auth_client(
    settings: Settings, migrated_db: None, keitaro: FakeKeitaro
) -> AsyncIterator[AsyncClient]:
    secured = settings.model_copy(
        update={"app_username": "boss", "app_password": SecretStr("s3cret")}
    )
    app = create_app(secured, keitaro=keitaro, frontend_dist=None)
    async with (
        LifespanManager(app) as manager,
        AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as http,
    ):
        yield http


def basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        basic("boss", "wrong"),
        basic("other", "s3cret"),
        {"Authorization": "Basic !!!not-base64"},
        {"Authorization": "Bearer s3cret"},
    ],
)
async def test_auth_rejects(auth_client: AsyncClient, headers: dict[str, str]) -> None:
    response = await auth_client.get("/api/offers", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")


async def test_health_stays_open(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/api/health")).status_code == 200


@pytest.mark.usefixtures("campaign")
async def test_auth_accepts_and_records_the_actor(auth_client: AsyncClient) -> None:
    auth = basic("boss", "s3cret")
    await call(auth_client, "POST", f"/api/campaigns/{CAMPAIGN}/fetch", headers=auth)
    await call(
        auth_client, "POST", f"/api/streams/{STREAM}/offers", json={"offer_id": 13}, headers=auth
    )
    await call(auth_client, "POST", f"/api/streams/{STREAM}/push", headers=auth)
    (entry,) = await call(auth_client, "GET", f"/api/streams/{STREAM}/history", headers=auth)
    assert entry["actor"] == "boss"


# ---- settings -------------------------------------------------------------


async def test_the_app_uses_its_own_settings(
    settings: Settings, migrated_db: None, keitaro: FakeKeitaro
) -> None:
    custom = settings.model_copy(update={"campaign_prefix": "test_custom_"})
    app = create_app(custom, keitaro=keitaro, frontend_dist=None)
    async with (
        LifespanManager(app) as manager,
        AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as http,
    ):
        assert (await http.get("/api/meta")).json()["campaign_prefix"] == "test_custom_"
        response = await http.post(
            "/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 11}
        )
    assert response.status_code == 201
    assert response.json()["name"] == "test_custom_x"
