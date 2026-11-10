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
    app_token = os.getenv("APP_ACCESS_TOKEN", "").strip()
    admin_token = os.getenv("ADMIN_ACCESS_TOKEN", "").strip()
    if app_token and admin_token and hmac.compare_digest(app_token, admin_token):
        raise AccessConfigurationError("APP_ACCESS_TOKEN and ADMIN_ACCESS_TOKEN must be distinct")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise UnauthorizedError("Unauthorized")
