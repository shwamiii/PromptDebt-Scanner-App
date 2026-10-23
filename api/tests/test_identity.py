from sqlalchemy import select

from app.db import SessionLocal
from app.models import Client

from .conftest import REPO_URL, new_key


def test_create_and_check_key(api):
    response = api.post("/api/identity")
    assert response.status_code == 201
    key = response.json()["key"]
    assert len(key) >= 43

    me = api.get("/api/identity/me", headers={"Authorization": f"Bearer {key}"})
    assert me.status_code == 200


def test_only_hash_is_stored(api):
    key = api.post("/api/identity").json()["key"]
    with SessionLocal() as db:
        stored = db.scalars(select(Client.token_hash)).all()
    assert key not in stored
    assert len(stored[0]) == 64


def test_unknown_or_missing_key_is_401(api):
    assert api.get("/api/identity/me").status_code == 401
    bad = api.get("/api/identity/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_key"


def test_delete_removes_client_and_data(api, github):
    auth = new_key(api)
    api.post("/api/watchlist", headers=auth, json={"url": REPO_URL})

    assert api.delete("/api/identity", headers=auth).status_code == 204
    assert api.get("/api/identity/me", headers=auth).status_code == 401
    with SessionLocal() as db:
        assert db.scalars(select(Client)).all() == []
