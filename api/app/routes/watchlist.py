"""Watchlist CRUD. Every query is filtered by the caller's client id, so another
client's item id behaves exactly like one that doesn't exist (404)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import require_client
from ..db import get_db
from ..errors import ApiError, not_found
from ..github import GitHub, get_github
from ..models import Client, FindingTriage, Scan, WatchlistItem
from ..scanner import parse_repo_url
from ..schemas import WatchlistIn, WatchlistOut, WatchlistUpdate
from ..services import run_scan, summarise
from .scans import limit_scans

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _owned(db: Session, client: Client, item_id: str) -> WatchlistItem:
    item = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.id == item_id, WatchlistItem.client_id == client.id
        )
    )
    if item is None:
        raise not_found("Watchlist item")
    return item


@router.get("", response_model=list[WatchlistOut])
def list_items(client: Client = Depends(require_client), db: Session = Depends(get_db)):
    items = db.scalars(
        select(WatchlistItem)
        .where(WatchlistItem.client_id == client.id)
        .order_by(WatchlistItem.created_at.desc())
    )
    return [summarise(db, item) for item in items]


@router.post("", status_code=201, response_model=WatchlistOut)
def add_item(
    body: WatchlistIn,
    request: Request,
    client: Client = Depends(require_client),
    db: Session = Depends(get_db),
    github: GitHub = Depends(get_github),
):
    """Add a repo to the watchlist.

    From a report, the app sends that report's ``scan_id``: the repo was just scanned,
    so the item is linked to that scan and GitHub isn't called again. Otherwise a URL
    is scanned now, which also confirms the repo exists and is public.
    """
    if body.scan_id:
        scan = db.get(Scan, body.scan_id)
        if scan is None:
            raise not_found("Scan")
    else:
        limit_scans(request)
        scan = run_scan(db, github, parse_repo_url(body.url))

    exists = db.scalar(
        select(WatchlistItem.id).where(
            WatchlistItem.client_id == client.id,
            WatchlistItem.repo_full_name == scan.repo_full_name,
        )
    )
    if exists:
        raise ApiError(
            409, "already_watched", f"{scan.repo_full_name} is already on your watchlist"
        )

    item = WatchlistItem(
        client_id=client.id,
        repo_full_name=scan.repo_full_name,
        label=body.label.strip(),
        last_scan=scan,
    )
    db.add(item)
    db.commit()
    return summarise(db, item)


@router.get("/{item_id}", response_model=WatchlistOut)
def get_item(item_id: str, client: Client = Depends(require_client), db: Session = Depends(get_db)):
    return summarise(db, _owned(db, client, item_id))


@router.patch("/{item_id}", response_model=WatchlistOut)
def update_item(
    item_id: str,
    body: WatchlistUpdate,
    client: Client = Depends(require_client),
    db: Session = Depends(get_db),
):
    item = _owned(db, client, item_id)
    if body.label is not None:
        item.label = body.label.strip()
    if body.notes is not None:
        item.notes = body.notes
    db.commit()
    return summarise(db, item)


@router.delete("/{item_id}", status_code=204)
def delete_item(
    item_id: str, client: Client = Depends(require_client), db: Session = Depends(get_db)
):
    """Remove a repo from the watchlist, along with the caller's triage for it."""
    item = _owned(db, client, item_id)
    db.execute(
        delete(FindingTriage).where(
            FindingTriage.client_id == client.id,
            FindingTriage.repo_full_name == item.repo_full_name,
        )
    )
    db.delete(item)
    db.commit()


@router.post("/{item_id}/rescan", response_model=WatchlistOut, dependencies=[Depends(limit_scans)])
def rescan_item(
    item_id: str,
    client: Client = Depends(require_client),
    db: Session = Depends(get_db),
    github: GitHub = Depends(get_github),
):
    item = _owned(db, client, item_id)
    item.last_scan = run_scan(db, github, item.repo_full_name)
    db.commit()
    return summarise(db, item)
