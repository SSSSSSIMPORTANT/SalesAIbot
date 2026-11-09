from hashlib import sha256

import pytest

from app.database import OperatorAccount, OperatorSession, get_db
from app.services.operator_accounts import create_operator_account
from app.services.operator_sessions import SESSION_COOKIE


LOGIN = {
    "username": "LOCAL-SALES",
    "password": "synthetic local test passphrase",
}


@pytest.fixture
def client(anonymous_client):
    return anonymous_client


@pytest.fixture
def db(client):
    yield from client.app.dependency_overrides[get_db]()


@pytest.fixture
def account_id(db):
    account = create_operator_account(
        db,
        username="local-sales",
        password=LOGIN["password"],
    )
    account_id = account.id
    db.rollback()
    return account_id


def test_login_and_logout_revoke_the_old_cookie(client, db, account_id):
    assert client.get("/auth/me").status_code == 401

    response = client.post("/auth/login", json=LOGIN)
    assert response.status_code == 200
    assert response.json() == {"id": account_id, "username": "local-sales"}
    assert "httponly" in response.headers["set-cookie"].lower()

    token = client.cookies[SESSION_COOKIE]
    digest = sha256(token.encode("utf-8")).hexdigest()
    assert db.get(OperatorSession, digest) is not None
    db.rollback()

    assert client.get("/auth/me").json() == response.json()
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401

    replay = client.get(
        "/auth/me",
        headers={"Cookie": f"{SESSION_COOKIE}={token}"},
    )
    assert replay.status_code == 401


@pytest.mark.parametrize("reason", ["expired", "disabled"])
def test_session_rechecks_expiration_and_account_status(
    client, db, account_id, reason
):
    assert client.post("/auth/login", json=LOGIN).status_code == 200

    if reason == "expired":
        token = client.cookies[SESSION_COOKIE]
        digest = sha256(token.encode("utf-8")).hexdigest()
        db.get(OperatorSession, digest).expires_at = 0
    else:
        db.get(OperatorAccount, account_id).is_active = False

    db.commit()
    assert client.get("/auth/me").status_code == 401


def test_wrong_password_and_unknown_account_have_same_error(
    client, account_id
):
    wrong = client.post("/auth/login", json={**LOGIN, "password": "wrong"})
    unknown = client.post(
        "/auth/login",
        json={**LOGIN, "username": "unknown-sales"},
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_rejects_cross_origin_and_hides_invalid_password(client):
    cross_origin = client.post(
        "/auth/login",
        json=LOGIN,
        headers={"Origin": "https://other.example"},
    )
    assert cross_origin.status_code == 403

    invalid_password = "synthetic-sensitive-input-" * 10
    invalid = client.post(
        "/auth/login",
        json={**LOGIN, "password": invalid_password},
    )
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "Invalid authentication request"}


def test_business_routes_require_a_real_session(client, account_id):
    assert client.get("/health").status_code == 200
    assert client.get("/conversations").status_code == 401
    assert client.get("/products").status_code == 401
    assert client.post(
        "/conversations/missing/suggestions",
        json={
            "request_key": "generate-001",
            "based_on_version": 0,
            "product_id": "demo_python_basic",
        },
    ).status_code == 401

    assert client.post("/auth/login", json=LOGIN).status_code == 200
    assert client.get("/conversations").status_code == 200
    assert client.get("/products").status_code == 200

    wrong_page = client.get(
        "/conversations",
        headers={"X-Workbench-Operator": "another-operator"},
    )
    assert wrong_page.status_code == 401

    assert client.post(
        "/conversations", json={"customer_name": "合成客户"}
    ).status_code == 201

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/conversations").status_code == 401


def test_authenticated_writes_reject_untrusted_origin(client, account_id):
    assert client.post("/auth/login", json=LOGIN).status_code == 200
    payload = {"customer_name": "不应写入的合成客户"}

    assert client.post(
        "/conversations",
        json=payload,
        headers={"Origin": "https://other.example"},
    ).status_code == 403

    client.headers.pop("Origin")
    assert client.post("/conversations", json=payload).status_code == 403
    assert client.get("/conversations").json() == []
