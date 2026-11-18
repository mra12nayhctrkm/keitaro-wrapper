import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.keitaro.client import KeitaroApi, KeitaroClient, KeitaroError, KeitaroUnavailableError
from app.services.errors import DomainError
from app.services.offers import OfferCatalog

log = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(
    settings: Settings | None = None,
    keitaro: KeitaroApi | None = None,
    frontend_dist: Path | None = FRONTEND_DIST,
) -> FastAPI:
    """App factory. Tests pass their own settings and a fake Keitaro."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        client: KeitaroClient | None = None
        api = keitaro
        if api is None:
            if not settings.keitaro_api_key.get_secret_value():
                log.warning("KEITARO_API_KEY is not set: Keitaro requests will fail with 401")
            client = KeitaroClient(
                settings.keitaro_api_url,
                settings.keitaro_api_key.get_secret_value(),
                timeout=settings.keitaro_timeout,
            )
            api = client
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.keitaro = api
        app.state.catalog = OfferCatalog(api, settings.offers_cache_ttl)
        try:
            yield
        finally:
            if client is not None:
                await client.aclose()
            await engine.dispose()

    app = FastAPI(title="Keitaro Wrapper", version="1.0.0", lifespan=lifespan)
    app.include_router(router)

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(KeitaroError)
    async def keitaro_error(_: Request, exc: KeitaroError) -> JSONResponse:
        # 401/403 from Keitaro is our misconfiguration, not the user's: say so.
        detail = (
            "Keitaro rejected the API key: check KEITARO_API_KEY."
            if exc.status_code in (401, 403)
            else f"Keitaro: {exc.message}"
        )
        return JSONResponse(status_code=502, content={"detail": detail})

    @app.exception_handler(KeitaroUnavailableError)
    async def keitaro_unavailable(_: Request, exc: KeitaroUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    if frontend_dist is not None and (frontend_dist / "index.html").is_file():
        _mount_frontend(app, frontend_dist)

    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA; unknown non-API paths fall back to index.html."""
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(index)
