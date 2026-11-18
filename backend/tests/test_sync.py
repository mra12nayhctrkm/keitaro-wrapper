import asyncio
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient

from app.config import Settings
from app.keitaro.client import KeitaroUnavailableError
from app.main import create_app
from app.services import sync
from tests.fake_keitaro import FakeKeitaro

CAMPAIGN = 9
STREAM = 90


@pytest.fixture(autouse=True)
def campaign(keitaro: FakeKeitaro) -> None:
    keitaro.add_campaign(CAMPAIGN, "sync")
    keitaro.add_stream(CAMPAIGN, stream_id=STREAM, name="Offers", offers={11: 50, 12: 50})


async def call(client: AsyncClient, method: str, url: str, **kwargs: Any) -> Any:
    response = await client.request(method, url, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


async def fetch_stream(client: AsyncClient) -> dict[str, Any]:
    data = await call(client, "POST", f"/api/campaigns/{CAMPAIGN}/fetch")
    stream: dict[str, Any] = data["streams"][0]
    return stream


async def test_remote_change_under_a_draft_blocks_push_until_acknowledged(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await fetch_stream(client)
    await call(client, "POST", f"/api/streams/{STREAM}/offers", json={"offer_id": 13})
    keitaro.streams[STREAM]["offers"][0]["share"] = 70  # someone edits Keitaro
    keitaro.streams[STREAM]["offers"][1]["share"] = 30

    stream = await fetch_stream(client)
    assert stream["remote_changed_at"] is not None
    assert stream["is_dirty"] is True

    response = await client.post(f"/api/streams/{STREAM}/push")
    assert response.status_code == 409
    assert "changed under your draft" in response.json()["detail"]
    assert keitaro.stream_offers(STREAM) == {11: 70, 12: 30}

    stream = await call(client, "POST", f"/api/streams/{STREAM}/acknowledge")
    assert stream["remote_changed_at"] is None
    await call(client, "POST", f"/api/streams/{STREAM}/push")
    assert set(keitaro.stream_offers(STREAM)) == {11, 12, 13}


async def test_no_flag_without_a_draft_or_without_a_change(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    await fetch_stream(client)
    await call(client, "POST", f"/api/streams/{STREAM}/offers", json={"offer_id": 13})
    assert (await fetch_stream(client))["remote_changed_at"] is None  # nothing changed remotely

    await call(client, "POST", f"/api/streams/{STREAM}/cancel")
    keitaro.streams[STREAM]["offers"][0]["share"] = 60
    keitaro.streams[STREAM]["offers"][1]["share"] = 40
    stream = await fetch_stream(client)
    assert stream["remote_changed_at"] is None  # no draft: just follow Keitaro
    assert [o["share"] for o in stream["offers"]] == [60, 40]


async def test_cancel_clears_the_flag(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    await fetch_stream(client)
    await call(client, "POST", f"/api/streams/{STREAM}/offers", json={"offer_id": 13})
    keitaro.streams[STREAM]["offers"].pop()
    assert (await fetch_stream(client))["remote_changed_at"] is not None
    stream = await call(client, "POST", f"/api/streams/{STREAM}/cancel")
    assert stream["remote_changed_at"] is None


async def test_sync_all_refreshes_known_campaigns_and_survives_errors(
    app: FastAPI, client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    keitaro.add_campaign(10, "second")
    keitaro.add_stream(10, stream_id=100, offers={11: 100})
    await call(client, "POST", f"/api/campaigns/{CAMPAIGN}/fetch")
    await call(client, "POST", "/api/campaigns/10/fetch")

    keitaro.streams[STREAM]["offers"][0]["share"] = 80
    keitaro.streams[STREAM]["offers"][1]["share"] = 20
    del keitaro.campaigns[10]  # deleted in Keitaro: logged, not fatal

    state = app.state
    synced = await sync.sync_all(state.sessionmaker, keitaro, state.catalog)
    assert synced == 1
    stream = (await call(client, "GET", f"/api/campaigns/{CAMPAIGN}"))["streams"][0]
    assert [o["share"] for o in stream["offers"]] == [80, 20]

    keitaro.fail["get_campaign"] = KeitaroUnavailableError("down")
    assert await sync.sync_all(state.sessionmaker, keitaro, state.catalog) == 0


async def test_run_forever_keeps_going_after_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[int] = []
    third_run = asyncio.Event()

    async def flaky(*_: Any) -> int:
        runs.append(1)
        if len(runs) == 3:
            third_run.set()
        if len(runs) == 1:
            raise RuntimeError("boom")
        return 0

    monkeypatch.setattr(sync, "sync_all", flaky)
    task = asyncio.create_task(sync.run_forever(0.01, None, None, None))  # type: ignore[arg-type]
    await asyncio.wait_for(third_run.wait(), timeout=5)  # survived the first failure
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.usefixtures("migrated_db")
async def test_lifespan_starts_and_stops_the_sync_task(
    settings: Settings, keitaro: FakeKeitaro
) -> None:
    app = create_app(
        settings.model_copy(update={"auto_sync_interval": 3600}),
        keitaro=keitaro,
        frontend_dist=None,
    )
    async with LifespanManager(app):
        task = app.state.sync_task
        assert task is not None
        assert not task.done()
    assert task.cancelled()
