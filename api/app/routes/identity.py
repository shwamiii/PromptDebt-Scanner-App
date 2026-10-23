from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import hash_key, new_key, require_client
from ..config import IDENTITY_RATE_LIMIT
from ..db import get_db
from ..models import Client
from ..ratelimit import RateLimiter
from ..schemas import IdentityOut, MeOut

router = APIRouter(prefix="/api/identity", tags=["identity"])
limit_identity = RateLimiter(IDENTITY_RATE_LIMIT, "new keys")


@router.post(
    "", status_code=201, response_model=IdentityOut, dependencies=[Depends(limit_identity)]
)
def create_identity(db: Session = Depends(get_db)):
    """Create an anonymous client. The key is returned once and never stored."""
    key = new_key()
    db.add(Client(token_hash=hash_key(key)))
    db.commit()
    return IdentityOut(key=key)


@router.get("/me", response_model=MeOut)
def me(client: Client = Depends(require_client)):
    """Check that a key is valid (used before switching to a pasted key)."""
    return MeOut(created_at=client.created_at)


@router.delete("", status_code=204)
def delete_identity(client: Client = Depends(require_client), db: Session = Depends(get_db)):
    """Delete the client and all of its watchlist and triage data."""
    db.delete(client)
    db.commit()
