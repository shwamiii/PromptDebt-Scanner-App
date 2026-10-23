"""Minimal client for the public GitHub REST API.

The server's GITHUB_TOKEN is attached to requests here and nowhere else. It is never
logged, returned to the browser, or included in error messages.
"""

from datetime import UTC, datetime

import httpx

from .config import GITHUB_TOKEN
from .errors import ApiError

API_URL = "https://api.github.com"
TIMEOUT_SECONDS = 10
# GitHub's maximum page size. Commit counts are capped here (shown as "100+").
COMMIT_PAGE_SIZE = 100


def parse_date(value: str) -> datetime:
    """GitHub timestamps look like 2026-05-01T12:00:00Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHub:
    def __init__(self, token: str | None = GITHUB_TOKEN) -> None:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "promptdebt-scanner"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # Renamed or transferred repos answer with a redirect to their new location.
        self._http = httpx.Client(
            base_url=API_URL, headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=True
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict | None = None, accept: str | None = None):
        """GET a GitHub endpoint, turning failures into ApiErrors with clear messages."""
        headers = {"Accept": accept} if accept else None
        try:
            response = self._http.get(path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise ApiError(504, "github_timeout", "GitHub took too long to respond.") from exc
        except httpx.TransportError as exc:
            raise ApiError(502, "github_unavailable", "Could not reach GitHub.") from exc

        status = response.status_code
        if status in (403, 429) and response.headers.get("x-ratelimit-remaining") == "0":
            reset = datetime.fromtimestamp(int(response.headers["x-ratelimit-reset"]), UTC)
            raise ApiError(
                429,
                "github_rate_limited",
                f"GitHub's rate limit was reached. Try again after {reset:%H:%M} UTC.",
            )
        if status == 404:
            raise ApiError(404, "not_found", "Not found on GitHub")
        if status == 409:
            raise ApiError(422, "empty_repository", "This repository has no commits yet.")
        if status >= 500:
            raise ApiError(502, "github_unavailable", "GitHub is having problems. Try again.")
        if status >= 400:
            raise ApiError(502, "github_error", f"GitHub refused the request ({status}).")
        return response

    def repo(self, full_name: str) -> dict:
        try:
            return self._get(f"/repos/{full_name}").json()
        except ApiError as exc:
            if exc.status_code == 404:
                raise ApiError(404, "repo_not_found", "Repository not found or private") from exc
            raise

    def commits(
        self,
        full_name: str,
        branch: str,
        *,
        path: str | None = None,
        since: datetime | None = None,
        limit: int = COMMIT_PAGE_SIZE,
    ) -> list[dict]:
        """Newest commits on ``branch``, at most ``limit`` (one page, max 100).

        Optionally only commits touching ``path``, and/or made after ``since``.
        """
        params = {"sha": branch, "per_page": limit}
        if path:
            params["path"] = path
        if since:
            params["since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        return self._get(f"/repos/{full_name}/commits", params=params).json()

    def tree(self, full_name: str, sha: str, recursive: bool = True) -> tuple[list[dict], bool]:
        """Entries of a git tree (a commit or a folder), plus GitHub's "truncated" flag.

        Recursive lists every file and folder beneath it. GitHub cuts that list off for
        very large trees (around 100,000 entries) and sets "truncated".
        """
        params = {"recursive": "1"} if recursive else None
        data = self._get(f"/repos/{full_name}/git/trees/{sha}", params=params).json()
        return data["tree"], data.get("truncated", False)

    def blob_text(self, full_name: str, sha: str) -> str:
        """Raw content of a git object by its SHA. For a symlink this is the target path."""
        response = self._get(
            f"/repos/{full_name}/git/blobs/{sha}", accept="application/vnd.github.raw+json"
        )
        return response.content.decode("utf-8", errors="replace")

    def file_text(self, full_name: str, path: str, ref: str) -> str:
        """Contents of one file as text."""
        response = self._get(
            f"/repos/{full_name}/contents/{path}",
            params={"ref": ref},
            accept="application/vnd.github.raw+json",
        )
        return response.content.decode("utf-8", errors="replace")

    def readme(self, full_name: str) -> str:
        """Text of the repo's README (GitHub finds it in any case or extension)."""
        try:
            response = self._get(
                f"/repos/{full_name}/readme", accept="application/vnd.github.raw+json"
            )
        except ApiError as exc:
            if exc.status_code == 404:
                return ""
            raise
        return response.text


def get_github():
    """FastAPI dependency: a GitHub client that is closed after the request."""
    github = GitHub()
    try:
        yield github
    finally:
        github.close()
