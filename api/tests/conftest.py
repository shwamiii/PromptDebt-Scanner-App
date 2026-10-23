import os

os.environ["DATABASE_URL"] = "sqlite://"
for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
    os.environ[name] = ""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app
from app.routes.identity import limit_identity
from app.routes.scans import limit_reviews, limit_scans

GITHUB = "https://api.github.com/repos/acme/widgets"
REPO_URL = "https://github.com/acme/widgets"

CLAUDE_MD = """# Project notes

- Use pnpm for installing all dependencies.
- Entry point is `src/app.py`; helper scripts live in `scripts/old.sh`.
- Write docs in docs/ as you go.
"""
COPILOT_MD = """- Use pnpm for installing all dependencies!
- Keep versions pinned in `package.json` always.
"""

TREE = [
    {"path": "README.md", "type": "blob"},
    {"path": "CLAUDE.md", "type": "blob"},
    {"path": ".github", "type": "tree"},
    {"path": ".github/copilot-instructions.md", "type": "blob"},
    {"path": "src", "type": "tree"},
    {"path": "src/app.py", "type": "blob"},
]


def commit(sha: str, date: str) -> dict:
    return {"sha": sha, "commit": {"committer": {"date": date}}}


HISTORY = {
    None: [commit("head123", "2026-10-01T12:00:00Z")],
    "CLAUDE.md": [commit("c2", "2026-09-21T12:00:00Z"), commit("c1", "2026-08-01T12:00:00Z")],
    ".github/copilot-instructions.md": [commit("p1", "2026-05-01T12:00:00Z")],
}
SINCE = {"2026-09-21T12:00:01Z": 5, "2026-05-01T12:00:01Z": 40}


def _commits(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    if "since" in params:
        count = SINCE[params["since"]]
        return httpx.Response(200, json=[commit("s", "2026-09-30T00:00:00Z")] * count)
    return httpx.Response(200, json=HISTORY[params.get("path")])


@pytest.fixture(autouse=True)
def fresh_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    limit_scans.hits.clear()
    limit_identity.hits.clear()
    limit_reviews.hits.clear()


@pytest.fixture
def github():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(GITHUB).respond(
            json={
                "full_name": "acme/widgets",
                "default_branch": "main",
                "stargazers_count": 7,
                "archived": False,
            }
        )
        mock.get(f"{GITHUB}/commits").mock(side_effect=_commits)
        mock.get(f"{GITHUB}/git/trees/head123").respond(json={"tree": TREE, "truncated": False})
        mock.get(f"{GITHUB}/contents/CLAUDE.md").respond(text=CLAUDE_MD)
        mock.get(f"{GITHUB}/contents/.github/copilot-instructions.md").respond(text=COPILOT_MD)
        mock.get(f"{GITHUB}/readme").respond(text="# Widgets\nAgent notes live in CLAUDE.md.\n")
        yield mock


@pytest.fixture
def api() -> TestClient:
    return TestClient(app)


def new_key(api: TestClient) -> dict[str, str]:
    key = api.post("/api/identity").json()["key"]
    return {"Authorization": f"Bearer {key}"}
