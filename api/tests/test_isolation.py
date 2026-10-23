from .conftest import REPO_URL, new_key


def test_clients_cannot_touch_each_others_data(api, github):
    alice, bob = new_key(api), new_key(api)

    item = api.post("/api/watchlist", headers=alice, json={"url": REPO_URL}).json()
    row = api.post(
        "/api/triage",
        headers=alice,
        json={"repo_full_name": "acme/widgets", "finding_key": "stale:x", "status": "ignored"},
    ).json()

    assert api.get("/api/watchlist", headers=bob).json() == []
    assert api.get("/api/triage", headers=bob).json() == []

    for method, url, body in [
        ("GET", f"/api/watchlist/{item['id']}", None),
        ("PATCH", f"/api/watchlist/{item['id']}", {"label": "mine"}),
        ("POST", f"/api/watchlist/{item['id']}/rescan", None),
        ("DELETE", f"/api/watchlist/{item['id']}", None),
        ("GET", f"/api/triage/{row['id']}", None),
        ("PATCH", f"/api/triage/{row['id']}", {"status": "open"}),
        ("DELETE", f"/api/triage/{row['id']}", None),
    ]:
        response = api.request(method, url, headers=bob, json=body)
        assert response.status_code == 404, (method, url)

    assert api.get(f"/api/watchlist/{item['id']}", headers=alice).json()["label"] == ""
    assert api.get(f"/api/triage/{row['id']}", headers=alice).json()["status"] == "ignored"

    report = api.post("/api/scans", headers=bob, json={"url": REPO_URL}).json()
    assert report["watchlist_item_id"] is None
