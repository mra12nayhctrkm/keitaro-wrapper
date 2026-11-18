import pytest
from httpx import AsyncClient

from app.keitaro.client import KeitaroError
from app.services.errors import NotFoundError
from app.services.offers import OfferCatalog
from tests.fake_keitaro import FakeKeitaro


async def test_search_by_name_and_id(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    keitaro.add_offer(111, "Another 111")

    response = await client.get("/api/offers", params={"q": "miaflow"})
    assert [o["id"] for o in response.json()] == [11, 12]

    # Exact ID first, then ID prefix matches.
    response = await client.get("/api/offers", params={"q": "11"})
    assert [o["id"] for o in response.json()] == [11, 111]


async def test_deleted_offers_are_hidden(client: AsyncClient) -> None:
    response = await client.get("/api/offers", params={"q": "archived"})
    assert response.json() == []


async def test_empty_query_and_limit(client: AsyncClient) -> None:
    response = await client.get("/api/offers", params={"limit": 2})
    assert len(response.json()) == 2
    assert (await client.get("/api/offers", params={"limit": 0})).status_code == 422


async def test_list_is_cached_for_ttl(keitaro: FakeKeitaro) -> None:
    now = 0.0
    catalog = OfferCatalog(keitaro, ttl=60, clock=lambda: now)
    await catalog.search("a")
    await catalog.search("b")
    assert keitaro.calls.count("list_offers") == 1
    now = 61.0
    await catalog.search("c")
    assert keitaro.calls.count("list_offers") == 2


async def test_get_falls_back_to_api_for_new_offers(keitaro: FakeKeitaro) -> None:
    catalog = OfferCatalog(keitaro, ttl=60)
    await catalog.all()
    keitaro.add_offer(77, "Fresh")
    assert (await catalog.get(77)).name == "Fresh"
    with pytest.raises(NotFoundError):
        await catalog.get(78)


async def test_get_propagates_other_errors(keitaro: FakeKeitaro) -> None:
    catalog = OfferCatalog(keitaro, ttl=60)
    keitaro.fail["get_offer"] = KeitaroError(500, "boom")
    with pytest.raises(KeitaroError):
        await catalog.get(78)


async def test_list_keitaro_campaigns(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    keitaro.add_campaign(1, "test_mkrtchyan_one")
    keitaro.add_campaign(2, "Other")
    keitaro.add_campaign(3, "test_mkrtchyan_gone")
    keitaro.campaigns[3]["state"] = "deleted"

    response = await client.get("/api/campaigns")
    assert [c["id"] for c in response.json()] == [2, 1]  # newest first, no deleted
    response = await client.get("/api/campaigns", params={"q": "MKRTCHYAN"})
    assert [c["id"] for c in response.json()] == [1]
    response = await client.get("/api/campaigns", params={"q": "2"})
    assert [c["id"] for c in response.json()] == [2]
