"""Request and response bodies. Pydantic validates every incoming field."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TriageStatus = Literal["open", "acknowledged", "fixed", "ignored"]
REPO_NAME = r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$"


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Identity


class IdentityOut(BaseModel):
    key: str


class MeOut(BaseModel):
    created_at: datetime


# Scans


class ScanIn(BaseModel):
    url: str = Field(max_length=300)


class BrokenRef(BaseModel):
    path: str
    line: int
    reason: str
    # Where a file or folder with the same name exists (it was probably moved).
    found_at: list[str]


class DuplicateRule(BaseModel):
    text: str
    other_path: str


class DebtOut(BaseModel):
    score: int
    band: str
    # Points each component contributed, e.g. {"drift": 12.5, ...}; see debt.py.
    points: dict[str, float]
    # False until the AI review has run. Then conflicting rules are left out and the
    # other points (out of 65) are scaled up to 100.
    conflicts_checked: bool


class ArtefactOut(BaseModel):
    path: str
    tool: str
    last_changed_at: datetime | None
    days_behind: int | None
    status: str
    documented: bool
    commits_since_update: int | None
    change_count: int
    line_count: int
    approx_tokens: int
    broken_refs: list[BrokenRef] | None
    duplicate_rules: list[DuplicateRule]
    aliases: list[str]


class TriageOut(Orm):
    id: str
    repo_full_name: str
    finding_key: str
    status: TriageStatus
    note: str
    updated_at: datetime
    # Only filled in on the triage list: is the finding in the repo's latest scan?
    still_detected: bool | None = None


class FindingOut(BaseModel):
    key: str
    type: str
    path: str
    summary: str
    triage: TriageOut | None


class ConflictOut(BaseModel):
    path_a: str
    quote_a: str
    path_b: str
    quote_b: str
    explanation: str


class ReviewOut(Orm):
    overview: list[str]
    conflicts: list[ConflictOut]
    model: str
    provider: str
    prompt_version: str
    created_at: datetime


class ReportOut(BaseModel):
    id: str
    repo_full_name: str
    default_branch: str
    head_sha: str
    last_commit_at: datetime
    stars: int
    archived: bool
    scanned_at: datetime
    # The repo's Prompt Debt Score; None when it has no artefacts.
    debt: DebtOut | None
    # Distinct tools with instruction files. Two or more means fragmentation.
    tools: list[str]
    artefacts: list[ArtefactOut]
    findings: list[FindingOut]
    watchlist_item_id: str | None
    # The advisory AI review, if one has been run, and whether one can be.
    review: ReviewOut | None
    review_available: bool


# Watchlist


class WatchlistIn(BaseModel):
    """Add a repo either by URL (scans it) or by an existing scan's id (no new scan)."""

    url: str | None = Field(None, max_length=300)
    scan_id: str | None = Field(None, max_length=36)
    label: str = Field("", max_length=100)

    @model_validator(mode="after")
    def url_or_scan(self) -> "WatchlistIn":
        if not self.url and not self.scan_id:
            raise ValueError("Provide a repository URL or a scan id")
        return self


class WatchlistUpdate(BaseModel):
    label: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=2000)


class ScanSummary(BaseModel):
    scan_id: str
    scanned_at: datetime
    artefact_count: int
    debt_score: int | None
    debt_band: str | None
    open_findings: int


class WatchlistOut(BaseModel):
    id: str
    repo_full_name: str
    label: str
    notes: str
    created_at: datetime
    updated_at: datetime
    latest: ScanSummary | None


# Triage


class TriageIn(BaseModel):
    repo_full_name: str = Field(pattern=REPO_NAME)
    finding_key: str = Field(min_length=1, max_length=300)
    status: TriageStatus
    note: str = Field("", max_length=2000)


class TriageUpdate(BaseModel):
    status: TriageStatus | None = None
    note: str | None = Field(None, max_length=2000)
