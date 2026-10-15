"""ACME Clinical API (FastAPI)."""

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.db import close_pool
from app.routers import admin, alarms, auth, devices, ingest, me, patients, reports, simulation, team, ward

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("acme.api")

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "Cross-Origin-Resource-Policy": "same-site",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}

UPLOAD_PATHS = {"/me/avatar"}


class SecurityMiddleware:
    """Pure ASGI middleware: request id, request-size limit, parameter pollution and method checks,
    security headers on every response, and removal of headers that reveal implementation details."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        request_id = secrets.token_hex(8)
        scope.setdefault("state", {})["request_id"] = request_id
        path = scope.get("path", "")
        limit = settings.max_upload_bytes + 64_000 if path in UPLOAD_PATHS else settings.max_body_bytes

        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"server", b"x-powered-by")]
                existing = {k.lower() for k, _ in headers}
                for name, value in SECURITY_HEADERS.items():
                    if name.lower().encode() not in existing:
                        headers.append((name.encode(), value.encode()))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        if scope["method"] in ("TRACE", "TRACK", "CONNECT"):
            await _error(send_wrapper, 405, "method_not_allowed", "Method not allowed.")
            return

        query = scope.get("query_string", b"").decode("latin-1")
        keys = [part.split("=", 1)[0] for part in query.split("&") if part]
        if len(keys) != len(set(keys)) or len(query) > 2048:
            await _error(send_wrapper, 400, "invalid_request", "Duplicate or oversized query parameters.")
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > limit:
                        await _error(send_wrapper, 413, "payload_too_large", "The request is too large.")
                        return
                except ValueError:
                    await _error(send_wrapper, 400, "invalid_request", "Invalid Content-Length.")
                    return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _PayloadTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except _PayloadTooLarge:
            await _error(send_wrapper, 413, "payload_too_large", "The request is too large.")
        except Exception as exc:  # noqa: BLE001 - last-resort handler: generic message, details only in logs
            log.error("unhandled error request_id=%s path=%s type=%s", request_id, path, type(exc).__name__)
            if started:
                raise
            await _error(send_wrapper, 500, "internal_error", "Something went wrong. Please try again.")


class _PayloadTooLarge(Exception):
    pass


async def _error(send: Send, status: int, code: str, message: str) -> None:
    response = JSONResponse({"error": {"code": code, "message": message}}, status_code=status)
    await response({"type": "http", "method": "GET", "path": "/", "headers": []}, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    docs = not settings.is_production
    app = FastAPI(
        title="ACME Clinical API",
        version="1.0.0",
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,  # bearer tokens only; no cookies are ever used
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition", "X-Request-Id", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": _code(exc.status_code), "message": _msg(exc)}
        return JSONResponse({"error": {**detail, "request_id": request.state.request_id}}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for err in exc.errors()[:10]:
            loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
            fields.append({"field": loc, "message": str(err.get("msg", "Invalid value")).replace("Value error, ", "")})
        return JSONResponse({"error": {"code": "validation_error", "message": "Some fields are invalid.",
                                       "fields": fields, "request_id": request.state.request_id}}, status_code=422)

    @app.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "service": "acme-clinical-api"}

    for module in (auth, me, ward, patients, alarms, devices, reports, simulation, team, admin, ingest):
        app.include_router(module.router)
    return app


def _code(status: int) -> str:
    return {404: "not_found", 405: "method_not_allowed", 401: "not_authenticated", 403: "forbidden"}.get(status, "error")


def _msg(exc: StarletteHTTPException) -> str:
    return {404: "Not found.", 405: "Method not allowed."}.get(exc.status_code, "Request failed.")


app = create_app()
