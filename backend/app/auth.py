"""Minimal signed demo identities for the synthetic MVP.

This is intentionally small and local. It is not a production identity system;
the token boundary and server-side role checks are what the prototype needs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    role: str
    profile_id: str


@dataclass(frozen=True, slots=True)
class DemoIdentity:
    user_id: str
    role: str
    profile_id: str
    password: str


def _identities() -> dict[str, DemoIdentity]:
    return {
        "demo-user": DemoIdentity(
            user_id="demo-user",
            role="user",
            profile_id="profile-demo",
            password=os.getenv("MEDSI_DEMO_USER_PASSWORD", "demo-user"),
        ),
        "demo-caregiver": DemoIdentity(
            user_id="demo-caregiver",
            role="caregiver",
            profile_id="profile-demo",
            password=os.getenv("MEDSI_DEMO_CAREGIVER_PASSWORD", "demo-caregiver"),
        ),
    }


def _secret() -> bytes:
    return os.getenv("MEDSI_AUTH_SECRET", "synthetic-local-auth-secret").encode()


def _encode(value: dict[str, object]) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(_secret(), payload, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{payload.decode()}.{encoded_signature.decode()}"


def _decode(token: str) -> dict[str, object]:
    try:
        payload_part, signature_part = token.split(".", 1)
        payload = payload_part.encode()
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("invalid signature")
        data = json.loads(base64.urlsafe_b64decode(payload + b"=" * (-len(payload) % 4)))
        if int(data["exp"]) < int(time.time()):
            raise ValueError("expired token")
        return data
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc


def authenticate(user_id: str, password: str) -> UserContext | None:
    identity = _identities().get(user_id)
    if identity is None or not hmac.compare_digest(identity.password, password):
        return None
    return UserContext(identity.user_id, identity.role, identity.profile_id)


def issue_token(user: UserContext, *, ttl_seconds: int = 8 * 60 * 60) -> str:
    return _encode(
        {
            "sub": user.user_id,
            "role": user.role,
            "profile_id": user.profile_id,
            "exp": int(time.time()) + ttl_seconds,
        }
    )


def get_current_user(authorization: Annotated[str | None, Header()] = None) -> UserContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    data = _decode(authorization.split(" ", 1)[1].strip())
    return UserContext(str(data["sub"]), str(data["role"]), str(data["profile_id"]))


CurrentUser = Annotated[UserContext, Depends(get_current_user)]


def require_profile_access(profile_id: str, user: UserContext, *, write: bool = False) -> None:
    if profile_id != user.profile_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Profile access denied")
    if write and user.role != "user":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Caregiver access is read-only")
