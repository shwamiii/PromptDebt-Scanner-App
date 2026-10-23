"""The scan: which prompt artefacts a repo has, and how much prompt debt they carry.

Measuring against the repo's newest commit rather than today's date means an
inactive repo isn't penalized: if nobody has touched the code either, the
artefact isntt behind it.
"""

import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from . import analysis, debt
from .errors import ApiError
from .github import GitHub, parse_date

# (filename, folder, tool). Folder "" means the repository root.
ARTEFACTS = [
    (".cursorrules", "", "Cursor"),
    ("copilot-instructions.md", ".github", "GitHub Copilot"),
    ("CLAUDE.md", "", "Claude Code"),
    ("AGENTS.md", "", "Codex and other agents"),
    ("Plan.md", "", "Planning file"),
]

# A repo too big to list in one request is listed per top-level folder, up to this many.
MAX_SUBTREES = 40

# Status bands on days_behind (inclusive upper bounds).
FRESH_MAX_DAYS = 30
AGEING_MAX_DAYS = 90

_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def parse_repo_url(url: str) -> str:
    """Turn a GitHub URL into "owner/repo", or raise ApiError with a specific message.

    Accepts https/http, optional "www.", no scheme at all, a ".git" suffix, a
    trailing slash, and extra path parts such as "/tree/main/src".
    """
    text = url.strip()
    if not text:
        raise ApiError(400, "invalid_url", "Enter a GitHub repository URL")
    if "://" not in text:
        text = "https://" + text

    parts = urlsplit(text)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.scheme not in ("http", "https") or host != "github.com":
        raise ApiError(400, "invalid_url", "That's not a GitHub URL")

    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        raise ApiError(400, "invalid_url", "Include the owner and repository name")

    owner, repo = segments[0], segments[1].removesuffix(".git")
    if not _OWNER.match(owner) or not _REPO.match(repo) or repo in (".", ".."):
        raise ApiError(400, "invalid_url", "That isn't a valid GitHub repository URL")
    return f"{owner}/{repo}"


def status_for(days_behind: int | None) -> str:
    """fresh (<= 30 days), ageing (31-90), stale (> 90), unknown (no date)."""
    if days_behind is None:
        return "unknown"
    if days_behind <= FRESH_MAX_DAYS:
        return "fresh"
    if days_behind <= AGEING_MAX_DAYS:
        return "ageing"
    return "stale"


def mentions(text: str, filename: str) -> bool:
    """True if ``text`` mentions ``filename`` as a whole name, ignoring case."""
    pattern = rf"(?<![\w-]){re.escape(filename)}(?![\w-])"
    return re.search(pattern, text, re.IGNORECASE) is not None


@dataclass
class ArtefactResult:
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
    # None when the repo is too large to list every path, so references weren't checked.
    # [{"path", "line", "reason", "found_at"}]; see analysis.broken_references.
    broken_refs: list[dict] | None
    duplicate_rules: list[dict]
    # Other artefact paths that are symlinks to this file (e.g. CLAUDE.md -> AGENTS.md).
    aliases: list[str]


@dataclass
class ScanResult:
    repo_full_name: str
    default_branch: str
    head_sha: str
    last_commit_at: datetime
    stars: int
    archived: bool
    artefacts: list[ArtefactResult]


def _find_file(paths: list[str], filename: str) -> str | None:
    """Real path of ``filename`` among ``paths``, matched case-insensitively."""
    for path in sorted(paths):
        if path.rsplit("/", 1)[-1].lower() == filename.lower():
            return path
    return None


def _commit_date(commit: dict) -> datetime:
    return parse_date(commit["commit"]["committer"]["date"])


def _list_repo(github: GitHub, full_name: str, sha: str) -> tuple[list[dict], bool]:
    """Every file and folder entry in the repo, and whether the list is complete.

    GitHub cuts the one-request recursive list off for very large repos (around
    100,000 entries). Then the list is rebuilt one top-level folder at a time, since
    each folder's own list is usually complete. A repo with more than MAX_SUBTREES
    top-level folders is too costly to rebuild: only the root and .github/ are listed,
    which is still enough to find the artefacts.
    """
    entries, truncated = github.tree(full_name, sha)
    if not truncated:
        return entries, True

    root, _ = github.tree(full_name, sha, recursive=False)
    subtrees = [e for e in root if e["type"] == "tree"]
    complete = len(subtrees) <= MAX_SUBTREES
    if not complete:
        subtrees = [e for e in subtrees if e["path"] == ".github"]
    entries = list(root)
    for folder in subtrees:
        inner, inner_truncated = github.tree(full_name, folder["sha"])
        complete = complete and not inner_truncated
        entries += [{**e, "path": f"{folder['path']}/{e['path']}"} for e in inner]
    return entries, complete


def _repo_paths(github: GitHub, full_name: str, sha: str):
    """Every file and folder in the repo, the files in the root and in .github/, and
    the symlinks ({path: object sha}). Files and folders are None if the repo couldn't
    be listed in full, meaning references can't be checked.
    """
    entries, complete = _list_repo(github, full_name, sha)
    # Git stores symbolic links with file mode 120000.
    symlinks = {e["path"]: e["sha"] for e in entries if e.get("mode") == "120000"}
    files = {e["path"] for e in entries if e["type"] == "blob"}
    folders = {e["path"] for e in entries if e["type"] == "tree"}
    by_folder = {
        "": [f for f in files if "/" not in f],
        ".github": [f for f in files if f.startswith(".github/") and f.count("/") == 1],
    }
    if not complete:
        return None, None, by_folder, symlinks
    return files, folders, by_folder, symlinks


def _fold_symlinks(github, full_name, found, symlinks) -> dict[str, list[str]]:
    """Remove artefacts that are symlinks to another artefact, returning {target: [links]}.

    Repos often make CLAUDE.md a link to AGENTS.md so one file serves two tools. That
    is one artefact, not a duplicate, so the link is reported as an alias of its target
    instead of being scored on its own. A link's content is its target path.
    """
    paths = {path for path, *_ in found}
    aliases: dict[str, list[str]] = {}
    for entry in list(found):
        path, folder = entry[0], entry[1]
        if path not in symlinks:
            continue
        target = posixpath.normpath(
            posixpath.join(folder, github.blob_text(full_name, symlinks[path]).strip())
        )
        if target in paths and target != path:
            aliases.setdefault(target, []).append(path)
            found.remove(entry)
    return aliases


def _measure(github, full_name, branch, last_commit_at, path, folder, text, files, folders):
    """Commit-history and content measurements for one artefact."""
    history = github.commits(full_name, branch, path=path)
    changed_at = _commit_date(history[0]) if history else None
    days_behind = max(0, (last_commit_at - changed_at).days) if changed_at else None
    commits_since = None
    if changed_at:
        # One second later, so the commit that changed the artefact isn't counted.
        later = github.commits(full_name, branch, since=changed_at + timedelta(seconds=1))
        commits_since = len(later)

    broken = None
    if files is not None:
        refs = analysis.path_references(text)
        broken = analysis.broken_references(refs, files, folders, folder)

    return {
        "last_changed_at": changed_at,
        "days_behind": days_behind,
        "status": status_for(days_behind),
        "commits_since_update": commits_since,
        "change_count": len(history),
        "line_count": analysis.line_count(text),
        "approx_tokens": analysis.approx_tokens(text),
        "broken_refs": broken,
    }


def scan_repository(github: GitHub, full_name: str) -> ScanResult:
    repo = github.repo(full_name)
    full_name, branch = repo["full_name"], repo["default_branch"]

    newest = github.commits(full_name, branch, limit=1)
    if not newest:
        raise ApiError(422, "empty_repository", "This repository has no commits yet.")
    head_sha, last_commit_at = newest[0]["sha"], _commit_date(newest[0])

    files, folders, by_folder, symlinks = _repo_paths(github, full_name, head_sha)
    readme = github.readme(full_name)

    found = []
    for filename, folder, tool in ARTEFACTS:
        path = _find_file(by_folder[folder], filename)
        if path:
            found.append((path, folder, filename, tool))
    aliases = _fold_symlinks(github, full_name, found, symlinks)
    texts = {path: github.file_text(full_name, path, head_sha) for path, *_ in found}
    duplicates = analysis.duplicated_rules(texts)

    artefacts = []
    for path, folder, filename, tool in found:
        # Copilot's file is usually referred to by its folder-free name.
        term = "copilot-instructions" if folder == ".github" else filename
        measured = _measure(
            github, full_name, branch, last_commit_at, path, folder, texts[path], files, folders
        )
        artefacts.append(
            ArtefactResult(
                path=path,
                tool=tool,
                documented=mentions(readme, term),
                duplicate_rules=duplicates[path],
                aliases=aliases.get(path, []),
                **measured,
            )
        )

    return ScanResult(
        repo_full_name=full_name,
        default_branch=branch,
        head_sha=head_sha,
        last_commit_at=last_commit_at,
        stars=repo.get("stargazers_count", 0),
        archived=repo.get("archived", False),
        artefacts=artefacts,
    )


@dataclass
class Finding:
    key: str
    type: str
    path: str
    summary: str


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _findings_for_one(a) -> list[Finding]:
    found = []

    def add(kind: str, summary: str) -> None:
        found.append(Finding(f"{kind}:{a.path}", kind, a.path, summary))

    if a.broken_refs:
        listed = ", ".join(f"{r['path']} (line {r['line']})" for r in a.broken_refs[:3])
        if len(a.broken_refs) > 3:
            listed += " and more"
        count = _plural(len(a.broken_refs), "path")
        add("broken_refs", f"{a.path} mentions {count} that no longer exist: {listed}.")
    if a.status == "stale":
        add("stale", f"{a.path} is {a.days_behind} days behind the latest commit.")
    if a.duplicate_rules:
        others = ", ".join(sorted({d["other_path"] for d in a.duplicate_rules}))
        count = _plural(len(a.duplicate_rules), "rule")
        add("duplicated", f"{a.path} repeats {count} also found in {others}.")
    if not a.documented:
        add("undocumented", f"{a.path} isn't mentioned in the README.")
    if a.approx_tokens >= debt.OVERSIZED_TOKENS:
        add("oversized", f"{a.path} is about {a.approx_tokens:,} tokens long.")
    return found


def findings_for(artefacts) -> list[Finding]:
    """Problems worth triaging: broken_refs, stale, duplicated, undocumented, oversized.
    """
    return [f for a in artefacts for f in _findings_for_one(a)]
