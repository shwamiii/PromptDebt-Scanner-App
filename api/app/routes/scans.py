from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config, review
from ..auth import optional_client
from ..config import REVIEW_RATE_LIMIT, SCAN_RATE_LIMIT
from ..db import get_db
from ..errors import ApiError, not_found
from ..github import GitHub, get_github
from ..models import AiReview, Client, Scan
from ..ratelimit import RateLimiter
from ..scanner import parse_repo_url
from ..schemas import ReportOut, ReviewOut, ScanIn
from ..services import build_report, run_scan

router = APIRouter(prefix="/api/scans", tags=["scans"])
limit_scans = RateLimiter(SCAN_RATE_LIMIT, "scans")
limit_reviews = RateLimiter(REVIEW_RATE_LIMIT, "AI reviews")


@router.post("", response_model=ReportOut, dependencies=[Depends(limit_scans)])
def create_scan(
    body: ScanIn,
    db: Session = Depends(get_db),
    github: GitHub = Depends(get_github),
    client: Client | None = Depends(optional_client),
):
    """Scan a public GitHub repo. Works without a key; with one, includes triage."""
    scan = run_scan(db, github, parse_repo_url(body.url))
    return build_report(db, scan, client)


@router.get("/{scan_id}", response_model=ReportOut)
def get_scan(
    scan_id: str,
    db: Session = Depends(get_db),
    client: Client | None = Depends(optional_client),
):
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise not_found("Scan")
    return build_report(db, scan, client)


@router.post("/{scan_id}/review", response_model=ReviewOut)
def create_review(
    scan_id: str,
    request: Request,
    db: Session = Depends(get_db),
    github: GitHub = Depends(get_github),
):
    """Run the advisory AI review for a scan, or return the one already saved.

    Rate limited only when a new review actually calls the model.
    """
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise not_found("Scan")
    if scan.review is not None:
        return scan.review
    if not review.available():
        raise ApiError(503, "review_unavailable", "AI review isn't set up on this server.")
    if not scan.artefacts:
        raise ApiError(422, "nothing_to_review", "This repo has no artefacts to review.")

    limit_reviews(request)
    overview, conflicts = review.run_review(github, scan)
    saved = AiReview(
        scan_id=scan.id,
        overview=overview,
        conflicts=conflicts,
        model=config.LLM_MODEL,
        provider=review.provider_host(),
        prompt_version=review.PROMPT_VERSION,
    )
    db.add(saved)
    try:
        db.commit()
    except IntegrityError:
        # Another request (e.g. a second open tab) saved a review for this scan first.
        db.rollback()
        return db.scalar(select(AiReview).where(AiReview.scan_id == scan.id))
    return saved
