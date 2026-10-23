"""Anonymous identity: each browser holds a random key instead of an account.

Flow:
1. On first visit the app calls POST /api/identity. The server generates a random
   key, stores only its SHA-256 hash, and returns the key once.
2. The app keeps the key in localStorage and sends it as
   "Authorization: Bearer <key>".
3. Each request hashes the key it receives and looks up the client by that hash.
   A leaked database therefore exposes no usable keys.
"""

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .errors import ApiError
from .models import Client

_bearer = HTTPBearer(auto_error=False)


def new_key() -> str:
    """32 random bytes, URL-safe base64 encoded (43 characters)."""
    return secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _lookup(db: Session, credentials: HTTPAuthorizationCredentials | None) -> Client | None:
    if credentials is None:
        return None
    client = db.scalar(select(Client).where(Client.token_hash == hash_key(credentials.credentials)))
    if client is not None:
        client.last_seen_at = datetime.now(UTC)
        db.commit()
    return client


def optional_client(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Client | None:
    """The calling client if a valid key was sent, otherwise None (e.g. for scanning)."""
    return _lookup(db, credentials)


def require_client(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Client:
    """The calling client; responds 401 if the key is missing or unknown."""
    client = _lookup(db, credentials)
    if client is None:
        raise ApiError(401, "invalid_key", "Missing or unknown key")
    return client
