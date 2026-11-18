"""
Server for the Playwright end-to-end tests: the real app (API + built UI)
backed by the in-memory FakeKeitaro, plus a test-only endpoint to inspect
what "Keitaro" received.

    uv run python -m tests.e2e_server   # http://127.0.0.1:8899
"""

import os
import tempfile
from pathlib import Path
from typing import Any

import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app
from tests.fake_keitaro import FakeKeitaro

BACKEND = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("E2E_PORT", "8899"))


def seeded_keitaro() -> FakeKeitaro:
    fake = FakeKeitaro()
    fake.add_offer(11, "Miaflow [BEAUTY-RO-BE_0009]")
    fake.add_offer(12, "Miaflow [BEAUTY-RO-BE_0008]")
    fake.add_offer(13, "FitoMishki [Weight Loss-CO-DT_0309]")
    fake.add_offer(14, "Oxys [BEAUTY-CL-BE_0155]")
    return fake


def build_app() -> FastAPI:
    db = Path(tempfile.mkdtemp()) / "e2e.db"
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{db}",
        auto_sync_interval=0,
        campaign_prefix="test_e2e_",
    )
    config = Config(BACKEND / "alembic.ini")
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")

    keitaro = seeded_keitaro()
    app = create_app(settings, keitaro=keitaro)

    @app.get("/__fake/streams/{stream_id}", include_in_schema=False)
    async def fake_stream(stream_id: int) -> dict[str, Any]:
        return keitaro.streams[stream_id]

    @app.get("/__fake/campaigns", include_in_schema=False)
    async def fake_campaigns() -> list[dict[str, Any]]:
        return [
            {**c, "streams": [s for s in keitaro.streams.values() if s["campaign_id"] == c["id"]]}
            for c in keitaro.campaigns.values()
        ]

    # Registered after the SPA catch-all, so move them to the front.
    app.router.routes.sort(key=lambda r: not getattr(r, "path", "").startswith("/__fake"))
    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=PORT, log_level="warning")
