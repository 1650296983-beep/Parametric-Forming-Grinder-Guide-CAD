"""Small, configuration-driven session authentication for the local Web UI."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest, new
import json
import os
from time import time
from typing import Literal

from fastapi import HTTPException, Request, status


Role = Literal["administrator", "operator"]
SESSION_COOKIE_NAME = "cad_session"
SESSION_TTL_SECONDS = 8 * 60 * 60


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    role: Role

    @property
    def is_administrator(self) -> bool:
        return self.role == "administrator"


def authenticate(username: str, password: str) -> AuthenticatedUser | None:
    """Authenticate against environment-provided accounts without logging secrets."""
    account = _configured_accounts().get(username)
    if account is None or not compare_digest(account["password"], password):
        return None
    return AuthenticatedUser(username=username, role=account["role"])


def create_session_token(user: AuthenticatedUser) -> str:
    payload = {
        "sub": user.username,
        "role": user.role,
        "exp": int(time()) + SESSION_TTL_SECONDS,
    }
    encoded_payload = _encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode())
    signature = new(_session_secret().encode(), encoded_payload.encode(), sha256).digest()
    return f"{encoded_payload}.{_encode(signature)}"


def require_user(request: Request) -> AuthenticatedUser:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise _unauthorized()
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected_signature = new(
            _session_secret().encode(), encoded_payload.encode(), sha256
        ).digest()
        if not compare_digest(_encode(expected_signature), encoded_signature):
            raise ValueError("invalid session signature")
        payload = json.loads(_decode(encoded_payload))
        username = payload["sub"]
        role = payload["role"]
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise _unauthorized() from None

    if expires_at < int(time()) or role not in {"administrator", "operator"}:
        raise _unauthorized()
    account = _configured_accounts().get(username)
    if account is None or account["role"] != role:
        raise _unauthorized()
    return AuthenticatedUser(username=username, role=role)


def session_cookie_secure() -> bool:
    return os.getenv("CAD_COOKIE_SECURE", "false").lower() == "true"


def _configured_accounts() -> dict[str, dict[str, str]]:
    admin_username = _required_setting("CAD_ADMIN_USERNAME")
    admin_password = _required_setting("CAD_ADMIN_PASSWORD")
    accounts: dict[str, dict[str, str]] = {
        admin_username: {"password": admin_password, "role": "administrator"}
    }
    raw_accounts = os.getenv("CAD_OPERATOR_ACCOUNTS_JSON", "{}")
    try:
        configured_operators = json.loads(raw_accounts)
    except json.JSONDecodeError as error:
        raise _configuration_error("CAD_OPERATOR_ACCOUNTS_JSON 必须是有效 JSON 对象。") from error
    if not isinstance(configured_operators, dict):
        raise _configuration_error("CAD_OPERATOR_ACCOUNTS_JSON 必须是用户名到密码的对象。")
    for username, password in configured_operators.items():
        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
            raise _configuration_error("CAD_OPERATOR_ACCOUNTS_JSON 的用户名和密码必须为非空字符串。")
        if username in accounts:
            raise _configuration_error("操作员账户不能与管理员账户重名。")
        accounts[username] = {"password": password, "role": "operator"}
    return accounts


def _session_secret() -> str:
    return _required_setting("CAD_SESSION_SECRET")


def _required_setting(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise _configuration_error(f"服务未配置 {name} 环境变量。")


def _configuration_error(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=message)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录后再继续。")


def _encode(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(value + padding).decode()
