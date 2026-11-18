"""Campaign creator: one campaign, two streams (geo → Google, everyone else → offer)."""

import logging
import re
import secrets
import string
from collections.abc import Iterable
from dataclasses import dataclass

import pycountry

from app.config import Settings
from app.keitaro.client import KeitaroApi, KeitaroError, KeitaroUnavailableError, KtNamed
from app.services.errors import ValidationError
from app.services.offers import OfferCatalog

log = logging.getLogger(__name__)

_ALIAS_ALPHABET = string.ascii_letters + string.digits


@dataclass(frozen=True, slots=True)
class CampaignDraft:
    name: str
    geo: list[str]
    offer_id: int
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None


@dataclass(frozen=True, slots=True)
class Defaults:
    domain_id: int | None
    group_id: int | None
    traffic_source_id: int | None


def normalize_geo(raw: str | Iterable[str]) -> list[str]:
    """`"mx, au;RO  mx"` -> `["MX", "AU", "RO"]`; rejects unknown ISO 3166-1 alpha-2 codes."""
    parts = re.split(r"[\s,;]+", raw) if isinstance(raw, str) else list(raw)
    codes: list[str] = []
    for part in parts:
        code = part.strip().upper()
        if code and code not in codes:
            codes.append(code)
    if not codes:
        raise ValidationError("Specify at least one country code, e.g. MX, AU, RO.")
    unknown = [c for c in codes if len(c) != 2 or pycountry.countries.get(alpha_2=c) is None]
    if unknown:
        raise ValidationError(f"Unknown country code(s): {', '.join(unknown)}.")
    return codes


def apply_prefix(name: str, prefix: str) -> str:
    name = name.strip()
    if not name:
        raise ValidationError("Campaign name is required.")
    return name if name.startswith(prefix) else f"{prefix}{name}"


def _find_by_name(items: Iterable[KtNamed], name: str) -> int | None:
    """ID of the item called `name`; if there is no such item but only one exists, that one."""

    def norm(value: str) -> str:
        return re.sub(r"^https?://", "", value.strip().lower()).rstrip("/")

    items = list(items)
    target = norm(name)
    found = next((i.id for i in items if norm(i.name) == target), None)
    if found is None and len(items) == 1:
        return items[0].id
    return found


class CampaignCreator:
    def __init__(self, keitaro: KeitaroApi, catalog: OfferCatalog, settings: Settings) -> None:
        self._keitaro = keitaro
        self._catalog = catalog
        self._settings = settings

    async def options(self) -> tuple[list[KtNamed], list[KtNamed], list[KtNamed], Defaults]:
        domains = await self._keitaro.list_domains()
        groups = await self._keitaro.list_campaign_groups()
        sources = await self._keitaro.list_traffic_sources()
        defaults = Defaults(
            domain_id=_find_by_name(domains, self._settings.default_domain),
            group_id=_find_by_name(groups, self._settings.default_group),
            traffic_source_id=_find_by_name(sources, self._settings.default_traffic_source),
        )
        return domains, groups, sources, defaults

    async def create(self, draft: CampaignDraft) -> int:
        """Create the campaign in Keitaro and return its ID. All-or-nothing."""
        name = apply_prefix(draft.name, self._settings.campaign_prefix)
        geo = normalize_geo(draft.geo)
        offer = await self._catalog.get(draft.offer_id)

        _, _, _, defaults = await self.options()
        domain_id = draft.domain_id or defaults.domain_id
        group_id = draft.group_id or defaults.group_id
        source_id = draft.traffic_source_id or defaults.traffic_source_id
        missing = [
            label
            for label, value in (
                ("domain", domain_id),
                ("group", group_id),
                ("traffic source", source_id),
            )
            if value is None
        ]
        if missing:
            raise ValidationError(f"Choose a {', '.join(missing)}: no default found in Keitaro.")

        campaign = await self._keitaro.create_campaign(
            {
                "name": name,
                "alias": "".join(secrets.choice(_ALIAS_ALPHABET) for _ in range(8)),
                "type": "position",
                "state": "active",
                "domain_id": domain_id,
                "group_id": group_id,
                "traffic_source_id": source_id,
            }
        )
        try:
            await self._keitaro.create_stream(
                {
                    "campaign_id": campaign.id,
                    "type": "regular",
                    "name": f"Geo {', '.join(geo)} → Google",
                    "position": 1,
                    "state": "active",
                    "schema": "redirect",
                    "action_type": "http",
                    "action_payload": self._settings.geo_redirect_url,
                    "collect_clicks": True,
                    "filter_or": False,
                    "filters": [{"name": "country", "mode": "accept", "payload": geo}],
                }
            )
            await self._keitaro.create_stream(
                {
                    "campaign_id": campaign.id,
                    "type": "regular",
                    "name": "Offers",
                    "position": 2,
                    "state": "active",
                    "schema": "landings",
                    "action_type": "http",  # required by Keitaro even for offer streams
                    "collect_clicks": True,
                    "offers": [{"offer_id": offer.id, "share": 100, "state": "active"}],
                }
            )
        except (KeitaroError, KeitaroUnavailableError):
            # Don't leave a half-configured campaign behind.
            try:
                await self._keitaro.delete_campaign(campaign.id)
            except (KeitaroError, KeitaroUnavailableError):
                log.exception("Rollback failed: campaign %s is left in Keitaro", campaign.id)
            raise
        return campaign.id
