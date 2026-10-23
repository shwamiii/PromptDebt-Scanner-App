"""The AI review: conflicting rules and a short "what's most wrong" overview.

The number of conflicts found counts towards the Prompt Debt Score (see debt.py);
without a review, the score is scaled from the other components. The review creates
no triage findings. It runs once per scan, when the report is first opened, and the
result is saved with that scan.

"""

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import config
from .errors import ApiError
from .github import GitHub
from .models import Scan

PROMPT_VERSION = "review-v2"
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "review_v2.md").read_text(encoding="utf-8")

# Limits on what is sent. About 4 characters per token, so the files stay under ~4,500
# tokens: with the prompt that fits free tiers like Groq's 8,000 tokens per minute.
MAX_FILE_CHARS = 12_000
MAX_TOTAL_CHARS = 18_000
# Limits on what is kept from the reply.
MAX_OVERVIEW_SENTENCES = 3
MAX_CONFLICTS = 10
MAX_TEXT_CHARS = 400
# A short provider rate limit ("try again in 17 seconds") is waited out once, up to this.
MAX_RETRY_WAIT_SECONDS = 20


class RetryableError(ApiError):
    """A review failure worth one automatic retry, after ``wait`` seconds."""

    def __init__(self, wait: float, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code, code, message)
        self.wait = wait


def available() -> bool:
    """True when the AI provider is configured."""
    return bool(config.LLM_BASE_URL and config.LLM_API_KEY and config.LLM_MODEL)


def provider_host() -> str:
    return urlsplit(config.LLM_BASE_URL).hostname or ""


def describe(scan: Scan) -> str:
    """The scanner's measurements in plain sentences, for the overview to build on.

    The Prompt Debt Score isn't included: it depends on this review's conflicts.
    """
    lines = []
    for a in scan.artefacts:
        behind = "unknown" if a.days_behind is None else f"{a.days_behind} days"
        since = "unknown" if a.commits_since_update is None else str(a.commits_since_update)
        broken = ", ".join(r["path"] for r in (a.broken_refs or [])[:10]) or "none"
        lines.append(
            f"- {a.path}: {behind} behind the latest commit (status: {a.status}); "
            f"{since} commits since it changed; "
            f"about {a.approx_tokens} tokens; "
            f"{'mentioned' if a.documented else 'not mentioned'} in the README; "
            f"paths that no longer exist: {broken}; "
            f"rules repeated in other files: {len(a.duplicate_rules)}."
        )
    return "\n".join(lines)


def build_messages(files: dict[str, str], facts: str) -> list[dict]:
    """System prompt plus one user message holding the measurements and the files.

    Each file is wrapped in <file path="..."> tags. A closing tag inside a file is
    defused so file text can't break out of its block.
    """
    blocks = []
    budget = MAX_TOTAL_CHARS
    for path, text in files.items():
        clipped = text[: max(min(MAX_FILE_CHARS, budget), 0)]
        budget -= len(clipped)
        truncated = ' truncated="true"' if len(clipped) < len(text) else ""
        safe = clipped.replace("</file>", "</ file>")
        blocks.append(f'<file path="{path}"{truncated}>\n{safe}\n</file>')
    user = "Scanner measurements:\n" + facts + "\n\nFiles:\n\n" + "\n\n".join(blocks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def call_model(messages: list[dict]) -> str:
    """Send the messages and return the reply text. Failures become ApiErrors.

    The API key is sent only in the Authorization header and never logged.
    """
    try:
        response = httpx.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            json={
                "model": config.LLM_MODEL,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise ApiError(504, "review_timeout", "The AI review took too long. Try again.") from exc
    except httpx.TransportError as exc:
        raise ApiError(502, "review_failed", "Couldn't reach the AI provider.") from exc

    if response.status_code == 429:
        raise _rate_limited(response)
    if response.status_code == 413:
        raise ApiError(
            413, "review_too_large", "These files are too large for the AI provider's limit."
        )
    # Groq rejects a reply that isn't valid JSON with a 400 "json_validate_failed".
    if response.status_code == 400 and "json_validate_failed" in response.text:
        raise _unusable()
    if response.status_code >= 400:
        raise ApiError(
            502, "review_failed", f"The AI provider returned an error ({response.status_code})."
        )
    try:
        return response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise _unusable() from exc


def _rate_limited(response: httpx.Response) -> ApiError:
    """Explain a provider rate limit: a daily allowance used up, or a short wait.

    Providers say how long to wait in a ``retry-after`` header (seconds); Groq's
    message also says whether the limit is per minute or per day.
    """
    if "per day" in response.text:
        return ApiError(
            429,
            "review_daily_limit",
            "The AI provider's free daily limit has been used up. Try again tomorrow.",
        )
    try:
        wait = max(1, round(float(response.headers.get("retry-after", "60"))))
    except ValueError:
        wait = 60
    return RetryableError(
        wait,
        429,
        "review_rate_limited",
        f"The AI provider's free-tier usage limit was reached. Try again in {wait} seconds.",
    )


def _unusable() -> ApiError:
    return RetryableError(
        0, 502, "review_invalid", "The AI returned an unusable answer. Try again."
    )


def _normal(text: str) -> str:
    """Lowercase with whitespace collapsed, for matching quotes against file text."""
    return " ".join(text.lower().split())


def _clean_text(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:MAX_TEXT_CHARS]


def _valid_conflict(item, files: dict[str, str]) -> dict | None:
    """The conflict, cleaned, if both quotes really are in the files named."""
    if not isinstance(item, dict):
        return None
    fields = {k: _clean_text(item.get(k)) for k in ("path_a", "quote_a", "path_b", "quote_b")}
    explanation = _clean_text(item.get("explanation"))
    if not all(fields.values()) or not explanation:
        return None
    for side in ("a", "b"):
        path, quote = fields[f"path_{side}"], fields[f"quote_{side}"]
        if path not in files or _normal(quote) not in _normal(files[path]):
            return None
    if _normal(fields["quote_a"]) == _normal(fields["quote_b"]):
        return None
    return {**fields, "explanation": explanation}


def parse_review(content: str, files: dict[str, str]) -> tuple[list[str], list[dict]]:
    """Validate the model's JSON reply. Returns (overview sentences, conflicts).

    Raises ApiError if the reply isn't JSON or has no usable overview. Conflicts with
    quotes that can't be found in the named files are dropped.
    """
    text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise _unusable() from exc
    if not isinstance(data, dict) or not isinstance(data.get("overview"), list):
        raise _unusable()

    overview = [s for s in map(_clean_text, data["overview"]) if s][:MAX_OVERVIEW_SENTENCES]
    if not overview:
        raise _unusable()

    raw_conflicts = data.get("conflicts")
    conflicts = []
    for item in raw_conflicts if isinstance(raw_conflicts, list) else []:
        valid = _valid_conflict(item, files)
        if valid and len(conflicts) < MAX_CONFLICTS:
            conflicts.append(valid)
    return overview, conflicts


def run_review(github: GitHub, scan: Scan) -> tuple[list[str], list[dict]]:
    """Fetch the scanned files, ask the model, and return the validated review.

    One automatic retry covers the common passing failures: an unusable answer, or a
    per-minute rate limit that clears within MAX_RETRY_WAIT_SECONDS. Anything else,
    or a second failure, is raised with its explanation.
    """
    files = {
        a.path: github.file_text(scan.repo_full_name, a.path, scan.head_sha) for a in scan.artefacts
    }
    messages = build_messages(files, describe(scan))
    try:
        return parse_review(call_model(messages), files)
    except RetryableError as exc:
        if exc.wait > MAX_RETRY_WAIT_SECONDS:
            raise
        time.sleep(exc.wait)
    return parse_review(call_model(messages), files)
