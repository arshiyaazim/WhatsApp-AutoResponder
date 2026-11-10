from __future__ import annotations

import hmac
import os


class AccessConfigurationError(Exception):
    pass


class UnauthorizedError(Exception):
    pass


def verify_bearer_token(authorization: str | None, environment_name: str) -> None:
    expected = os.getenv(environment_name, "").strip()
    if not expected:
        raise AccessConfigurationError(f"{environment_name} is not configured")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise UnauthorizedError("Unauthorized")
