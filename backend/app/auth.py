"""
Who is calling, and what they may do.

Three ways to sign in, checked in this order:
  1. SSO via a trusted reverse proxy (e.g. oauth2-proxy in front of the app)
     that puts the signed-in user into a header (`TRUSTED_USER_HEADER`);
  2. HTTP Basic with users from `APP_USERS` ("alice:pass:publisher,bob:pass:editor")
     or the single `APP_USERNAME` / `APP_PASSWORD` (a publisher);
  3. nothing configured: the app is open and everyone may publish (local use).

Roles: an *editor* prepares drafts; a *publisher* may also push to Keitaro,
create campaigns and run bulk changes.
"""

import base64
import binascii
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from fastapi import FastAPI, Request, Response

from app.config import Settings

OPEN_PATHS = {"/api/health", "/metrics"}


class Role(StrEnum):
    EDITOR = "editor"
    PUBLISHER = "publisher"


@dataclass(frozen=True, slots=True)
class Principal:
    user: str | None
    role: Role
    auth_enabled: bool


@dataclass(frozen=True, slots=True)
class _Account:
    password: bytes
    role: Role


def parse_users(settings: Settings) -> dict[str, _Account]:
    users: dict[str, _Account] = {}
    for entry in filter(None, (e.strip() for e in settings.app_users.split(","))):
        name, sep, rest = entry.partition(":")
        password, _, role = rest.rpartition(":")
        if not sep or not name or not password or role not in Role.__members__.values():
            raise ValueError(
                f"APP_USERS entry {entry.split(':')[0]!r} must look like name:password:role "
                f"with role {' or '.join(Role)}"
            )
        users[name] = _Account(password.encode(), Role(role))
    single = settings.app_password.get_secret_value()
    if single:
        users.setdefault(settings.app_username, _Account(single.encode(), Role.PUBLISHER))
    return users


def install(app: FastAPI, settings: Settings) -> None:
    users = parse_users(settings)
    header = settings.trusted_user_header.strip()
    sso_publishers = {u.strip().lower() for u in settings.sso_publishers.split(",") if u.strip()}
    enabled = bool(users or header)

    def from_basic(request: Request) -> Principal | None:
        scheme, _, encoded = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "basic":
            return None
        try:
            name, _, password = base64.b64decode(encoded, validate=True).decode().partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return None
        account = users.get(name)
        # Compare even for unknown users so timing doesn't reveal who exists.
        expected = account.password if account else b"\0" * 32
        if hmac.compare_digest(password.encode(), expected) and account:
            return Principal(name, account.role, True)
        return None

    @app.middleware("http")
    async def authenticate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not enabled:
            request.state.principal = Principal(None, Role.PUBLISHER, False)
            return await call_next(request)
        if request.url.path in OPEN_PATHS:
            return await call_next(request)

        principal = None
        sso_user = request.headers.get(header, "").strip() if header else ""
        if sso_user:
            role = Role.PUBLISHER if sso_user.lower() in sso_publishers else Role.EDITOR
            principal = Principal(sso_user, role, True)
        elif users:
            principal = from_basic(request)

        if principal is None:
            headers = {"WWW-Authenticate": 'Basic realm="Keitaro Wrapper", charset="UTF-8"'}
            return Response(status_code=401, headers=headers if users else {})
        request.state.principal = principal
        return await call_next(request)
