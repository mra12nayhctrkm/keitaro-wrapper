"""Background sync: re-fetch known campaigns from Keitaro on a schedule."""

import asyncio
import logging
import time

from prometheus_client import Counter, Gauge
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.keitaro.client import KeitaroApi, KeitaroError, KeitaroUnavailableError
from app.models import Campaign
from app.services.editor import StreamEditor
from app.services.errors import NotFoundError
from app.services.offers import OfferCatalog

log = logging.getLogger(__name__)

SYNC_RUNS = Counter("auto_sync_campaigns_total", "Campaigns re-fetched by auto-sync", ["result"])
SYNC_LAST_SUCCESS = Gauge("auto_sync_last_success_timestamp", "Unix time of the last sync run")


async def sync_all(
    sessionmaker: async_sessionmaker[AsyncSession], keitaro: KeitaroApi, catalog: OfferCatalog
) -> int:
    """Re-fetch every campaign the wrapper knows. One failure doesn't stop the rest."""
    async with sessionmaker() as session:
        campaign_ids = list(await session.scalars(select(Campaign.id).order_by(Campaign.id)))

    synced = 0
    for campaign_id in campaign_ids:
        async with sessionmaker() as session:
            try:
                await StreamEditor(session, keitaro, catalog).fetch_campaign(campaign_id)
            except NotFoundError:
                SYNC_RUNS.labels("missing").inc()
                log.warning("Auto-sync: campaign %s is gone from Keitaro", campaign_id)
            except (KeitaroError, KeitaroUnavailableError) as exc:
                SYNC_RUNS.labels("error").inc()
                log.warning("Auto-sync: campaign %s failed: %s", campaign_id, exc)
            else:
                SYNC_RUNS.labels("ok").inc()
                synced += 1
    SYNC_LAST_SUCCESS.set(time.time())
    return synced


async def run_forever(
    interval: float,
    sessionmaker: async_sessionmaker[AsyncSession],
    keitaro: KeitaroApi,
    catalog: OfferCatalog,
) -> None:
    log.info("Auto-sync every %ss", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            count = await sync_all(sessionmaker, keitaro, catalog)
            log.info("Auto-sync: %s campaign(s) refreshed", count)
        except Exception:  # keep the loop alive whatever happens
            log.exception("Auto-sync run failed")
