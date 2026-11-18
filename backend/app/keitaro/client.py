"""Thin typed client for the Keitaro Admin API v1."""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class KeitaroError(Exception):
    """Keitaro answered with an error status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Keitaro API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class KeitaroUnavailableError(Exception):
    """Keitaro could not be reached (network error or timeout)."""


class _Model(BaseModel):
    # Keitaro returns many more fields than we use; ignore them.
    model_config = ConfigDict(extra="ignore")


class KtNamed(_Model):
    id: int
    name: str


class KtCampaign(_Model):
    id: int
    name: str
    alias: str | None = None
    state: str | None = None


class KtOffer(_Model):
    id: int
    name: str
    state: str | None = None


class KtStreamOffer(_Model):
    offer_id: int
    share: int = 0
    state: str = "active"


class KtStream(_Model):
    # `schema` would shadow a BaseModel attribute, so it is read via an alias.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    campaign_id: int
    name: str | None = None
    type: str = "regular"
    flow_schema: str | None = Field(default=None, alias="schema")
    position: int = 0
    state: str | None = None
    offers: list[KtStreamOffer] = []


class KeitaroApi(Protocol):
    """What the app needs from Keitaro. Implemented by the HTTP client and by test fakes."""

    async def list_campaigns(self) -> list[KtCampaign]: ...
    async def get_campaign(self, campaign_id: int) -> KtCampaign: ...
    async def create_campaign(self, payload: dict[str, Any]) -> KtCampaign: ...
    async def delete_campaign(self, campaign_id: int) -> None: ...
    async def list_streams(self, campaign_id: int) -> list[KtStream]: ...
    async def get_stream(self, stream_id: int) -> KtStream: ...
    async def create_stream(self, payload: dict[str, Any]) -> KtStream: ...
    async def update_stream(self, stream_id: int, payload: dict[str, Any]) -> KtStream: ...
    async def list_offers(self) -> list[KtOffer]: ...
    async def get_offer(self, offer_id: int) -> KtOffer: ...
    async def list_domains(self) -> list[KtNamed]: ...
    async def list_campaign_groups(self) -> list[KtNamed]: ...
    async def list_traffic_sources(self) -> list[KtNamed]: ...


_campaigns = TypeAdapter(list[KtCampaign])
_streams = TypeAdapter(list[KtStream])
_offers = TypeAdapter(list[KtOffer])
_named = TypeAdapter(list[KtNamed])

_RETRIES = 2  # extra attempts for idempotent requests on network errors / 5xx


class KeitaroClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        idempotent = method in {"GET", "PUT", "DELETE"}
        attempts = 1 + (_RETRIES if idempotent else 0)
        for attempt in range(1, attempts + 1):
            try:
                response = await self._http.request(method, path, json=json, params=params)
            except httpx.TransportError as exc:
                if attempt < attempts:
                    continue
                raise KeitaroUnavailableError(f"Keitaro is unreachable: {exc}") from exc
            if response.status_code >= 500 and attempt < attempts:
                continue
            if response.is_error:
                raise KeitaroError(response.status_code, _error_message(response))
            if not response.content:
                return None
            return response.json()
        raise AssertionError("unreachable")  # pragma: no cover

    async def list_campaigns(self) -> list[KtCampaign]:
        return _campaigns.validate_python(await self._request("GET", "/campaigns"))

    async def get_campaign(self, campaign_id: int) -> KtCampaign:
        return KtCampaign.model_validate(await self._request("GET", f"/campaigns/{campaign_id}"))

    async def create_campaign(self, payload: dict[str, Any]) -> KtCampaign:
        return KtCampaign.model_validate(await self._request("POST", "/campaigns", json=payload))

    async def delete_campaign(self, campaign_id: int) -> None:
        await self._request("DELETE", f"/campaigns/{campaign_id}")

    async def list_streams(self, campaign_id: int) -> list[KtStream]:
        return _streams.validate_python(
            await self._request("GET", f"/campaigns/{campaign_id}/streams")
        )

    async def get_stream(self, stream_id: int) -> KtStream:
        return KtStream.model_validate(await self._request("GET", f"/streams/{stream_id}"))

    async def create_stream(self, payload: dict[str, Any]) -> KtStream:
        return KtStream.model_validate(await self._request("POST", "/streams", json=payload))

    async def update_stream(self, stream_id: int, payload: dict[str, Any]) -> KtStream:
        return KtStream.model_validate(
            await self._request("PUT", f"/streams/{stream_id}", json=payload)
        )

    async def list_offers(self) -> list[KtOffer]:
        return _offers.validate_python(await self._request("GET", "/offers"))

    async def get_offer(self, offer_id: int) -> KtOffer:
        return KtOffer.model_validate(await self._request("GET", f"/offers/{offer_id}"))

    async def list_domains(self) -> list[KtNamed]:
        return _named.validate_python(await self._request("GET", "/domains"))

    async def list_campaign_groups(self) -> list[KtNamed]:
        return _named.validate_python(
            await self._request("GET", "/groups", params={"type": "campaigns"})
        )

    async def list_traffic_sources(self) -> list[KtNamed]:
        return _named.validate_python(await self._request("GET", "/traffic_sources"))


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase
    if isinstance(body, dict):
        for key in ("error", "message", "errors"):
            if key in body:
                return str(body[key])
    return str(body)[:300]
