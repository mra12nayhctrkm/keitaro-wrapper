from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.keitaro.client import KeitaroClient, KeitaroError, KeitaroUnavailableError

BASE = "https://kt.test/admin_api/v1"


@pytest.fixture
async def kt() -> AsyncIterator[KeitaroClient]:
    client = KeitaroClient(BASE, "secret-key", timeout=1)
    yield client
    await client.aclose()


@respx.mock
async def test_sends_api_key_and_parses_streams(kt: KeitaroClient) -> None:
    route = respx.get(f"{BASE}/campaigns/5/streams").respond(
        json=[
            {
                "id": 1,
                "campaign_id": 5,
                "name": "Flow 2",
                "type": "regular",
                "schema": "landings",
                "position": 2,
                "state": "active",
                "unknown_field": "ignored",
                "offers": [{"id": 9, "offer_id": 11, "share": 50, "state": "active"}],
            }
        ]
    )
    (stream,) = await kt.list_streams(5)
    assert route.calls.last.request.headers["Api-Key"] == "secret-key"
    assert stream.flow_schema == "landings"
    assert stream.offers[0].offer_id == 11
    assert stream.offers[0].share == 50


@respx.mock
async def test_groups_are_filtered_by_campaign_type(kt: KeitaroClient) -> None:
    route = respx.get(f"{BASE}/groups").respond(json=[{"id": "3", "name": "FORTESTS"}])
    (group,) = await kt.list_campaign_groups()
    assert route.calls.last.request.url.params["type"] == "campaigns"
    assert group.id == 3  # Keitaro sometimes sends IDs as strings


@respx.mock
async def test_post_sends_json_body(kt: KeitaroClient) -> None:
    route = respx.post(f"{BASE}/campaigns").respond(json={"id": 7, "name": "c", "alias": "a"})
    campaign = await kt.create_campaign({"name": "c"})
    assert campaign.id == 7
    assert route.calls.last.request.content == b'{"name":"c"}'


@respx.mock
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(400, json={"error": "Alias already exists"}), "Alias already exists"),
        (httpx.Response(422, json={"message": "Invalid"}), "Invalid"),
        (httpx.Response(404, text="Not Found"), "Not Found"),
    ],
)
async def test_error_message_is_extracted(
    kt: KeitaroClient, response: httpx.Response, message: str
) -> None:
    respx.post(f"{BASE}/streams").mock(return_value=response)
    with pytest.raises(KeitaroError) as info:
        await kt.create_stream({})
    assert info.value.status_code == response.status_code
    assert info.value.message == message


@respx.mock
async def test_get_is_retried_on_5xx(kt: KeitaroClient) -> None:
    route = respx.get(f"{BASE}/offers").mock(
        side_effect=[
            httpx.Response(502),
            httpx.ConnectError("reset"),
            httpx.Response(200, json=[]),
        ]
    )
    assert await kt.list_offers() == []
    assert route.call_count == 3


@respx.mock
async def test_post_is_not_retried(kt: KeitaroClient) -> None:
    route = respx.post(f"{BASE}/campaigns").respond(503)
    with pytest.raises(KeitaroError):
        await kt.create_campaign({})
    assert route.call_count == 1


@respx.mock
async def test_network_failure_becomes_unavailable(kt: KeitaroClient) -> None:
    respx.get(f"{BASE}/domains").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(KeitaroUnavailableError, match="unreachable"):
        await kt.list_domains()


@respx.mock
async def test_empty_body_on_delete(kt: KeitaroClient) -> None:
    route = respx.delete(f"{BASE}/campaigns/7").respond(204)
    await kt.delete_campaign(7)  # no JSON to parse, must not raise
    assert route.called


@respx.mock
async def test_all_read_endpoints(kt: KeitaroClient) -> None:
    respx.get(f"{BASE}/campaigns").respond(json=[{"id": 1, "name": "a"}])
    respx.get(f"{BASE}/campaigns/1").respond(json={"id": 1, "name": "a"})
    respx.get(f"{BASE}/streams/2").respond(json={"id": 2, "campaign_id": 1})
    respx.put(f"{BASE}/streams/2").respond(json={"id": 2, "campaign_id": 1, "offers": []})
    respx.get(f"{BASE}/offers/3").respond(json={"id": 3, "name": "o"})
    respx.get(f"{BASE}/traffic_sources").respond(json=[{"id": 4, "name": "s"}])

    assert (await kt.list_campaigns())[0].name == "a"
    assert (await kt.get_campaign(1)).id == 1
    assert (await kt.get_stream(2)).offers == []
    assert (await kt.update_stream(2, {"offers": []})).id == 2
    assert (await kt.get_offer(3)).name == "o"
    assert (await kt.list_traffic_sources())[0].id == 4
