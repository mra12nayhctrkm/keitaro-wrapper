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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.keitaro.client import KeitaroApi, KeitaroError, KtStreamOffer
from app.models import Campaign, OfferState, OfferStatus, PublishLog, Stream, StreamOffer
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.offers import OfferCatalog
from app.services.weights import TOTAL, Slot, distribute


class StreamEditor:
    def __init__(
        self,
        session: AsyncSession,
        keitaro: KeitaroApi,
        catalog: OfferCatalog,
        actor: str | None = None,
    ) -> None:
        self._session = session
        self._keitaro = keitaro
        self._catalog = catalog
        self._actor = actor  # who is editing, recorded in the publish history

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
        names = await self._catalog.names(refresh=True) if any(s.offers for s in kt_streams) else {}

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
            had_draft = stream.is_dirty
            if _reconcile(stream, kt.offers, names) and had_draft:
                stream.remote_changed_at = datetime.now(UTC)
            if not stream.is_dirty:
                stream.remote_changed_at = None  # nothing left to conflict with

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

    async def replace_offer(self, stream_id: int, from_offer: int, to_offer: int) -> Stream:
        """Draft: send the traffic share of `from_offer` to `to_offer` instead."""
        if from_offer == to_offer:
            raise ValidationError("Choose two different offers.")
        stream = await self._editable_stream(stream_id)
        source = next(
            (o for o in stream.offers if o.offer_id == from_offer and o.state is OfferState.ACTIVE),
            None,
        )
        if source is None:
            # Idempotent: the same replacement is already drafted (e.g. "apply as
            # drafts" first, "apply and publish" second) - nothing more to change.
            already = any(
                o.offer_id == from_offer and o.status is OfferStatus.PENDING_REMOVE
                for o in stream.offers
            ) and any(
                o.offer_id == to_offer and o.state is OfferState.ACTIVE for o in stream.offers
            )
            if already:
                return stream
            raise ValidationError(f"Offer {from_offer} is not active in stream {stream_id}.")
        target_offer = await self._catalog.get(to_offer)
        share = source.share

        if source.published_state is None:
            stream.offers.remove(source)
        else:
            source.state = OfferState.REMOVED
            source.share = 0
            source.pinned = False

        target = next((o for o in stream.offers if o.offer_id == to_offer), None)
        if target is None:
            stream.offers.append(
                StreamOffer(
                    offer_id=target_offer.id,
                    offer_name=target_offer.name,
                    state=OfferState.ACTIVE,
                    share=share,
                    pinned=False,
                    published_state=None,
                    published_share=None,
                    kt_state="active",
                )
            )
        elif target.state is OfferState.ACTIVE:
            target.share += share  # already there: it takes over the share too
        else:
            target.state = OfferState.ACTIVE
            target.share = share
        return await self._save(stream, rebalance=False)

    async def cancel(self, stream_id: int) -> Stream:
        """Drop all unpublished changes of a stream."""
        stream = await self._editable_stream(stream_id)
        for link in list(stream.offers):
            if link.published_state is None:
                stream.offers.remove(link)
            else:
                link.state = link.published_state
                link.share = link.published_share or 0
        stream.remote_changed_at = None
        return await self._save(stream, rebalance=False)

    async def acknowledge(self, stream_id: int) -> Stream:
        """The user reviewed what changed in Keitaro under their draft; allow pushing."""
        stream = await self._editable_stream(stream_id)
        stream.remote_changed_at = None
        return await self._save(stream, rebalance=False)

    # ---- publish ---------------------------------------------------------

    async def push(self, stream_id: int) -> Stream:
        """Publish the stream's draft to Keitaro (“Push to KT”)."""
        stream = await self._editable_stream(stream_id)
        if not stream.is_dirty:
            return stream
        if stream.remote_changed_at is not None:
            raise ConflictError(
                "Keitaro changed under your draft. Review the stream, then confirm "
                "the draft is still right (or cancel it) before pushing."
            )

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

        before = _snapshot(stream)
        updated = await self._keitaro.update_stream(
            stream_id,
            {
                "offers": [
                    {"offer_id": o.offer_id, "share": o.share, "state": o.kt_state} for o in active
                ],
            },
        )
        _reconcile(stream, updated.offers, {})
        stream.remote_changed_at = None
        self._session.add(
            PublishLog(
                stream_id=stream.id,
                actor=self._actor,
                before=before,
                after=_snapshot(stream),
            )
        )
        return await self._save(stream, rebalance=False)

    # ---- history ---------------------------------------------------------

    async def history(self, stream_id: int, limit: int = 50) -> list[PublishLog]:
        await self.get_stream(stream_id)  # 404 for unknown streams
        result = await self._session.scalars(
            select(PublishLog)
            .where(PublishLog.stream_id == stream_id)
            .order_by(PublishLog.id.desc())
            .limit(limit)
        )
        return list(result)

    async def restore(self, stream_id: int, log_id: int, *, before: bool = False) -> Stream:
        """
        Load a past version as a draft (publish it with Push): the result of
        that push, or with `before=True` the state it replaced ("undo").
        """
        stream = await self._editable_stream(stream_id)
        entry = await self._session.get(PublishLog, log_id)
        if entry is None or entry.stream_id != stream_id:
            raise NotFoundError(f"History entry {log_id} not found for stream {stream_id}.")

        wanted = {item["offer_id"]: item for item in (entry.before if before else entry.after)}
        for link in list(stream.offers):
            link.pinned = False  # the snapshot's shares are exact; old pins would fight them
            if link.offer_id in wanted:
                link.state = OfferState.ACTIVE
                link.share = wanted[link.offer_id]["share"]
            elif link.published_state is None:
                stream.offers.remove(link)
            else:
                link.state = OfferState.REMOVED
                link.share = 0
        known = {o.offer_id for o in stream.offers}
        for offer_id, item in wanted.items():
            if offer_id not in known:
                stream.offers.append(
                    StreamOffer(
                        offer_id=offer_id,
                        offer_name=item.get("offer_name", ""),
                        state=OfferState.ACTIVE,
                        share=item["share"],
                        pinned=False,
                        published_state=None,
                        published_share=None,
                        kt_state=item.get("state", "active"),
                    )
                )
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


def _reconcile(stream: Stream, remote: Iterable[KtStreamOffer], names: dict[int, str]) -> bool:
    """
    Make Keitaro's offers the new published state of the stream.
    Unchanged offers follow Keitaro; offers with a pending draft keep the draft.
    An offer that vanished from Keitaro becomes "removed" (kept in our archive).

    Returns True if Keitaro's offers differ from the published state we knew.
    """
    live = _live(remote)
    published_before = {
        o.offer_id: (o.published_share, o.kt_state)
        for o in stream.offers
        if o.published_state is OfferState.ACTIVE
    }
    changed = published_before != {o.offer_id: (o.share, o.state) for o in live}
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
    return changed


def _live(offers: Iterable[KtStreamOffer]) -> list[KtStreamOffer]:
    """Offers Keitaro still has in the stream (deleted ones are history)."""
    return [o for o in offers if o.state != "deleted"]


def _snapshot(stream: Stream) -> list[dict[str, Any]]:
    """The offers Keitaro has for this stream, as stored in the publish history."""
    return [
        {
            "offer_id": o.offer_id,
            "offer_name": o.offer_name,
            "share": o.published_share or 0,
            "state": o.kt_state,
        }
        for o in stream.offers
        if o.published_state is OfferState.ACTIVE
    ]
