from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Base
from tests.fake_keitaro import FakeKeitaro


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.json() == {"status": "ok"}


@pytest.mark.usefixtures("migrated_db")
async def test_migrations_match_models(settings: Settings) -> None:
    """Catches a model change committed without a migration."""
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
        )
    await engine.dispose()
    assert diff == []


@pytest.mark.usefixtures("migrated_db")
async def test_serves_built_frontend_with_spa_fallback(
    settings: Settings, tmp_path: Path, keitaro: FakeKeitaro
) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "main.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")

    app = create_app(settings, keitaro=keitaro, frontend_dist=dist)
    async with (
        LifespanManager(app) as manager,
        AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as http,
    ):
        assert (await http.get("/")).text == "<html>app</html>"
        assert (await http.get("/campaigns/5")).text == "<html>app</html>"
        assert (await http.get("/assets/main.js")).text == "console.log(1)"
        assert (await http.get("/favicon.svg")).text == "<svg/>"
        assert (await http.get("/../../etc/passwd")).text == "<html>app</html>"
        assert (await http.get("/api/health")).json() == {"status": "ok"}


@pytest.mark.usefixtures("migrated_db")
async def test_real_client_is_built_from_settings(settings: Settings) -> None:
    app = create_app(settings, frontend_dist=None)
    async with LifespanManager(app):
        assert app.state.keitaro.__class__.__name__ == "KeitaroClient"


def test_settings_urls() -> None:
    s = Settings(_env_file=None, keitaro_url="https://kt.example/")
    assert s.keitaro_api_url == "https://kt.example/admin_api/v1"
    assert s.keitaro_admin_url == "https://kt.example/admin"
