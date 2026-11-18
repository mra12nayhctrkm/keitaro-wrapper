from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.keitaro.client import KeitaroApi
from app.services.creator import CampaignCreator
from app.services.editor import StreamEditor
from app.services.offers import OfferCatalog


def get_keitaro(request: Request) -> KeitaroApi:
    keitaro: KeitaroApi = request.app.state.keitaro
    return keitaro


def get_catalog(request: Request) -> OfferCatalog:
    catalog: OfferCatalog = request.app.state.catalog
    return catalog


SessionDep = Annotated[AsyncSession, Depends(get_session)]
KeitaroDep = Annotated[KeitaroApi, Depends(get_keitaro)]
CatalogDep = Annotated[OfferCatalog, Depends(get_catalog)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_editor(session: SessionDep, keitaro: KeitaroDep, catalog: CatalogDep) -> StreamEditor:
    return StreamEditor(session, keitaro, catalog)


def get_creator(keitaro: KeitaroDep, catalog: CatalogDep, settings: SettingsDep) -> CampaignCreator:
    return CampaignCreator(keitaro, catalog, settings)


EditorDep = Annotated[StreamEditor, Depends(get_editor)]
CreatorDep = Annotated[CampaignCreator, Depends(get_creator)]
