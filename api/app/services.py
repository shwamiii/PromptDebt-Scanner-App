"""Logic shared by several routes: running scans and building responses."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import debt, review
from .github import GitHub
from .models import Artefact, Client, FindingTriage, Scan, WatchlistItem
from .scanner import findings_for, scan_repository
from .schemas import (
    ArtefactOut,
    DebtOut,
    FindingOut,
    ReportOut,
    ScanSummary,
    TriageOut,
    WatchlistOut,
)


def run_scan(db: Session, github: GitHub, full_name: str) -> Scan:
    """Scan a repo on GitHub and save the result."""
    result = scan_repository(github, full_name)
    scan = Scan(
        repo_full_name=result.repo_full_name,
        default_branch=result.default_branch,
        head_sha=result.head_sha,
        last_commit_at=result.last_commit_at,
        stars=result.stars,
        archived=result.archived,
        artefacts=[Artefact(**vars(a)) for a in result.artefacts],
    )
    db.add(scan)
    db.commit()
    return scan


def repo_debt(scan: Scan) -> DebtOut | None:
    """The repo's Prompt Debt Score with the points behind it (None without artefacts).

    Conflicting rules come from the scan's AI review; without one they're left out,
    the score is scaled from 65 to 100, and ``conflicts_checked`` is False.
    """
    conflicts = len(scan.review.conflicts) if scan.review else None
    total = debt.score(scan.artefacts, conflicts)
    if total is None:
        return None
    points = debt.points(scan.artefacts, conflicts)
    return DebtOut(
        score=total,
        band=debt.band(total),
        points={name: round(value, 1) for name, value in points.items()},
        conflicts_checked=conflicts is not None,
    )


def latest_scan(db: Session, repo_full_name: str) -> Scan | None:
    return db.scalar(
        select(Scan)
        .where(Scan.repo_full_name == repo_full_name)
        .order_by(Scan.scanned_at.desc())
        .limit(1)
    )


def triage_by_key(db: Session, client: Client, repo_full_name: str) -> dict[str, FindingTriage]:
    rows = db.scalars(
        select(FindingTriage).where(
            FindingTriage.client_id == client.id,
            FindingTriage.repo_full_name == repo_full_name,
        )
    )
    return {t.finding_key: t for t in rows}


def build_report(db: Session, scan: Scan, client: Client | None) -> ReportOut:
    """Full report. With a client, each finding includes that client's triage status."""
    triage = triage_by_key(db, client, scan.repo_full_name) if client else {}
    watch_id = None
    if client:
        watch_id = db.scalar(
            select(WatchlistItem.id).where(
                WatchlistItem.client_id == client.id,
                WatchlistItem.repo_full_name == scan.repo_full_name,
            )
        )

    findings = []
    for f in findings_for(scan.artefacts):
        row = triage.get(f.key)
        findings.append(
            FindingOut(**vars(f), triage=TriageOut.model_validate(row) if row else None)
        )

    return ReportOut(
        id=scan.id,
        repo_full_name=scan.repo_full_name,
        default_branch=scan.default_branch,
        head_sha=scan.head_sha,
        last_commit_at=scan.last_commit_at,
        stars=scan.stars,
        archived=scan.archived,
        scanned_at=scan.scanned_at,
        debt=repo_debt(scan),
        tools=sorted({a.tool for a in scan.artefacts}),
        artefacts=[ArtefactOut.model_validate(a, from_attributes=True) for a in scan.artefacts],
        findings=findings,
        watchlist_item_id=watch_id,
        review=scan.review,
        review_available=review.available() and bool(scan.artefacts),
    )


def summarise(db: Session, item: WatchlistItem) -> WatchlistOut:
    """Watchlist entry with a one-line summary of its latest scan."""
    latest = None
    scan = item.last_scan
    if scan is not None:
        triage = triage_by_key(db, item.client, item.repo_full_name)
        open_count = sum(
            1
            for f in findings_for(scan.artefacts)
            if f.key not in triage or triage[f.key].status == "open"
        )
        repo_score = repo_debt(scan)
        latest = ScanSummary(
            scan_id=scan.id,
            scanned_at=scan.scanned_at,
            artefact_count=len(scan.artefacts),
            debt_score=repo_score.score if repo_score else None,
            debt_band=repo_score.band if repo_score else None,
            open_findings=open_count,
        )
    return WatchlistOut(
        id=item.id,
        repo_full_name=item.repo_full_name,
        label=item.label,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
        latest=latest,
    )
