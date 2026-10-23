import httpx

from .conftest import GITHUB, REPO_URL, commit, new_key

STALE = "stale:.github/copilot-instructions.md"


def watching(api) -> dict[str, str]:
    auth = new_key(api)
    api.post("/api/watchlist", headers=auth, json={"url": REPO_URL})
    return auth


def triage(api, auth, key=STALE, status="acknowledged", repo="acme/widgets"):
    return api.post(
        "/api/triage",
        headers=auth,
        json={"repo_full_name": repo, "finding_key": key, "status": status, "note": "n"},
    )


def test_triage_crud(api, github):
    auth = watching(api)

    created = triage(api, auth)
    assert created.status_code == 201
    row = created.json()
    assert row["status"] == "acknowledged"

    assert api.get(f"/api/triage/{row['id']}", headers=auth).json()["note"] == "n"

    updated = api.patch(
        f"/api/triage/{row['id']}", headers=auth, json={"status": "fixed", "note": "done"}
    ).json()
    assert (updated["status"], updated["note"]) == ("fixed", "done")

    assert api.delete(f"/api/triage/{row['id']}", headers=auth).status_code == 204
    assert api.get(f"/api/triage/{row['id']}", headers=auth).status_code == 404


def test_only_watched_repos_can_be_triaged(api, github):
    auth = new_key(api)
    refused = triage(api, auth)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "not_watched"

    api.post("/api/watchlist", headers=auth, json={"url": REPO_URL})
    assert triage(api, auth).status_code == 201
    assert triage(api, auth, repo="other/repo").status_code == 409


def test_list_filters_by_repo_and_status(api, github):
    auth = watching(api)
    triage(api, auth, status="ignored")
    triage(api, auth, key="undocumented:CLAUDE.md", status="open")

    by_status = api.get("/api/triage?status=ignored", headers=auth).json()
    assert [t["finding_key"] for t in by_status] == [STALE]
    by_repo = api.get("/api/triage?repo=acme/widgets", headers=auth).json()
    assert len(by_repo) == 2
    assert api.get("/api/triage?repo=other/repo", headers=auth).json() == []


def test_fixed_but_still_detected(api, github):
    auth = watching(api)
    triage(api, auth, status="fixed")
    assert api.get("/api/triage", headers=auth).json()[0]["still_detected"] is True

    latest = commit("head123", "2026-10-01T12:00:00Z")
    github.get(f"{GITHUB}/commits").mock(
        side_effect=lambda request: httpx.Response(
            200, json=[] if "since" in request.url.params else [latest]
        )
    )
    api.post("/api/scans", json={"url": REPO_URL})
    assert api.get("/api/triage", headers=auth).json()[0]["still_detected"] is False


def test_duplicate_and_invalid_input(api, github):
    auth = watching(api)
    triage(api, auth)
    assert triage(api, auth).status_code == 409
    assert triage(api, auth, key="stale:x", status="done").status_code == 422
    assert triage(api, auth, key="stale:x", repo="not a repo").status_code == 422
