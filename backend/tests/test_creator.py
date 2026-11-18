import pytest
from httpx import AsyncClient

from app.keitaro.client import KeitaroError, KeitaroUnavailableError
from app.services.creator import apply_prefix, normalize_geo
from app.services.errors import ValidationError
from tests.fake_keitaro import FakeKeitaro


def test_normalize_geo() -> None:
    assert normalize_geo("mx, au;RO  mx") == ["MX", "AU", "RO"]
    assert normalize_geo(["au", " Mx "]) == ["AU", "MX"]


@pytest.mark.parametrize("raw", ["", " , ", "XX", "AUS", "MX, ZZ"])
def test_normalize_geo_rejects(raw: str) -> None:
    with pytest.raises(ValidationError):
        normalize_geo(raw)


def test_apply_prefix() -> None:
    assert apply_prefix(" spring ", "test_x_") == "test_x_spring"
    assert apply_prefix("test_x_spring", "test_x_") == "test_x_spring"
    with pytest.raises(ValidationError):
        apply_prefix("  ", "test_x_")


async def test_meta_preselects_defaults(client: AsyncClient) -> None:
    response = await client.get("/api/meta")
    assert response.status_code == 200
    data = response.json()
    assert data["default_domain_id"] == 7
    assert data["default_group_id"] == 3
    assert data["default_traffic_source_id"] == 5
    assert data["campaign_prefix"] == "test_mkrtchyan_"
    assert {d["name"] for d in data["domains"]} == {"other.example", "in.posdk.xyz"}


async def test_creates_campaign_with_two_streams(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    response = await client.post(
        "/api/campaigns", json={"name": "spring", "geo": "au, mx", "offer_id": 13}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    campaign = keitaro.campaigns[body["id"]]
    assert campaign["name"] == "test_mkrtchyan_spring"
    assert (campaign["domain_id"], campaign["group_id"], campaign["traffic_source_id"]) == (7, 3, 5)
    assert campaign["type"] == "position"
    assert len(campaign["alias"]) == 8

    geo, offers = sorted(
        (s for s in keitaro.streams.values() if s["campaign_id"] == body["id"]),
        key=lambda s: s["position"],
    )
    assert geo["schema"] == "redirect"
    assert geo["action_type"] == "http"
    assert geo["action_payload"] == "https://google.com"
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU", "MX"]}]
    assert offers["schema"] == "landings"
    assert offers["action_type"] == "http"
    assert offers.get("filters", []) == []  # no filters: catches everyone else
    assert offers["offers"] == [{"offer_id": 13, "share": 100, "state": "active"}]

    # Stored locally and ready for the editor.
    assert body["name"] == "test_mkrtchyan_spring"
    assert [s["has_offers"] for s in body["streams"]] == [False, True]
    offer_row = body["streams"][1]["offers"][0]
    assert offer_row["offer_name"] == "FitoMishki [Weight Loss-CO-DT_0309]"
    assert (offer_row["share"], offer_row["status"]) == (100, "active")


async def test_explicit_domain_group_source_override_defaults(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    response = await client.post(
        "/api/campaigns",
        json={
            "name": "x",
            "geo": ["RO"],
            "offer_id": 11,
            "domain_id": 1,
            "group_id": 4,
            "traffic_source_id": 6,
        },
    )
    assert response.status_code == 201
    campaign = keitaro.campaigns[response.json()["id"]]
    assert (campaign["domain_id"], campaign["group_id"], campaign["traffic_source_id"]) == (1, 4, 6)


@pytest.mark.parametrize(
    ("payload", "status", "detail"),
    [
        ({"name": "x", "geo": "XX", "offer_id": 11}, 422, "Unknown country"),
        ({"name": "x", "geo": "", "offer_id": 11}, 422, "at least one country"),
        ({"name": "x", "geo": "AU", "offer_id": 999}, 404, "Offer 999 not found"),
        ({"name": "", "geo": "AU", "offer_id": 11}, 422, None),
        ({"name": "x", "geo": "AU", "offer_id": 0}, 422, None),
    ],
)
async def test_validation(
    client: AsyncClient,
    keitaro: FakeKeitaro,
    payload: dict[str, object],
    status: int,
    detail: str | None,
) -> None:
    response = await client.post("/api/campaigns", json=payload)
    assert response.status_code == status
    if detail:
        assert detail in response.json()["detail"]
    assert "create_campaign" not in keitaro.calls


async def test_no_default_found(client: AsyncClient, keitaro: FakeKeitaro) -> None:
    keitaro.groups = []
    response = await client.post("/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 11})
    assert response.status_code == 422
    assert "group" in response.json()["detail"]


@pytest.mark.parametrize(
    "error", [KeitaroError(400, "bad filter"), KeitaroUnavailableError("timeout")]
)
async def test_rolls_back_campaign_when_a_stream_fails(
    client: AsyncClient, keitaro: FakeKeitaro, error: Exception
) -> None:
    keitaro.fail["create_stream"] = error
    response = await client.post("/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 11})
    assert response.status_code in (422, 503)
    assert "delete_campaign" in keitaro.calls
    (campaign,) = keitaro.campaigns.values()
    assert campaign["state"] == "deleted"


async def test_failed_rollback_still_reports_the_original_error(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    keitaro.fail["create_stream"] = KeitaroError(400, "bad filter")
    keitaro.fail["delete_campaign"] = KeitaroError(500, "boom")
    response = await client.post("/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 11})
    assert response.status_code == 422
    assert "bad filter" in response.json()["detail"]


async def test_single_domain_is_used_when_default_is_missing(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    keitaro.domains = keitaro.domains[:1]  # only "other.example" is available
    response = await client.get("/api/meta")
    assert response.json()["default_domain_id"] == 1


async def test_keitaro_validation_error_is_a_readable_422(
    client: AsyncClient, keitaro: FakeKeitaro
) -> None:
    keitaro.fail["create_campaign"] = KeitaroError(400, "name: Name has already been used")
    response = await client.post("/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 11})
    assert response.status_code == 422
    assert response.json()["detail"] == "Keitaro: name: Name has already been used"
    assert "create_stream" not in keitaro.calls
