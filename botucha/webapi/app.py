"""FastAPI app factory: security checks, error mapping, routes and the static UI."""
from __future__ import annotations

import secrets
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ..config import Config
from ..memory import Memory
from ..store import Store
from .service import ServiceControl

DEFAULT_PORT = 8765
DEV_HOSTS = {"localhost:3000", "127.0.0.1:3000"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Deps:
    cfg: Config
    config_path: Path
    store: Store
    memory: Memory
    service: ServiceControl
    static_dir: Path | None
    clock: Callable[[], float] = time.time
    backups_dir: Path | None = None
    claude_key: bool = False  # whether .env has ANTHROPIC_API_KEY (the key itself stays out of here)


def create_app(deps: Deps, *, token: str | None = None, dev: bool = False, port: int = DEFAULT_PORT) -> FastAPI:
    app = FastAPI(title="Botucha", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.deps = deps
    app.state.token = token or secrets.token_urlsafe(32)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"} | (DEV_HOSTS if dev else set())

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host", "") not in hosts:
            return JSONResponse({"error": "bad host"}, status_code=400)
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS:
            sent = request.headers.get("x-botucha-token", "")
            if not secrets.compare_digest(sent, app.state.token):
                return JSONResponse({"error": "bad token"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(sqlite3.OperationalError)
    async def busy(_: Request, e: sqlite3.OperationalError):
        if "locked" in str(e) or "busy" in str(e):
            return JSONResponse({"error": "busy"}, status_code=503)
        return JSONResponse({"error": "database error"}, status_code=500)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", ())[1:])
        return JSONResponse({"error": f"{where}: {first.get('msg', 'invalid')}".strip(": ")}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        return JSONResponse({"error": str(e.detail)}, status_code=e.status_code)

    from . import routes_status
    app.include_router(routes_status.router)
    for name in ("routes_traces", "routes_memory", "routes_ratings", "routes_control", "routes_settings", "routes_claude"):
        try:
            module = __import__(f"{__package__}.{name}", fromlist=["router"])
        except ModuleNotFoundError:
            continue
        app.include_router(module.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def unknown_api(rest: str):  # a typo in the UI must fail loudly, not get index.html back
        return JSONResponse({"error": "no such API endpoint"}, status_code=404)

    if deps.static_dir and Path(deps.static_dir).is_dir():
        app.mount("/", StaticFiles(directory=deps.static_dir, html=True), name="ui")
    else:
        @app.get("/")
        async def no_ui():
            return PlainTextResponse("UI not built: cd web && npm run build:static")
    return app
