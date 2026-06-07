"""API key authentication for HTTP and WebSocket clients."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config

_UNAUTHORIZED = {
    "detail": (
        "Invalid or missing API key. "
        "Send X-API-Key: <key> or Authorization: Bearer <key>."
    )
}


def extract_api_key(request: Request) -> str | None:
    """Read API key from standard headers or ?api_key= query param."""
    header_key = request.headers.get("x-api-key")
    if header_key:
        return header_key.strip()

    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()

    query_key = request.query_params.get("api_key")
    if query_key:
        return query_key.strip()

    return None


def extract_ws_api_key(websocket) -> str | None:
    """Read API key from WebSocket query string or headers."""
    query_key = websocket.query_params.get("api_key")
    if query_key:
        return query_key.strip()

    header_key = websocket.headers.get("x-api-key")
    if header_key:
        return header_key.strip()

    auth = websocket.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return None


def verify_api_key(key: str | None) -> bool:
    """Return True when auth is disabled or the key matches."""
    if not config.API_KEY:
        return True
    return bool(key) and key == config.API_KEY


def is_public_path(path: str, method: str) -> bool:
    """Paths that may load without an API key (UI shell, assets, docs)."""
    if path.startswith("/static/"):
        return True
    if method == "GET" and path in ("/", "/anpr/live"):
        return True
    if path in ("/docs", "/redoc", "/openapi.json"):
        return True
    return False


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Reject HTTP requests without a valid API key when OCR_API_KEY is set."""

    async def dispatch(self, request: Request, call_next):
        if not config.API_KEY:
            return await call_next(request)

        if is_public_path(request.url.path, request.method):
            return await call_next(request)

        if verify_api_key(extract_api_key(request)):
            return await call_next(request)

        return JSONResponse(status_code=401, content=_UNAUTHORIZED)
