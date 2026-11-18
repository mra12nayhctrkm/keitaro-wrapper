from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, Role
from app.config import Settings
from app.db import get_session
from app.keitaro.client import KeitaroApi
from app.services.creator import CampaignCreator
from app.services.editor import StreamEditor
from app.services.offers import OfferCatalog


def get_keitaro(request: Request) -> KeitaroApi:
    keitaro: KeitaroApi = request.app.state.keitaro
    return keitaro


def get_app_settings(request: Request) -> Settings:
    # The settings the app was created with (tests pass their own), not a global.
    settings: Settings = request.app.state.settings
    return settings


def get_principal(request: Request) -> Principal:
    """Who is calling; set by the auth middleware (app/auth.py)."""
    principal: Principal = getattr(
        request.state, "principal", Principal(None, Role.PUBLISHER, auth_enabled=False)
    )
    return principal


def require_publisher(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if principal.role is not Role.PUBLISHER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only publishers can change Keitaro. Ask a publisher."
        )
    return principal


def get_catalog(request: Request) -> OfferCatalog:
    catalog: OfferCatalog = request.app.state.catalog
    return catalog


SessionDep = Annotated[AsyncSession, Depends(get_session)]
KeitaroDep = Annotated[KeitaroApi, Depends(get_keitaro)]
CatalogDep = Annotated[OfferCatalog, Depends(get_catalog)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
PublisherDep = Annotated[Principal, Depends(require_publisher)]


def get_editor(
    session: SessionDep, keitaro: KeitaroDep, catalog: CatalogDep, principal: PrincipalDep
) -> StreamEditor:
    return StreamEditor(session, keitaro, catalog, principal.user)


def get_creator(keitaro: KeitaroDep, catalog: CatalogDep, settings: SettingsDep) -> CampaignCreator:
    return CampaignCreator(keitaro, catalog, settings)


EditorDep = Annotated[StreamEditor, Depends(get_editor)]
CreatorDep = Annotated[CampaignCreator, Depends(get_creator)]
