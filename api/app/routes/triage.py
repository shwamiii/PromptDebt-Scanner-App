"""Finding triage CRUD. Like the watchlist, every query is scoped to the caller.

Triage is part of keeping an eye on a repo, so findings can only be triaged for
repos on the caller's watchlist; removing a repo from the watchlist removes them.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_client
from ..db import get_db
from ..errors import ApiError, not_found
from ..models import Client, FindingTriage, WatchlistItem
from ..scanner import findings_for
from ..schemas import TriageIn, TriageOut, TriageStatus, TriageUpdate
from ..services import latest_scan

router = APIRouter(prefix="/api/triage", tags=["triage"])


def _owned(db: Session, client: Client, triage_id: str) -> FindingTriage:
    row = db.scalar(
        select(FindingTriage).where(
            FindingTriage.id == triage_id, FindingTriage.client_id == client.id
        )
    )
    if row is None:
        raise not_found("Triage entry")
    return row


@router.get("", response_model=list[TriageOut])
def list_triage(
    repo: str | None = None,
    status: TriageStatus | None = None,
    client: Client = Depends(require_client),
    db: Session = Depends(get_db),
):
    """All of the caller's triage entries, optionally filtered by repo and status.

    Each entry says whether its finding still appears in the repo's latest scan,
    so a finding marked "fixed" that is still detected can be flagged.
    """
    query = select(FindingTriage).where(FindingTriage.client_id == client.id)
    if repo:
        query = query.where(FindingTriage.repo_full_name == repo)
    if status:
        query = query.where(FindingTriage.status == status)
    rows = db.scalars(query.order_by(FindingTriage.updated_at.desc())).all()

    current_keys: dict[str, set[str]] = {}
    result = []
    for row in rows:
        if row.repo_full_name not in current_keys:
            scan = latest_scan(db, row.repo_full_name)
            keys = {f.key for f in findings_for(scan.artefacts)} if scan else set()
            current_keys[row.repo_full_name] = keys
        out = TriageOut.model_validate(row)
        out.still_detected = row.finding_key in current_keys[row.repo_full_name]
        result.append(out)
    return result


@router.post("", status_code=201, response_model=TriageOut)
def create_triage(
    body: TriageIn, client: Client = Depends(require_client), db: Session = Depends(get_db)
):
    watched = db.scalar(
        select(WatchlistItem.id).where(
            WatchlistItem.client_id == client.id,
            WatchlistItem.repo_full_name == body.repo_full_name,
        )
    )
    if not watched:
        raise ApiError(409, "not_watched", "Add this repo to your watchlist to triage its findings")
    exists = db.scalar(
        select(FindingTriage.id).where(
            FindingTriage.client_id == client.id,
            FindingTriage.repo_full_name == body.repo_full_name,
            FindingTriage.finding_key == body.finding_key,
        )
    )
    if exists:
        raise ApiError(409, "already_triaged", "This finding has already been triaged")
    row = FindingTriage(client_id=client.id, **body.model_dump())
    db.add(row)
    db.commit()
    return row


@router.get("/{triage_id}", response_model=TriageOut)
def get_triage(
    triage_id: str, client: Client = Depends(require_client), db: Session = Depends(get_db)
):
    return _owned(db, client, triage_id)


@router.patch("/{triage_id}", response_model=TriageOut)
def update_triage(
    triage_id: str,
    body: TriageUpdate,
    client: Client = Depends(require_client),
    db: Session = Depends(get_db),
):
    row = _owned(db, client, triage_id)
    if body.status is not None:
        row.status = body.status
    if body.note is not None:
        row.note = body.note
    db.commit()
    return row


@router.delete("/{triage_id}", status_code=204)
def delete_triage(
    triage_id: str, client: Client = Depends(require_client), db: Session = Depends(get_db)
):
    """Remove a triage entry; the finding goes back to being Open."""
    db.delete(_owned(db, client, triage_id))
    db.commit()
