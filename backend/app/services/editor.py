"""
Campaign stream editor: keeps an editable draft of each stream's offers
and publishes it to Keitaro.

Every offer row stores two states:
  * desired   — `state` / `share`, what the user edits;
  * published — `published_state` / `published_share`, what Keitaro has.
A stream is "dirty" (yellow in the UI) while they differ for any offer.
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.keitaro.client import KeitaroApi, KeitaroError, KtStreamOffer
from app.models import Campaign, OfferState, Stream, StreamOffer
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.offers import OfferCatalog
from app.services.weights import TOTAL, Slot, distribute


class StreamEditor:
    def __init__(self, session: AsyncSession, keitaro: KeitaroApi, catalog: OfferCatalog) -> None:
        self._session = session
        self._keitaro = keitaro
        self._catalog = catalog

    # ---- reading ---------------------------------------------------------

    async def get_campaign(self, campaign_id: int) -> Campaign:
        campaign = await self._session.scalar(
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .options(selectinload(Campaign.streams).selectinload(Stream.offers))
            .execution_options(populate_existing=True)
        )
        if campaign is None:
            raise NotFoundError(f"Campaign {campaign_id} has not been fetched yet.")
        return campaign

    async def get_stream(self, stream_id: int) -> Stream:
        stream = await self._session.scalar(
            select(Stream)
            .where(Stream.id == stream_id)
            .options(selectinload(Stream.offers))
            .execution_options(populate_existing=True)
        )
        if stream is None:
            raise NotFoundError(f"Stream {stream_id} not found. Fetch the campaign first.")
        return stream

    # ---- sync from Keitaro ----------------------------------------------

    async def fetch_campaign(self, campaign_id: int) -> Campaign:
        """Import or refresh a campaign and its streams from Keitaro (“Fetch streams”)."""
        try:
            kt_campaign = await self._keitaro.get_campaign(campaign_id)
        except KeitaroError as exc:
            if exc.status_code == 404:
                raise NotFoundError(f"Campaign {campaign_id} not found in Keitaro.") from exc
            raise
        kt_streams = [
            s for s in await self._keitaro.list_streams(campaign_id) if s.state != "deleted"
        ]
        names = await self._catalog.names() if any(s.offers for s in kt_streams) else {}

        campaign = await self._session.scalar(
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .options(selectinload(Campaign.streams).selectinload(Stream.offers))
        )
        if campaign is None:
            campaign = Campaign(id=campaign_id, name=kt_campaign.name)
            campaign.streams = []
            self._session.add(campaign)
        campaign.name = kt_campaign.name
        campaign.alias = kt_campaign.alias
        campaign.fetched_at = datetime.now(UTC)

        local = {s.id: s for s in campaign.streams}
        seen: set[int] = set()
        for kt in sorted(kt_streams, key=lambda s: (s.position, s.id)):
            seen.add(kt.id)
            stream = local.get(kt.id)
            if stream is None:
                stream = Stream(id=kt.id, campaign_id=campaign_id, name="", type=kt.type)
                stream.offers = []
                campaign.streams.append(stream)
            stream.name = kt.name or f"Flow #{kt.id}"
            stream.type = kt.type
            stream.schema = kt.flow_schema
            stream.position = kt.position
            _reconcile(stream, kt.offers, names)

        # Streams deleted in Keitaro disappear here too.
        campaign.streams = [s for s in campaign.streams if s.id in seen]

        await self._session.commit()
        return await self.get_campaign(campaign_id)

    # ---- draft edits -----------------------------------------------------

    async def add_offer(self, stream_id: int, offer_id: int) -> Stream:
        stream = await self._editable_stream(stream_id)
        existing = next((o for o in stream.offers if o.offer_id == offer_id), None)
        if existing is not None:
            if existing.state is OfferState.ACTIVE:
                raise ConflictError(f"Offer {offer_id} is already in this stream.")
            existing.state = OfferState.ACTIVE  # adding a removed offer = bring it back
        else:
            offer = await self._catalog.get(offer_id)
            stream.offers.append(
                StreamOffer(
                    offer_id=offer.id,
                    offer_name=offer.name,
                    state=OfferState.ACTIVE,
                    share=0,
                    pinned=False,
                    published_state=None,
                    published_share=None,
                    kt_state="active",
                )
            )
        return await self._save(stream, rebalance=True)

    async def remove_offer(self, link_id: int) -> Stream:
        link, stream = await self._editable_link(link_id)
        if link.state is OfferState.REMOVED:
            raise ConflictError("Offer is already removed.")
        if link.published_state is None:
            stream.offers.remove(link)  # never published: just drop the draft
        else:
            link.state = OfferState.REMOVED
            link.pinned = False
        return await self._save(stream, rebalance=True)

    async def bring_back(self, link_id: int) -> Stream:
        link, stream = await self._editable_link(link_id)
        if link.state is OfferState.ACTIVE:
            raise ConflictError("Offer is already active.")
        link.state = OfferState.ACTIVE
        return await self._save(stream, rebalance=True)

    async def update_offer(
        self, link_id: int, *, pinned: bool | None = None, share: int | None = None
    ) -> Stream:
        """Pin/unpin an offer's share, or set it explicitly (which pins it)."""
        link, stream = await self._editable_link(link_id)
        if link.state is not OfferState.ACTIVE:
            raise ValidationError("Only active offers can be pinned.")
        if share is not None:
            if not 0 <= share <= TOTAL:
                raise ValidationError(f"Share must be between 0 and {TOTAL}.")
            link.share = share
            link.pinned = True
        elif pinned is not None:
            link.pinned = pinned
        return await self._save(stream, rebalance=True)

    async def cancel(self, stream_id: int) -> Stream:
        """Drop all unpublished changes of a stream."""
        stream = await self._editable_stream(stream_id)
        for link in list(stream.offers):
            if link.published_state is None:
                stream.offers.remove(link)
            else:
                link.state = link.published_state
                link.share = link.published_share or 0
        return await self._save(stream, rebalance=False)

    # ---- publish ---------------------------------------------------------

    async def push(self, stream_id: int) -> Stream:
        """Publish the stream's draft to Keitaro (“Push to KT”)."""
        stream = await self._editable_stream(stream_id)
        if not stream.is_dirty:
            return stream

        active = [o for o in stream.offers if o.state is OfferState.ACTIVE]
        if active and stream.total_share != TOTAL:
            raise ValidationError(f"Shares add up to {stream.total_share}%, not {TOTAL}%.")

        # Optimistic concurrency: refuse to overwrite edits made in Keitaro
        # after our last fetch, they would be silently lost.
        remote = await self._keitaro.get_stream(stream_id)
        remote_offers = {o.offer_id: o.share for o in _live(remote.offers)}
        known_offers = {
            o.offer_id: o.published_share
            for o in stream.offers
            if o.published_state is OfferState.ACTIVE
        }
        if remote_offers != known_offers:
            raise ConflictError(
                "The stream was changed in Keitaro after the last fetch. "
                "Fetch streams again, then repeat your changes."
            )

        updated = await self._keitaro.update_stream(
            stream_id,
            {
                "offers": [
                    {"offer_id": o.offer_id, "share": o.share, "state": o.kt_state} for o in active
                ],
            },
        )
        _reconcile(stream, updated.offers, {})
        return await self._save(stream, rebalance=False)

    # ---- helpers ---------------------------------------------------------

    async def _editable_stream(self, stream_id: int) -> Stream:
        stream = await self.get_stream(stream_id)
        if not stream.has_offers:
            raise ValidationError("This stream does not send traffic to offers.")
        return stream

    async def _editable_link(self, link_id: int) -> tuple[StreamOffer, Stream]:
        link = await self._session.get(StreamOffer, link_id)
        if link is None:
            raise NotFoundError(f"Stream offer {link_id} not found.")
        stream = await self._editable_stream(link.stream_id)
        link = next(o for o in stream.offers if o.id == link_id)
        return link, stream

    async def _save(self, stream: Stream, *, rebalance: bool) -> Stream:
        if rebalance:
            shares = distribute(
                [Slot(o.state is OfferState.ACTIVE, o.pinned, o.share) for o in stream.offers]
            )
            for link, share in zip(stream.offers, shares, strict=True):
                link.share = share
        await self._session.commit()
        return await self.get_stream(stream.id)


def _reconcile(stream: Stream, remote: Iterable[KtStreamOffer], names: dict[int, str]) -> None:
    """
    Make Keitaro's offers the new published state of the stream.
    Unchanged offers follow Keitaro; offers with a pending draft keep the draft.
    An offer that vanished from Keitaro becomes "removed" (kept in our archive).
    """
    live = _live(remote)
    remote_shares = {o.offer_id: o.share for o in live}
    remote_states = {o.offer_id: o.state for o in live}

    for link in stream.offers:
        was_dirty = link.is_dirty
        if link.offer_id in remote_shares:
            link.published_state = OfferState.ACTIVE
            link.published_share = remote_shares[link.offer_id]
            link.kt_state = remote_states[link.offer_id]
        elif link.published_state is not None:
            link.published_state = OfferState.REMOVED
            link.published_share = 0
        if not was_dirty and link.published_state is not None:
            link.state = link.published_state
            link.share = link.published_share or 0
            if link.state is OfferState.REMOVED:
                link.pinned = False
        if link.offer_id in names:
            link.offer_name = names[link.offer_id]

    known = {o.offer_id for o in stream.offers}
    for offer_id, share in remote_shares.items():
        if offer_id not in known:
            stream.offers.append(
                StreamOffer(
                    offer_id=offer_id,
                    offer_name=names.get(offer_id, ""),
                    state=OfferState.ACTIVE,
                    share=share,
                    pinned=False,
                    published_state=OfferState.ACTIVE,
                    published_share=share,
                    kt_state=remote_states[offer_id],
                )
            )


def _live(offers: Iterable[KtStreamOffer]) -> list[KtStreamOffer]:
    """Offers Keitaro still has in the stream (deleted ones are history)."""
    return [o for o in offers if o.state != "deleted"]
