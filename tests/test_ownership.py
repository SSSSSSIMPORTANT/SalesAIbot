from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import Conversation, ConversationFact, Customer, Message, get_db
from app.services.operator_accounts import create_operator_account
from scripts.assign_legacy_ownership import assign_legacy_ownership


@pytest.fixture
def operators(anonymous_client):
    application = anonymous_client.app
    session_factory = application.dependency_overrides[get_db]
    password = "synthetic ownership test passphrase"
    with closing(session_factory()) as sessions:
        db = next(sessions)
        a = create_operator_account(db, username="operator-a", password=password).id
        b = create_operator_account(db, username="operator-b", password=password).id

    with TestClient(application) as second:
        for client, username in ((anonymous_client, "operator-a"), (second, "operator-b")):
            client.headers["Origin"] = str(client.base_url).rstrip("/")
            response = client.post("/auth/login", json={"username": username, "password": password})
            assert response.status_code == 200
        yield anonymous_client, second, a, b, session_factory


def create(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_operators_only_see_their_own_customers_and_conversations(operators):
    a, b, owner_a, owner_b, sessions = operators
    a_customer = create(a, "/customers", {"display_name": "同名合成客户"})
    b_customer = create(b, "/customers", {"display_name": "同名合成客户"})
    a_conversation = create(a, "/conversations", {"customer_id": a_customer["id"]})
    b_conversation = create(b, "/conversations", {"customer_id": b_customer["id"]})

    for client, own_customer, own_conversation, foreign_customer, foreign_conversation in (
        (a, a_customer, a_conversation, b_customer, b_conversation),
        (b, b_customer, b_conversation, a_customer, a_conversation),
    ):
        assert client.get("/conversations").json() == [own_conversation]
        assert client.get(f"/customers/{own_customer['id']}").status_code == 200
        assert client.get(f"/customers/{foreign_customer['id']}").status_code == 404
        assert client.get(f"/conversations/{foreign_conversation['id']}").status_code == 404
        assert client.post(
            "/conversations", json={"customer_id": foreign_customer["id"]}
        ).status_code == 404

    assert a.post("/conversations", json={
        "customer_name": "合成客户", "owner_operator_id": owner_b,
    }).status_code == 422
    with closing(sessions()) as entries:
        db = next(entries)
        assert db.get(Conversation, a_conversation["id"]).owner_operator_id == owner_a
        assert db.get(Customer, b_customer["id"]).owner_operator_id == owner_b
        db.add(Conversation(
            customer_name="越权外键检查",
            owner_operator_id=owner_b,
            customer_id=a_customer["id"],
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_foreign_conversation_blocks_all_nested_routes_and_source_links(operators):
    a, b, _, _, _ = operators
    a_id = create(a, "/conversations", {"customer_name": "合成客户 A"})["id"]
    b_id = create(b, "/conversations", {"customer_name": "合成客户 B"})["id"]
    path = f"/conversations/{a_id}"
    message = create(a, f"{path}/messages", {
        "request_key": "source-001", "based_on_version": 0,
        "actor": "customer", "text": "我想学习 Python",
    })
    fact_body = {
        "based_on_version": 1, "fact_key": "learning_goal",
        "value": "学习 Python", "source_message_id": message["id"],
    }
    fact = create(a, f"{path}/facts", fact_body)
    generation = {"based_on_version": 2, "product_id": "demo_python_basic"}
    suggestion = create(a, f"{path}/suggestions", {
        **generation, "request_key": "suggestion-001",
    })
    draft = f"/suggestions/{suggestion['id']}"

    operations = [
        ("GET", "", None),
        ("PUT", "/assistance", {"based_on_version": 2, "suggestions_paused": True}),
        ("GET", "/messages", None),
        ("POST", "/messages", {
            "request_key": "foreign-001", "based_on_version": 2,
            "actor": "customer", "text": "禁止写入的合成消息",
        }),
        ("GET", "/facts", None),
        ("POST", "/facts", {**fact_body, "based_on_version": 2}),
        ("POST", f"/facts/{fact['id']}/revoke", {"based_on_version": 2}),
        ("POST", "/memory-candidates", {
            "based_on_version": 2, "source_message_id": message["id"],
        }),
        ("GET", "/memory-recall", None),
        ("POST", "/reply-preview", generation),
        ("POST", "/screenshots/preview", None),
        ("POST", "/screenshots/transcribe?based_on_version=2", None),
        ("GET", "/suggestions", None),
        ("POST", "/suggestions", {**generation, "request_key": "foreign-002"}),
        ("GET", draft, None),
        ("GET", f"{draft}/validity", None),
        ("POST", f"{draft}/copy-ready", None),
        ("GET", f"{draft}/copy-events", None),
        ("POST", f"{draft}/copy-events", {"request_key": "foreign-003"}),
        ("GET", "/generation-requests/by-key?request_key=suggestion-001", None),
    ]
    for method, suffix, body in operations:
        response = b.request(method, path + suffix, json=body)
        assert response.status_code == 404, (method, suffix, response.text)
        assert response.json() == {"detail": "Conversation not found"}

    assert b.post(f"/conversations/{b_id}/messages", json={
        "request_key": "foreign-source", "based_on_version": 0,
        "actor": "human", "text": "越权来源检查", "source_suggestion_id": suggestion["id"],
    }).status_code == 404
    assert a.get(f"{path}/messages").json() == [message]
    assert a.get(f"{path}/facts").json() == [fact]
    assert a.get(f"{path}{draft}/copy-events").json() == []
    assert a.get(path).json()["version"] == 2


def test_legacy_records_are_invisible_until_explicitly_assigned(operators):
    a, b, owner_a, _, sessions = operators
    customer = create(a, "/customers", {"display_name": "有历史会话的合成客户"})
    current = create(a, "/conversations", {"customer_id": customer["id"]})

    with closing(sessions()) as entries:
        db = next(entries)
        legacy = Conversation(customer_name=customer["display_name"], customer_id=customer["id"])
        db.add(legacy)
        db.flush()
        legacy_id = legacy.id
        source = Message(conversation_id=legacy_id, actor="customer", text="学习 Python")
        db.add(source)
        db.flush()
        db.add(ConversationFact(
            conversation_id=legacy_id, source_message_id=source.id,
            fact_key="learning_goal", value=source.text,
        ))
        db.add(Customer(display_name="未分配的合成客户"))
        db.commit()

        recall = f"/conversations/{current['id']}/memory-recall"
        assert a.get(recall).json()["recalled_memory"] == []
        assert a.get(f"/conversations/{legacy_id}").status_code == 404
        assert b.get(f"/conversations/{legacy_id}").status_code == 404

        with pytest.raises(ValueError, match="其他账号"):
            assign_legacy_ownership(db, "operator-b")

        assert assign_legacy_ownership(db, "operator-a") == (1, 1)
        assert assign_legacy_ownership(db, "operator-a") == (0, 0)
        assert db.get(Conversation, legacy_id).owner_operator_id == owner_a

    assert a.get(f"/conversations/{legacy_id}").status_code == 200
    assert b.get(f"/conversations/{legacy_id}").status_code == 404
    assert a.get(recall).json()["recalled_memory"][0]["conversation_id"] == legacy_id
