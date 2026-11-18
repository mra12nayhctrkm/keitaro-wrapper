import base64
import binascii
import hmac
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

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
    app.state.settings = settings
    app.include_router(router)

    password = settings.app_password.get_secret_value()
    if password:
        _add_basic_auth(app, settings.app_username, password)

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(KeitaroError)
    async def keitaro_error(_: Request, exc: KeitaroError) -> JSONResponse:
        # 401/403 from Keitaro is our misconfiguration, not the user's: say so.
        if exc.status_code in (401, 403):
            return JSONResponse(
                status_code=502,
                content={"detail": "Keitaro rejected the API key: check KEITARO_API_KEY."},
            )
        # Keitaro refused the data (e.g. a name already taken): the user can fix it.
        status = 422 if exc.status_code in (400, 422) else 502
        return JSONResponse(status_code=status, content={"detail": f"Keitaro: {exc.message}"})

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, __: IntegrityError) -> JSONResponse:
        # Two requests changed the same stream at once; the loser just retries.
        return JSONResponse(
            status_code=409,
            content={"detail": "The stream was changed by another request, try again."},
        )

    @app.exception_handler(KeitaroUnavailableError)
    async def keitaro_unavailable(_: Request, exc: KeitaroUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    if frontend_dist is not None and (frontend_dist / "index.html").is_file():
        _mount_frontend(app, frontend_dist)

    return app


def _add_basic_auth(app: FastAPI, username: str, password: str) -> None:
    """Protect everything except the health check with HTTP Basic auth."""
    expected = f"{username}:{password}".encode()

    @app.middleware("http")
    async def basic_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/api/health":
            return await call_next(request)
        scheme, _, encoded = request.headers.get("Authorization", "").partition(" ")
        try:
            given = base64.b64decode(encoded, validate=True) if scheme.lower() == "basic" else b""
        except binascii.Error:
            given = b""
        # Constant-time comparison: no timing hints about the password.
        if not hmac.compare_digest(given, expected):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Keitaro Wrapper", charset="UTF-8"'},
            )
        request.state.user = username
        return await call_next(request)


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA; unknown non-API paths fall back to index.html."""
    dist = dist.resolve()
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(index)
