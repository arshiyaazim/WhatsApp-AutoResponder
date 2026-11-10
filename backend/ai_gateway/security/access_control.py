from __future__ import annotations

import hmac

from .env import secret_value


class AccessConfigurationError(Exception):
    pass


class UnauthorizedError(Exception):
    pass


def verify_bearer_token(authorization: str | None, environment_name: str) -> None:
    expected = secret_value(environment_name)
    if not expected:
        raise AccessConfigurationError(f"{environment_name} is not configured")
    app_token = secret_value("APP_ACCESS_TOKEN")
    admin_token = secret_value("ADMIN_ACCESS_TOKEN")
    if app_token and admin_token and hmac.compare_digest(app_token, admin_token):
        raise AccessConfigurationError("APP_ACCESS_TOKEN and ADMIN_ACCESS_TOKEN must be distinct")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise UnauthorizedError("Unauthorized")
