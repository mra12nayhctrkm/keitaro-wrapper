from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.fake_keitaro import FakeKeitaro

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # never read the developer's .env
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        keitaro_api_key="test-key",
        campaign_prefix="test_mkrtchyan_",
    )


@pytest.fixture
def migrated_db(settings: Settings) -> None:
    """Build the schema through Alembic, the same way it is built in production."""
    config = Config(BACKEND / "alembic.ini")
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


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
async def client(
    settings: Settings, migrated_db: None, keitaro: FakeKeitaro
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, keitaro=keitaro, frontend_dist=None)
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
