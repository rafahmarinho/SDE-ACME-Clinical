"""Uniform API errors. Clients receive a stable code and a safe message - never stack traces."""

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, headers: dict[str, str] | None = None):
        super().__init__(status_code=status_code, detail={"code": code, "message": message}, headers=headers)
        self.code = code
        self.message = message


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(404, "not_found", f"{what} not found.")


def forbidden(message: str = "You do not have permission to perform this action.") -> ApiError:
    return ApiError(403, "forbidden", message)


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def bad_request(message: str, code: str = "invalid_request") -> ApiError:
    return ApiError(400, code, message)


def unauthorized(code: str = "not_authenticated", message: str = "Please sign in to continue.") -> ApiError:
    return ApiError(401, code, message, headers={"WWW-Authenticate": "Bearer"})


def too_many(message: str = "Too many requests. Please wait and try again.", retry_after: int = 60) -> ApiError:
    return ApiError(429, "rate_limited", message, headers={"Retry-After": str(retry_after)})
