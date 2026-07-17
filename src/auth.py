"""Desktop-local administrator identity.

The application has no central account service and no device authorization.
FastAPI still uses a dependency so authorization remains explicit at route
boundaries, but every request from the localhost-only desktop service receives
the same administrator identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Request


Role = Literal["administrator"]
LOCAL_ADMIN_USERNAME = "local-admin"


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str = LOCAL_ADMIN_USERNAME
    role: Role = "administrator"

    @property
    def is_administrator(self) -> bool:
        return True


LOCAL_ADMIN = AuthenticatedUser()


def require_user(_request: Request) -> AuthenticatedUser:
    """Return the sole local administrator; no password or token is stored."""
    return LOCAL_ADMIN
