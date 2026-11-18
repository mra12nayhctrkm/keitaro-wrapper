from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models import OfferStatus


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
    total_share: int
    offers: list[StreamOfferOut]


class CampaignOut(_Out):
    id: int
    name: str
    alias: str | None
    fetched_at: datetime | None
    streams: list[StreamOut]

    @field_serializer("fetched_at")
    def _utc(self, value: datetime | None) -> str | None:
        # SQLite drops the timezone; values are stored in UTC, so say so.
        if value is None:
            return None
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


class AddOffer(BaseModel):
    offer_id: int = Field(gt=0)


class UpdateOffer(BaseModel):
    pinned: bool | None = None
    share: int | None = Field(default=None, ge=0, le=100)
