from fastapi import APIRouter, Query, status

from app.api.deps import CatalogDep, CreatorDep, EditorDep, KeitaroDep, SettingsDep
from app.schemas import (
    AddOffer,
    CampaignCreate,
    CampaignOut,
    KeitaroCampaignOut,
    MetaOut,
    NamedOut,
    OfferOut,
    StreamOut,
    UpdateOffer,
)
from app.services.creator import CampaignDraft, normalize_geo

router = APIRouter(prefix="/api")


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
    body: CampaignCreate, creator: CreatorDep, editor: EditorDep
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


@router.post("/campaigns/{campaign_id}/fetch", summary="Fetch streams from Keitaro")
async def fetch_campaign(campaign_id: int, editor: EditorDep) -> CampaignOut:
    return CampaignOut.model_validate(await editor.fetch_campaign(campaign_id))


@router.post("/streams/{stream_id}/offers", summary="Add an offer to a stream (draft)")
async def add_offer(stream_id: int, body: AddOffer, editor: EditorDep) -> StreamOut:
    return StreamOut.model_validate(await editor.add_offer(stream_id, body.offer_id))


@router.post("/streams/{stream_id}/push", summary="Publish the stream draft to Keitaro")
async def push_stream(stream_id: int, editor: EditorDep) -> StreamOut:
    return StreamOut.model_validate(await editor.push(stream_id))


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
