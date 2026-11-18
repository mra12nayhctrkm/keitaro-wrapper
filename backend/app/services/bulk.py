"""Bulk change across many campaigns: replace offer X with offer Y, with a preview."""

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.keitaro.client import KeitaroApi, KeitaroError, KeitaroUnavailableError, KtStream
from app.services.editor import StreamEditor, _live
from app.services.errors import DomainError, ValidationError
from app.services.offers import OfferCatalog

log = logging.getLogger(__name__)
_CONCURRENCY = 8  # parallel Keitaro reads during a preview


@dataclass(frozen=True, slots=True)
class Change:
    campaign_id: int
    campaign_name: str
    stream_id: int
    stream_name: str
    before: dict[int, int]  # offer_id -> share
    after: dict[int, int]


@dataclass(slots=True)
class Outcome:
    stream_id: int
    campaign_id: int
    status: str  # "drafted" | "published" | "error"
    detail: str = ""


@dataclass(slots=True)
class Preview:
    changes: list[Change] = field(default_factory=list)
    scanned_campaigns: int = 0
    errors: list[str] = field(default_factory=list)


def plan(before: dict[int, int], from_offer: int, to_offer: int) -> dict[int, int]:
    after = {k: v for k, v in before.items() if k != from_offer}
    after[to_offer] = after.get(to_offer, 0) + before[from_offer]
    return after


async def preview(
    keitaro: KeitaroApi, group_id: int, from_offer: int, to_offer: int, name_filter: str = ""
) -> Preview:
    if from_offer == to_offer:
        raise ValidationError("Choose two different offers.")
    needle = name_filter.strip().lower()
    campaigns = [
        c
        for c in await keitaro.list_campaigns()
        if c.group_id == group_id
        and c.state != "deleted"
        and (not needle or needle in c.name.lower())
    ]
    result = Preview(scanned_campaigns=len(campaigns))
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def streams_of(campaign_id: int) -> list[KtStream]:
        async with gate:
            return await keitaro.list_streams(campaign_id)

    found = await asyncio.gather(*(streams_of(c.id) for c in campaigns), return_exceptions=True)
    for campaign, streams in zip(campaigns, found, strict=True):
        if isinstance(streams, BaseException):
            result.errors.append(f"Campaign {campaign.id}: {streams}")
            continue
        for stream in streams:
            if stream.state == "deleted":
                continue
            before = {o.offer_id: o.share for o in _live(stream.offers)}
            if from_offer in before:
                result.changes.append(
                    Change(
                        campaign_id=campaign.id,
                        campaign_name=campaign.name,
                        stream_id=stream.id,
                        stream_name=stream.name or f"Flow #{stream.id}",
                        before=before,
                        after=plan(before, from_offer, to_offer),
                    )
                )
    return result


async def apply(
    sessionmaker: async_sessionmaker[AsyncSession],
    keitaro: KeitaroApi,
    catalog: OfferCatalog,
    actor: str | None,
    targets: list[tuple[int, int]],
    from_offer: int,
    to_offer: int,
    publish: bool,
) -> list[Outcome]:
    """
    Apply to the chosen (campaign_id, stream_id) pairs, one stream at a time,
    each in its own transaction: one failure doesn't undo or block the others.
    """
    outcomes = []
    for campaign_id, stream_id in targets:
        async with sessionmaker() as session:
            editor = StreamEditor(session, keitaro, catalog, actor)
            try:
                await editor.fetch_campaign(campaign_id)  # start from Keitaro's current state
                await editor.replace_offer(stream_id, from_offer, to_offer)
                if publish:
                    await editor.push(stream_id)
            except (DomainError, KeitaroError, KeitaroUnavailableError) as exc:
                await session.rollback()
                detail = exc.message if isinstance(exc, DomainError | KeitaroError) else str(exc)
                outcomes.append(Outcome(stream_id, campaign_id, "error", detail))
                log.warning("Bulk replace on stream %s failed: %s", stream_id, detail)
            else:
                outcomes.append(
                    Outcome(stream_id, campaign_id, "published" if publish else "drafted")
                )
    return outcomes
