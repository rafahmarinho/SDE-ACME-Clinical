"""Per-request context used for logging and auditing (request id, client address, user agent)."""

from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    ip: str
    user_agent: str


def client_ip(request: Request) -> str:
    # Vercel sets x-vercel-forwarded-for / x-real-ip at its edge and strips client-supplied values.
    # The address is only used for audit records and rate-limit buckets, never for authorization.
    for header in ("x-vercel-forwarded-for", "x-real-ip"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def get_context(request: Request) -> RequestContext:
    return RequestContext(
        request_id=getattr(request.state, "request_id", "-"),
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:256],
    )
