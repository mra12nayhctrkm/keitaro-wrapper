"""Keitaro offer catalog with a short in-memory cache, used by autocomplete."""

import asyncio
import time
from collections.abc import Callable

from app.keitaro.client import KeitaroApi, KeitaroError, KtOffer
from app.services.errors import NotFoundError


class OfferCatalog:
    def __init__(
        self, keitaro: KeitaroApi, ttl: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._keitaro = keitaro
        self._ttl = ttl
        self._clock = clock
        self._offers: list[KtOffer] = []
        self._loaded_at: float | None = None
        self._lock = asyncio.Lock()

    async def all(self) -> list[KtOffer]:
        async with self._lock:
            now = self._clock()
            if self._loaded_at is None or now - self._loaded_at >= self._ttl:
                offers = await self._keitaro.list_offers()
                self._offers = [o for o in offers if o.state != "deleted"]
                self._loaded_at = now
            return self._offers

    async def search(self, query: str, limit: int = 20) -> list[KtOffer]:
        """Match by ID (exact or prefix) or by name substring, case-insensitive."""
        q = query.strip().lower()
        offers = await self.all()
        if not q:
            return offers[:limit]

        def rank(o: KtOffer) -> int:
            if str(o.id) == q:
                return 0
            if str(o.id).startswith(q):
                return 1
            return 2

        matches = [o for o in offers if str(o.id).startswith(q) or q in o.name.lower()]
        return sorted(matches, key=rank)[:limit]

    async def names(self) -> dict[int, str]:
        return {o.id: o.name for o in await self.all()}

    async def get(self, offer_id: int) -> KtOffer:
        for offer in await self.all():
            if offer.id == offer_id:
                return offer
        try:  # not in the cached list: maybe created a moment ago
            return await self._keitaro.get_offer(offer_id)
        except KeitaroError as exc:
            if exc.status_code == 404:
                raise NotFoundError(f"Offer {offer_id} not found in Keitaro.") from exc
            raise
