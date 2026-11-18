import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.fake_keitaro import FakeKeitaro

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # never read the developer's .env
        # CI also runs the suite on PostgreSQL by setting TEST_DATABASE_URL.
        database_url=os.environ.get("TEST_DATABASE_URL")
        or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        keitaro_api_key="test-key",
        campaign_prefix="test_mkrtchyan_",
        auto_sync_interval=0,  # tests drive syncing explicitly
    )


@pytest.fixture
def migrated_db(settings: Settings) -> Iterator[None]:
    """
    Build the schema through Alembic, the same way it is built in production,
    and tear it down with the downgrades (so they are exercised on every test).
    """
    config = Config(BACKEND / "alembic.ini")
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    yield
    command.downgrade(config, "base")


@pytest.fixture
def keitaro() -> FakeKeitaro:
    fake = FakeKeitaro()
    fake.add_offer(11, "Miaflow [BEAUTY-RO-BE_0009]")
    fake.add_offer(12, "Miaflow [BEAUTY-RO-BE_0008]")
    fake.add_offer(13, "FitoMishki [Weight Loss-CO-DT_0309]")
    fake.add_offer(14, "Oxys [BEAUTY-CL-BE_0155]")
    fake.add_offer(15, "Archived offer", state="deleted")
    return fake


@pytest.fixture
def app(settings: Settings, keitaro: FakeKeitaro) -> FastAPI:
    return create_app(settings, keitaro=keitaro, frontend_dist=None)


@pytest.fixture
async def client(app: FastAPI, migrated_db: None) -> AsyncIterator[AsyncClient]:
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
