"""Starlette + FastMCP application assembly and uvicorn entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager as _asynccontextmanager

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .auth import check_authorization
from .config import Config
from .tools import register_tools

logger = logging.getLogger("vision_mcp")

PROTECTED_PATHS = {"/mcp"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject any request to a protected path whose Bearer token does not match.

    /healthz is intentionally exempt: it is for unauthenticated monitoring.
    """

    async def dispatch(self, request, call_next):
        if request.url.path in PROTECTED_PATHS:
            header = request.headers.get("authorization")
            cfg: Config = request.app.state.config
            if not check_authorization(header, cfg.vision_bearer_token):
                return JSONResponse(
                    {"error": "unauthorized"}, status_code=401
                )
        return await call_next(request)


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app(cfg: Config) -> Starlette:
    mcp = FastMCP("vision-mcp", stateless_http=True)
    register_tools(mcp, cfg)
    mcp_app = mcp.streamable_http_app()  # exposes /mcp on its own ASGI sub-app

    # FastMCP's sub-app carries its own lifespan (initializes the
    # StreamableHTTPSessionManager's task group). Merge it into the parent
    # so the session manager is up before any /mcp request hits the app.
    mcp_lifespan = getattr(mcp_app, "router", None)
    mcp_lifespan_fn = getattr(mcp_lifespan, "lifespan_context", None)

    @_asynccontextmanager
    async def combined_lifespan(app):
        if mcp_lifespan_fn is not None:
            async with mcp_lifespan_fn(app):
                yield
        else:  # pragma: no cover - defensive fallback
            yield

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        middleware=[Middleware(AuthMiddleware)],
        lifespan=combined_lifespan,
    )
    app.state.config = cfg
    return app


def main() -> None:
    cfg = _load_via_helper()
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(build_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


def _load_via_helper() -> Config:
    from .config import load_config

    return load_config()


if __name__ == "__main__":
    main()