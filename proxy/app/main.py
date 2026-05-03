from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .router import router

logger = logging.getLogger("chatgpt_proxy")
access_logger = logging.getLogger("chatgpt_proxy.access")
API_KEY_EXEMPT_PATHS = {"/health", "/v1/models", "/docs", "/openapi.json", "/redoc"}


def _openai_error(message: str, status_code: int, code: str | None = None) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": "invalid_request_error" if status_code < 500 else "server_error",
            "code": code,
        }
    }


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        started = time.monotonic()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        logger_method = access_logger.info
        access_logger.info("→ %s %s", request.method, request.url.path)
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if status_code >= 400:
                logger_method = access_logger.warning
            logger_method("← %s %s %s %dms", status_code, request.method, request.url.path, elapsed_ms)


async def api_key_middleware(request: Request, call_next):
    if request.url.path in API_KEY_EXEMPT_PATHS or not request.url.path.startswith("/v1/"):
        return await call_next(request)

    if not settings.api_key:
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    if authorization != f"Bearer {settings.api_key}":
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=_openai_error("Invalid API key", status.HTTP_401_UNAUTHORIZED, "invalid_api_key"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(
        title="chatgpt-openai-proxy",
        description="OpenAI-compatible proxy for the local ChatGPT runtime",
        version="0.1.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.middleware("http")(api_key_middleware)
    app.include_router(router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail, headers=getattr(exc, "headers", None))
        return JSONResponse(
            status_code=exc.status_code,
            content=_openai_error(str(detail or "HTTP error"), exc.status_code),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=_openai_error(f"Validation error: {exc.errors()}", 422, "validation_error"))

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled proxy exception: %s", exc)
        return JSONResponse(status_code=500, content=_openai_error(f"Internal proxy error: {type(exc).__name__}: {exc}", 500, "proxy_error"))

    return app


app = create_app()
