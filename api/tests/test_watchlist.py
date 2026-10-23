from .conftest import GITHUB, REPO_URL, new_key


def test_watchlist_crud(api, github):
    auth = new_key(api)

    created = api.post("/api/watchlist", headers=auth, json={"url": REPO_URL, "label": " Work "})
    assert created.status_code == 201
    item = created.json()
    assert item["repo_full_name"] == "acme/widgets"
    assert item["label"] == "Work"
    assert item["latest"]["artefact_count"] == 2
    assert item["latest"]["open_findings"] == 6
    assert (item["latest"]["debt_score"], item["latest"]["debt_band"]) == (49, "moderate")

    listed = api.get("/api/watchlist", headers=auth).json()
    assert [i["id"] for i in listed] == [item["id"]]

    updated = api.patch(
        f"/api/watchlist/{item['id']}", headers=auth, json={"notes": "Check monthly"}
    ).json()
    assert updated["notes"] == "Check monthly"
    assert updated["label"] == "Work"

    assert api.get(f"/api/watchlist/{item['id']}", headers=auth).json()["notes"] == "Check monthly"

    assert api.delete(f"/api/watchlist/{item['id']}", headers=auth).status_code == 204
    assert api.get(f"/api/watchlist/{item['id']}", headers=auth).status_code == 404


def test_rescan_updates_latest_scan(api, github):
    auth = new_key(api)
    item = api.post("/api/watchlist", headers=auth, json={"url": REPO_URL}).json()

    github.get(f"{GITHUB}/git/trees/head123").respond(json={"tree": [], "truncated": False})
    rescanned = api.post(f"/api/watchlist/{item['id']}/rescan", headers=auth).json()

    assert rescanned["latest"]["scan_id"] != item["latest"]["scan_id"]
    assert rescanned["latest"]["artefact_count"] == 0


def test_triaged_findings_are_not_counted_as_open(api, github):
    auth = new_key(api)
    item = api.post("/api/watchlist", headers=auth, json={"url": REPO_URL}).json()
    api.post(
        "/api/triage",
        headers=auth,
        json={
            "repo_full_name": "acme/widgets",
            "finding_key": "stale:.github/copilot-instructions.md",
            "status": "ignored",
        },
    )
    assert (
        api.get(f"/api/watchlist/{item['id']}", headers=auth).json()["latest"]["open_findings"] == 5
    )


def test_duplicate_repo_is_rejected(api, github):
    auth = new_key(api)
    api.post("/api/watchlist", headers=auth, json={"url": REPO_URL})
    again = api.post("/api/watchlist", headers=auth, json={"url": REPO_URL + ".git"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_watched"


def test_validation_and_auth(api, github):
    assert api.get("/api/watchlist").status_code == 401
    auth = new_key(api)
    bad = api.post("/api/watchlist", headers=auth, json={"url": "not a url"})
    assert bad.status_code == 400
    long_label = api.post(
        "/api/watchlist", headers=auth, json={"url": REPO_URL, "label": "x" * 101}
    )
    assert long_label.status_code == 422
    assert long_label.json()["error"]["code"] == "invalid_input"


def test_add_from_existing_scan_makes_no_github_calls(api, github):
    auth = new_key(api)
    report = api.post("/api/scans", json={"url": REPO_URL}).json()
    calls_after_scan = github.calls.call_count

    created = api.post("/api/watchlist", headers=auth, json={"scan_id": report["id"]})
    assert created.status_code == 201
    assert created.json()["latest"]["scan_id"] == report["id"]
    assert github.calls.call_count == calls_after_scan


def test_add_needs_url_or_scan_id(api):
    auth = new_key(api)
    assert api.post("/api/watchlist", headers=auth, json={}).status_code == 422
    unknown = api.post("/api/watchlist", headers=auth, json={"scan_id": "nope"})
    assert unknown.status_code == 404


def test_removing_a_repo_removes_its_triage(api, github):
    auth = new_key(api)
    item = api.post("/api/watchlist", headers=auth, json={"url": REPO_URL}).json()
    api.post(
        "/api/triage",
        headers=auth,
        json={"repo_full_name": "acme/widgets", "finding_key": "stale:x", "status": "ignored"},
    )
    api.delete(f"/api/watchlist/{item['id']}", headers=auth)
    assert api.get("/api/triage", headers=auth).json() == []
