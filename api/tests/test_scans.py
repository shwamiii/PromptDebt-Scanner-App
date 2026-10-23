import httpx

from .conftest import GITHUB, REPO_URL, new_key


def test_scan_report(api, github):
    response = api.post("/api/scans", json={"url": REPO_URL})
    assert response.status_code == 200
    report = response.json()

    assert report["repo_full_name"] == "acme/widgets"
    assert report["head_sha"] == "head123"
    by_path = {a["path"]: a for a in report["artefacts"]}
    assert by_path["CLAUDE.md"]["days_behind"] == 10
    assert by_path["CLAUDE.md"]["status"] == "fresh"
    assert by_path["CLAUDE.md"]["documented"] is True
    assert by_path[".github/copilot-instructions.md"]["days_behind"] == 153
    assert by_path[".github/copilot-instructions.md"]["status"] == "stale"

    claude, copilot = by_path["CLAUDE.md"], by_path[".github/copilot-instructions.md"]
    assert (claude["commits_since_update"], claude["change_count"]) == (5, 2)
    assert (copilot["commits_since_update"], copilot["change_count"]) == (40, 1)
    assert claude["broken_refs"] == [
        {
            "path": "scripts/old.sh",
            "line": 4,
            "reason": "Nothing at this path, and no file named old.sh anywhere in the repo.",
            "found_at": [],
        },
        {
            "path": "docs/",
            "line": 5,
            "reason": "No folder named docs anywhere in the repo.",
            "found_at": [],
        },
    ]
    assert [r["path"] for r in copilot["broken_refs"]] == ["package.json"]
    assert claude["duplicate_rules"] == [
        {"text": "- Use pnpm for installing all dependencies.", "other_path": copilot["path"]}
    ]
    assert claude["line_count"] == 5

    assert report["debt"] == {
        "score": 49,
        "band": "moderate",
        "points": {
            "conflicts": 0.0,
            "broken_refs": 15.0,
            "drift": 12.5,
            "duplication": 2.0,
            "undocumented": 2.5,
            "size": 0.0,
        },
        "conflicts_checked": False,
    }
    assert report["tools"] == ["Claude Code", "GitHub Copilot"]

    keys = sorted(f["key"] for f in report["findings"])
    assert keys == [
        "broken_refs:.github/copilot-instructions.md",
        "broken_refs:CLAUDE.md",
        "duplicated:.github/copilot-instructions.md",
        "duplicated:CLAUDE.md",
        "stale:.github/copilot-instructions.md",
        "undocumented:.github/copilot-instructions.md",
    ]
    assert all(f["triage"] is None for f in report["findings"])

    again = api.get(f"/api/scans/{report['id']}")
    assert again.json()["artefacts"] == report["artefacts"]


def test_scan_includes_callers_triage(api, github):
    auth = new_key(api)
    item = api.post("/api/watchlist", headers=auth, json={"url": REPO_URL}).json()
    api.post(
        "/api/triage",
        headers=auth,
        json={
            "repo_full_name": "acme/widgets",
            "finding_key": "stale:.github/copilot-instructions.md",
            "status": "acknowledged",
        },
    )
    report = api.post("/api/scans", json={"url": REPO_URL}, headers=auth).json()
    triaged = {f["key"]: f["triage"] for f in report["findings"]}
    assert triaged["stale:.github/copilot-instructions.md"]["status"] == "acknowledged"
    assert triaged["undocumented:.github/copilot-instructions.md"] is None
    assert report["watchlist_item_id"] == item["id"]


def test_repo_with_no_artefacts(api, github):
    github.get(f"{GITHUB}/git/trees/head123").respond(
        json={"tree": [{"path": "README.md", "type": "blob"}], "truncated": False}
    )
    report = api.post("/api/scans", json={"url": REPO_URL}).json()
    assert report["artefacts"] == []
    assert report["findings"] == []
    assert report["debt"] is None


def test_invalid_url_uses_error_shape(api):
    response = api.post("/api/scans", json={"url": "https://gitlab.com/a/b"})
    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_url", "message": "That's not a GitHub URL"}
    }


def test_private_or_missing_repo(api, github):
    github.get(GITHUB).respond(404)
    response = api.post("/api/scans", json={"url": REPO_URL})
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Repository not found or private"


def test_github_rate_limit_message(api, github):
    github.get(GITHUB).respond(
        403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"}
    )
    response = api.post("/api/scans", json={"url": REPO_URL})
    assert response.status_code == 429
    assert "Try again after" in response.json()["error"]["message"]


def test_github_timeout(api, github):
    github.get(GITHUB).mock(side_effect=httpx.ReadTimeout("slow"))
    response = api.post("/api/scans", json={"url": REPO_URL})
    assert response.status_code == 504


def test_scan_rate_limit(api, github):
    for _ in range(10):
        assert api.post("/api/scans", json={"url": REPO_URL}).status_code == 200
    response = api.post("/api/scans", json={"url": REPO_URL})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


def test_unknown_scan_is_404(api):
    response = api.get("/api/scans/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_renamed_repo_follows_redirect(api, github):
    old = "https://api.github.com/repos/acme/old-name"
    github.get(old).respond(301, headers={"Location": GITHUB})
    report = api.post("/api/scans", json={"url": "https://github.com/acme/old-name"}).json()
    assert report["repo_full_name"] == "acme/widgets"


def test_symlinked_artefact_is_an_alias_not_a_duplicate(api, github):
    tree = [
        {"path": "README.md", "type": "blob"},
        {"path": "CLAUDE.md", "type": "blob"},
        {"path": ".github", "type": "tree"},
        {"path": ".github/copilot-instructions.md", "type": "blob", "mode": "120000", "sha": "ln"},
        {"path": "src", "type": "tree"},
        {"path": "src/app.py", "type": "blob"},
    ]
    github.get(f"{GITHUB}/git/trees/head123").respond(json={"tree": tree, "truncated": False})
    github.get(f"{GITHUB}/git/blobs/ln").respond(text="../CLAUDE.md")

    report = api.post("/api/scans", json={"url": REPO_URL}).json()

    assert [a["path"] for a in report["artefacts"]] == ["CLAUDE.md"]
    claude = report["artefacts"][0]
    assert claude["aliases"] == [".github/copilot-instructions.md"]
    assert claude["duplicate_rules"] == []
    assert report["tools"] == ["Claude Code"]


def test_very_large_repo_is_listed_folder_by_folder(api, github):
    root = [
        {"path": "README.md", "type": "blob"},
        {"path": "CLAUDE.md", "type": "blob"},
        {"path": ".github", "type": "tree", "sha": "gh"},
        {"path": "src", "type": "tree", "sha": "src"},
    ]
    inner = {
        "gh": [{"path": "copilot-instructions.md", "type": "blob"}],
        "src": [{"path": "app.py", "type": "blob"}],
    }

    def trees(request: httpx.Request) -> httpx.Response:
        sha = request.url.path.rsplit("/", 1)[-1]
        if sha == "head123":
            truncated = "recursive" in request.url.params
            return httpx.Response(
                200, json={"tree": root[:1] if truncated else root, "truncated": truncated}
            )
        return httpx.Response(200, json={"tree": inner[sha], "truncated": False})

    github.get(url__regex=rf"{GITHUB}/git/trees/.+").mock(side_effect=trees)
    report = api.post("/api/scans", json={"url": REPO_URL}).json()

    claude = next(a for a in report["artefacts"] if a["path"] == "CLAUDE.md")
    assert [r["path"] for r in claude["broken_refs"]] == ["scripts/old.sh", "docs/"]
    assert any(a["path"] == ".github/copilot-instructions.md" for a in report["artefacts"])
