import json
import logging
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import SecretStr

from app import observability
from app.config import Settings
from app.keitaro.client import KeitaroClient, KeitaroError

BASE = "https://kt.test/admin_api/v1"


def test_endpoint_label_bounds_cardinality() -> None:
    assert observability.endpoint_label("/campaigns/214529/streams") == "/campaigns/{id}/streams"
    assert observability.endpoint_label("/offers") == "/offers"


async def test_request_id_is_generated_or_propagated(client: AsyncClient) -> None:
    generated = (await client.get("/api/health")).headers["X-Request-ID"]
    assert len(generated) == 32
    response = await client.get("/api/health", headers={"X-Request-ID": "trace-123"})
    assert response.headers["X-Request-ID"] == "trace-123"


async def test_metrics_endpoint_counts_api_requests(client: AsyncClient) -> None:
    await client.get("/api/campaigns/123")  # 404, a templated route
    body = (await client.get("/metrics")).text
    assert (
        'http_requests_total{method="GET",route="/api/campaigns/{campaign_id}",status="404"}'
        in body
    )
    assert "keitaro_api_key_valid" in body


@respx.mock
async def test_keitaro_calls_are_measured_and_bad_key_alerts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    kt = KeitaroClient(BASE, "bad", backoff=0)
    respx.get(f"{BASE}/campaigns/5").respond(401, json={"error": "Invalid API key"})
    respx.get(f"{BASE}/offers").respond(json=[])
    with caplog.at_level(logging.ERROR, logger="app"):
        for _ in range(2):
            with pytest.raises(KeitaroError):
                await kt.get_campaign(5)
    assert observability.KEITARO_API_KEY_VALID._value.get() == 0
    # One alert per outage, not one per request.
    assert [r.getMessage() for r in caplog.records].count(
        "Keitaro rejected the API key (HTTP 401): check KEITARO_API_KEY"
    ) == 1

    await kt.list_offers()  # key works again
    assert observability.KEITARO_API_KEY_VALID._value.get() == 1
    await kt.aclose()

    labels = {"method": "GET", "endpoint": "/campaigns/{id}", "status": "401"}
    sample = observability.KEITARO_REQUESTS.labels(**labels)._value.get()
    assert sample >= 2


def test_json_log_format_includes_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    observability.configure_logging(Settings(_env_file=None, log_format="json"))
    token = observability.request_id_var.set("req-9")
    try:
        logging.getLogger("app.test").info("hello", extra={"status": 200, "user": "boss"})
    finally:
        observability.request_id_var.reset(token)
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["message"] == "hello"
    assert line["request_id"] == "req-9"
    assert (line["status"], line["user"], line["level"]) == (200, "boss", "INFO")


def test_sentry_is_initialised_only_with_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    observability.configure_sentry(Settings(_env_file=None))
    assert calls == []
    observability.configure_sentry(
        Settings(
            _env_file=None,
            sentry_dsn=SecretStr("https://k@sentry.test/1"),
            environment="prod",
        )
    )
    assert calls[0]["dsn"] == "https://k@sentry.test/1"
    assert calls[0]["environment"] == "prod"
    assert calls[0]["send_default_pii"] is False


@respx.mock
async def test_network_errors_are_counted() -> None:
    kt = KeitaroClient(BASE, "k", backoff=0)
    respx.get(f"{BASE}/domains").mock(side_effect=httpx.ConnectError("down"))
    before = observability.KEITARO_REQUESTS.labels("GET", "/domains", "error")._value.get()
    with pytest.raises(Exception, match="unreachable"):
        await kt.list_domains()
    after = observability.KEITARO_REQUESTS.labels("GET", "/domains", "error")._value.get()
    assert after - before == 3  # one attempt + two retries
    await kt.aclose()
