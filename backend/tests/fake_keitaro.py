"""In-memory Keitaro that behaves like the Admin API for the calls the app makes."""

from __future__ import annotations

import itertools
from typing import Any

from app.keitaro.client import (
    KeitaroError,
    KeitaroUnavailableError,
    KtCampaign,
    KtNamed,
    KtOffer,
    KtStream,
    KtStreamOffer,
)


class FakeKeitaro:
    def __init__(self) -> None:
        self.campaigns: dict[int, dict[str, Any]] = {}
        self.streams: dict[int, dict[str, Any]] = {}
        self.offers: dict[int, KtOffer] = {}
        self.domains = [KtNamed(id=1, name="other.example"), KtNamed(id=7, name="in.posdk.xyz")]
        self.groups = [KtNamed(id=3, name="FORTESTS"), KtNamed(id=4, name="Other")]
        self.sources = [KtNamed(id=5, name="FORTESTS"), KtNamed(id=6, name="Facebook")]
        self.calls: list[str] = []
        # method name -> exception to raise on the next call
        self.fail: dict[str, Exception] = {}
        self._ids = itertools.count(1000)

    # ---- helpers for tests ----------------------------------------------

    def add_offer(self, offer_id: int, name: str, state: str = "active") -> None:
        self.offers[offer_id] = KtOffer(id=offer_id, name=name, state=state)

    def add_campaign(self, campaign_id: int, name: str) -> None:
        self.campaigns[campaign_id] = {
            "id": campaign_id,
            "name": name,
            "alias": "abc",
            "state": "active",
        }

    def add_stream(
        self,
        campaign_id: int,
        *,
        stream_id: int | None = None,
        name: str = "Flow",
        position: int = 1,
        schema: str = "landings",
        offers: dict[int, int] | None = None,
        **extra: Any,
    ) -> int:
        sid = stream_id or next(self._ids)
        self.streams[sid] = {
            "id": sid,
            "campaign_id": campaign_id,
            "name": name,
            "type": "regular",
            "schema": schema,
            "position": position,
            "state": "active",
            "offers": [
                {"offer_id": o, "share": s, "state": "active"} for o, s in (offers or {}).items()
            ],
            **extra,
        }
        return sid

    def stream_offers(self, stream_id: int) -> dict[int, int]:
        return {o["offer_id"]: o["share"] for o in self.streams[stream_id]["offers"]}

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise self.fail.pop(name)

    def _campaign(self, campaign_id: int) -> dict[str, Any]:
        if campaign_id not in self.campaigns:
            raise KeitaroError(404, "Not found")
        return self.campaigns[campaign_id]

    # ---- KeitaroApi ------------------------------------------------------

    async def list_campaigns(self) -> list[KtCampaign]:
        self._call("list_campaigns")
        return [KtCampaign.model_validate(c) for c in self.campaigns.values()]

    async def get_campaign(self, campaign_id: int) -> KtCampaign:
        self._call("get_campaign")
        return KtCampaign.model_validate(self._campaign(campaign_id))

    async def create_campaign(self, payload: dict[str, Any]) -> KtCampaign:
        self._call("create_campaign")
        cid = next(self._ids)
        self.campaigns[cid] = {"id": cid, **payload}
        return KtCampaign.model_validate(self.campaigns[cid])

    async def delete_campaign(self, campaign_id: int) -> None:
        self._call("delete_campaign")
        self._campaign(campaign_id)["state"] = "deleted"

    async def list_streams(self, campaign_id: int) -> list[KtStream]:
        self._call("list_streams")
        self._campaign(campaign_id)
        return [
            KtStream.model_validate(s)
            for s in self.streams.values()
            if s["campaign_id"] == campaign_id
        ]

    async def get_stream(self, stream_id: int) -> KtStream:
        self._call("get_stream")
        if stream_id not in self.streams:
            raise KeitaroError(404, "Not found")
        return KtStream.model_validate(self.streams[stream_id])

    async def create_stream(self, payload: dict[str, Any]) -> KtStream:
        self._call("create_stream")
        self._campaign(payload["campaign_id"])
        if not payload.get("action_type"):  # the real API rejects this too
            raise KeitaroError(400, "{'action_type': ['Action Type is required']}")
        sid = next(self._ids)
        self.streams[sid] = {"id": sid, "offers": [], **payload}
        return KtStream.model_validate(self.streams[sid])

    async def update_stream(self, stream_id: int, payload: dict[str, Any]) -> KtStream:
        self._call("update_stream")
        if stream_id not in self.streams:
            raise KeitaroError(404, "Not found")
        for offer in payload.get("offers", []):
            if offer["offer_id"] not in self.offers:
                raise KeitaroError(400, f"Offer {offer['offer_id']} not found")
        self.streams[stream_id].update(payload)
        return KtStream.model_validate(self.streams[stream_id])

    async def list_offers(self) -> list[KtOffer]:
        self._call("list_offers")
        return list(self.offers.values())

    async def get_offer(self, offer_id: int) -> KtOffer:
        self._call("get_offer")
        if offer_id not in self.offers:
            raise KeitaroError(404, "Not found")
        return self.offers[offer_id]

    async def list_domains(self) -> list[KtNamed]:
        self._call("list_domains")
        return self.domains

    async def list_campaign_groups(self) -> list[KtNamed]:
        self._call("list_campaign_groups")
        return self.groups

    async def list_traffic_sources(self) -> list[KtNamed]:
        self._call("list_traffic_sources")
        return self.sources


__all__ = ["FakeKeitaro", "KeitaroError", "KeitaroUnavailableError", "KtStreamOffer"]
