from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models import OfferStatus


def _utc_iso(value: datetime) -> str:
    # SQLite drops the timezone; values are stored in UTC, so say so.
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


UtcDatetime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class NamedOut(_Out):
    id: int
    name: str


class OfferOut(_Out):
    id: int
    name: str


class KeitaroCampaignOut(_Out):
    id: int
    name: str
    alias: str | None
    state: str | None


class MetaOut(BaseModel):
    keitaro_admin_url: str
    campaign_prefix: str
    domains: list[NamedOut]
    groups: list[NamedOut]
    traffic_sources: list[NamedOut]
    default_domain_id: int | None
    default_group_id: int | None
    default_traffic_source_id: int | None


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: str | list[str] = Field(description="Country codes: 'MX, AU' or ['MX', 'AU']")
    offer_id: int = Field(gt=0)
    domain_id: int | None = Field(default=None, gt=0)
    group_id: int | None = Field(default=None, gt=0)
    traffic_source_id: int | None = Field(default=None, gt=0)


class StreamOfferOut(_Out):
    id: int
    offer_id: int
    offer_name: str
    share: int
    pinned: bool
    status: OfferStatus
    published_share: int | None


class StreamOut(_Out):
    id: int
    campaign_id: int
    name: str
    type: str
    position: int
    has_offers: bool
    is_dirty: bool
    remote_changed_at: UtcDatetime | None
    total_share: int
    offers: list[StreamOfferOut]


class CampaignOut(_Out):
    id: int
    name: str
    alias: str | None
    fetched_at: UtcDatetime | None
    streams: list[StreamOut]


class SnapshotOffer(BaseModel):
    offer_id: int
    offer_name: str = ""
    share: int
    state: str = "active"


class PublishLogOut(_Out):
    id: int
    stream_id: int
    actor: str | None
    created_at: UtcDatetime
    before: list[SnapshotOffer]
    after: list[SnapshotOffer]


class AddOffer(BaseModel):
    offer_id: int = Field(gt=0)


class UpdateOffer(BaseModel):
    pinned: bool | None = None
    share: int | None = Field(default=None, ge=0, le=100)


class MetricsOut(BaseModel):
    clicks: int
    conversions: int
    revenue: float
    cr: float
    epc: float


class OfferStatsOut(MetricsOut):
    offer_id: int
    daily_clicks: list[int]
    daily_conversions: list[int]


class StreamStatsOut(MetricsOut):
    stream_id: int
    offers: list[OfferStatsOut]


class CampaignStatsOut(BaseModel):
    period: str
    days: list[str]
    streams: list[StreamStatsOut]


class MeOut(BaseModel):
    user: str | None
    role: str
    auth_enabled: bool


class BulkReplaceQuery(BaseModel):
    group_id: int = Field(gt=0)
    from_offer_id: int = Field(gt=0)
    to_offer_id: int = Field(gt=0)
    name_filter: str = Field(default="", description="Only campaigns whose name contains this")


class OfferShare(BaseModel):
    offer_id: int
    share: int


class BulkChangeOut(BaseModel):
    campaign_id: int
    campaign_name: str
    stream_id: int
    stream_name: str
    before: list[OfferShare]
    after: list[OfferShare]


class BulkPreviewOut(BaseModel):
    scanned_campaigns: int
    changes: list[BulkChangeOut]
    errors: list[str]


class BulkTarget(BaseModel):
    campaign_id: int = Field(gt=0)
    stream_id: int = Field(gt=0)


class BulkApply(BaseModel):
    from_offer_id: int = Field(gt=0)
    to_offer_id: int = Field(gt=0)
    # Explicit list from the preview: nothing is changed that wasn't reviewed.
    targets: list[BulkTarget] = Field(min_length=1, max_length=500)
    publish: bool = False


class BulkOutcomeOut(BaseModel):
    campaign_id: int
    stream_id: int
    status: str
    detail: str
