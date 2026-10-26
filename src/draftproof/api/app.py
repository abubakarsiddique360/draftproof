"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from draftproof import __version__
from draftproof.api.manager import RunManager
from draftproof.api.metrics import Metrics
from draftproof.api.routes import api_metadata, router
from draftproof.api.security import ApiKeyGuard, TokenBucketLimiter
from draftproof.config import Settings, configure_logging, secret_value
from draftproof.domain.errors import DraftProofError
from draftproof.pipeline.service import RunService

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _web_directory() -> Path:
    """Locate the packaged studio assets."""
    if _WEB_DIR.is_dir():
        return _WEB_DIR
    raise RuntimeError("Studio web assets were not found in the package")  # pragma: no cover


def create_app(
    settings: Settings | None = None,
    *,
    service: RunService | None = None,
) -> FastAPI:
    """Build the HTTP application.

    Args:
        settings: Runtime settings. Defaults to environment configuration.
        service: Optional pre-built service, useful for tests.

    Returns:
        A configured FastAPI application.
    """
    resolved = settings or Settings()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = service or RunService.build(resolved)
        app.state.service = active
        app.state.settings = resolved
        app.state.metrics = Metrics()
        app.state.guard = ApiKeyGuard(secret_value(resolved.service_api_key))
        app.state.limiter = TokenBucketLimiter(resolved.rate_limit_per_minute)
        app.state.manager = RunManager(active, max_workers=2, metrics=app.state.metrics)
        app.state.started_at = time.monotonic()
        logger.info(
            "DraftProof %s ready: provider=%s retriever=%s verification=%s",
            __version__,
            resolved.provider,
            resolved.retriever,
            resolved.verification_mode,
        )
        try:
            yield
        finally:
            app.state.manager.shutdown()
            if service is None:
                active.close()

    app = FastAPI(
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        **api_metadata(),
    )

    if resolved.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.cors_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key"],
            allow_credentials=False,
            max_age=600,
        )

    @app.middleware("http")
    async def harden(request: Request, call_next: Any) -> Any:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > resolved.max_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "payload_too_large",
                            "message": f"Request body exceeds {resolved.max_body_bytes} bytes",
                        }
                    },
                )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=()")
        if not request.url.path.startswith("/api"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; base-uri 'none'; form-action 'self'",
            )
        return response

    @app.exception_handler(DraftProofError)
    async def handle_draftproof_error(request: Request, exc: DraftProofError) -> JSONResponse:
        del request
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": jsonable_encoder(exc.errors()),
                }
            },
        )

    app.include_router(router)

    web_dir = _web_directory()
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="studio")
    return app


app = create_app()


def main() -> None:  # pragma: no cover - console entry point
    """Run the API with uvicorn for ``python -m draftproof.api``."""
    import uvicorn

    uvicorn.run("draftproof.api.app:app", host="127.0.0.1", port=8000, reload=False)
