from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.deps import (
    CatalogDep,
    CreatorDep,
    EditorDep,
    KeitaroDep,
    PrincipalDep,
    PublisherDep,
    SettingsDep,
)
from app.auth import Role
from app.schemas import (
    AddOffer,
    BulkApply,
    BulkChangeOut,
    BulkOutcomeOut,
    BulkPreviewOut,
    BulkReplaceQuery,
    CampaignCreate,
    CampaignOut,
    CampaignStatsOut,
    KeitaroCampaignOut,
    MeOut,
    MetaOut,
    NamedOut,
    OfferOut,
    OfferShare,
    OfferStatsOut,
    PublishLogOut,
    StreamOut,
    StreamStatsOut,
    UpdateOffer,
)
from app.services import bulk
from app.services.creator import CampaignDraft, normalize_geo
from app.services.stats import Metrics, Period, campaign_stats


def _metrics(m: Metrics) -> dict[str, float | int]:
    return {
        "clicks": m.clicks,
        "conversions": m.conversions,
        "revenue": round(m.revenue, 2),
        "cr": m.cr,
        "epc": m.epc,
    }


router = APIRouter(prefix="/api")


@router.get("/me", summary="Who am I and what may I do")
async def me(principal: PrincipalDep) -> MeOut:
    return MeOut(
        user=principal.user, role=principal.role.value, auth_enabled=principal.auth_enabled
    )


@router.get("/meta", summary="Creator form options and defaults")
async def meta(creator: CreatorDep, settings: SettingsDep) -> MetaOut:
    domains, groups, sources, defaults = await creator.options()
    return MetaOut(
        keitaro_admin_url=settings.keitaro_admin_url,
        campaign_prefix=settings.campaign_prefix,
        domains=[NamedOut.model_validate(d) for d in domains],
        groups=[NamedOut.model_validate(g) for g in groups],
        traffic_sources=[NamedOut.model_validate(s) for s in sources],
        default_domain_id=defaults.domain_id,
        default_group_id=defaults.group_id,
        default_traffic_source_id=defaults.traffic_source_id,
    )


@router.get("/offers", summary="Search Keitaro offers by ID or name")
async def search_offers(
    catalog: CatalogDep,
    q: str = "",
    limit: int = Query(default=20, ge=1, le=100),
) -> list[OfferOut]:
    return [OfferOut.model_validate(o) for o in await catalog.search(q, limit)]


@router.get("/campaigns", summary="List Keitaro campaigns")
async def list_campaigns(keitaro: KeitaroDep, q: str = "") -> list[KeitaroCampaignOut]:
    needle = q.strip().lower()
    campaigns = [
        c
        for c in await keitaro.list_campaigns()
        if c.state != "deleted" and (not needle or needle in c.name.lower() or needle == str(c.id))
    ]
    campaigns.sort(key=lambda c: c.id, reverse=True)
    return [KeitaroCampaignOut.model_validate(c) for c in campaigns]


@router.post(
    "/campaigns",
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign with a geo stream and an offer stream",
)
async def create_campaign(
    body: CampaignCreate, creator: CreatorDep, editor: EditorDep, _: PublisherDep
) -> CampaignOut:
    campaign_id = await creator.create(
        CampaignDraft(
            name=body.name,
            geo=normalize_geo(body.geo),
            offer_id=body.offer_id,
            domain_id=body.domain_id,
            group_id=body.group_id,
            traffic_source_id=body.traffic_source_id,
        )
    )
    return CampaignOut.model_validate(await editor.fetch_campaign(campaign_id))


@router.get("/campaigns/{campaign_id}", summary="Campaign as stored in the wrapper")
async def get_campaign(campaign_id: int, editor: EditorDep) -> CampaignOut:
    return CampaignOut.model_validate(await editor.get_campaign(campaign_id))


@router.get("/campaigns/{campaign_id}/stats", summary="Clicks, conversions, revenue per offer")
async def get_stats(
    campaign_id: int, keitaro: KeitaroDep, settings: SettingsDep, period: Period = "7d"
) -> CampaignStatsOut:
    stats = await campaign_stats(keitaro, campaign_id, period, settings.stats_timezone)
    return CampaignStatsOut(
        period=stats.period,
        days=[d.isoformat() for d in stats.days],
        streams=[
            StreamStatsOut(
                stream_id=stream.stream_id,
                **_metrics(stream.total),
                offers=[
                    OfferStatsOut(
                        offer_id=offer.offer_id,
                        **_metrics(offer.total),
                        daily_clicks=[
                            offer.daily[d].clicks if d in offer.daily else 0 for d in stats.days
                        ],
                        daily_conversions=[
                            offer.daily[d].conversions if d in offer.daily else 0
                            for d in stats.days
                        ],
                    )
                    for offer in stream.offers.values()
                ],
            )
            for stream in stats.streams.values()
        ],
    )


@router.post("/campaigns/{campaign_id}/fetch", summary="Fetch streams from Keitaro")
async def fetch_campaign(campaign_id: int, editor: EditorDep) -> CampaignOut:
    return CampaignOut.model_validate(await editor.fetch_campaign(campaign_id))


@router.post("/streams/{stream_id}/offers", summary="Add an offer to a stream (draft)")
async def add_offer(stream_id: int, body: AddOffer, editor: EditorDep) -> StreamOut:
    return StreamOut.model_validate(await editor.add_offer(stream_id, body.offer_id))


@router.post("/streams/{stream_id}/push", summary="Publish the stream draft to Keitaro")
async def push_stream(stream_id: int, editor: EditorDep, _: PublisherDep) -> StreamOut:
    return StreamOut.model_validate(await editor.push(stream_id))


@router.get("/streams/{stream_id}/history", summary="Publish history, newest first")
async def stream_history(stream_id: int, editor: EditorDep) -> list[PublishLogOut]:
    return [PublishLogOut.model_validate(e) for e in await editor.history(stream_id)]


@router.post(
    "/streams/{stream_id}/history/{log_id}/restore",
    summary="Load a published version back as a draft",
)
async def restore_version(
    stream_id: int,
    log_id: int,
    editor: EditorDep,
    version: Literal["after", "before"] = Query(
        default="after", description="'after' = that push's result, 'before' = undo it"
    ),
) -> StreamOut:
    return StreamOut.model_validate(
        await editor.restore(stream_id, log_id, before=version == "before")
    )


@router.post(
    "/streams/{stream_id}/acknowledge", summary="Confirm the draft after Keitaro changed under it"
)
async def acknowledge(stream_id: int, editor: EditorDep) -> StreamOut:
    return StreamOut.model_validate(await editor.acknowledge(stream_id))


@router.post("/streams/{stream_id}/cancel", summary="Discard unpublished changes")
async def cancel_stream(stream_id: int, editor: EditorDep) -> StreamOut:
    return StreamOut.model_validate(await editor.cancel(stream_id))


@router.post("/stream-offers/{link_id}/remove", summary="Remove an offer (draft)")
async def remove_offer(link_id: int, editor: EditorDep) -> StreamOut:
    return StreamOut.model_validate(await editor.remove_offer(link_id))


@router.post("/stream-offers/{link_id}/bring-back", summary="Bring a removed offer back (draft)")
async def bring_back(link_id: int, editor: EditorDep) -> StreamOut:
    return StreamOut.model_validate(await editor.bring_back(link_id))


@router.patch("/stream-offers/{link_id}", summary="Pin/unpin or set an offer's share (draft)")
async def update_offer(link_id: int, body: UpdateOffer, editor: EditorDep) -> StreamOut:
    return StreamOut.model_validate(
        await editor.update_offer(link_id, pinned=body.pinned, share=body.share)
    )


def _shares(mapping: dict[int, int]) -> list[OfferShare]:
    return [OfferShare(offer_id=k, share=v) for k, v in mapping.items()]


@router.post("/bulk/replace-offer/preview", summary="Which streams a bulk replace would change")
async def bulk_preview(body: BulkReplaceQuery, keitaro: KeitaroDep) -> BulkPreviewOut:
    result = await bulk.preview(
        keitaro, body.group_id, body.from_offer_id, body.to_offer_id, body.name_filter
    )
    return BulkPreviewOut(
        scanned_campaigns=result.scanned_campaigns,
        errors=result.errors,
        changes=[
            BulkChangeOut(
                campaign_id=c.campaign_id,
                campaign_name=c.campaign_name,
                stream_id=c.stream_id,
                stream_name=c.stream_name,
                before=_shares(c.before),
                after=_shares(c.after),
            )
            for c in result.changes
        ],
    )


@router.post("/bulk/replace-offer/apply", summary="Replace the offer in the chosen streams")
async def bulk_apply(
    body: BulkApply,
    request: Request,
    principal: PrincipalDep,
    keitaro: KeitaroDep,
    catalog: CatalogDep,
) -> list[BulkOutcomeOut]:
    if body.publish and principal.role is not Role.PUBLISHER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only publishers can change Keitaro. Apply as drafts instead.",
        )
    if body.from_offer_id == body.to_offer_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose two different offers.")
    outcomes = await bulk.apply(
        request.app.state.sessionmaker,
        keitaro,
        catalog,
        principal.user,
        [(t.campaign_id, t.stream_id) for t in body.targets],
        body.from_offer_id,
        body.to_offer_id,
        body.publish,
    )
    return [
        BulkOutcomeOut(
            campaign_id=o.campaign_id, stream_id=o.stream_id, status=o.status, detail=o.detail
        )
        for o in outcomes
    ]
