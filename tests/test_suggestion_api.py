import pytest

from app.llm import MockModelGateway
from app.knowledge import KnowledgeRepository


def prepare_conversation(client, customer_id=None):
    created = client.post(
        "/conversations",
        json=(
            {"customer_id": customer_id}
            if customer_id is not None
            else {"customer_name": "合成草稿测试客户"}
        ),
    )
    assert created.status_code == 201

    url = f"/conversations/{created.json()['id']}"

    added = client.post(
        f"{url}/messages",
        json={
            "request_key": "suggestion-source",
            "based_on_version": 0,
            "actor": "customer",
            "text": "课程多少钱？",
        },
    )
    assert added.status_code == 201

    return url


def test_saved_suggestion_preserves_history(client):
    url = prepare_conversation(client)
    body = {
        "based_on_version": 1,
        "product_id": "demo_python_basic",
    }

    preview = client.post(f"{url}/reply-preview", json=body)
    assert preview.status_code == 200
    assert client.get(f"{url}/suggestions").json() == []

    saved = client.post(
        f"{url}/suggestions",
        json={**body, "request_key": "saved-history-001"},
    )
    assert saved.status_code == 201
    data = saved.json()

    validity_url = f"{url}/suggestions/{data['id']}/validity"
    validity = client.get(validity_url)

    assert validity.status_code == 200
    assert validity.json()["status"] == "current"
    assert validity.json()["reasons"] == []

    snapshot = data["generation_snapshot"]
    assert snapshot["reply"]["text"] == data["reply_text"]
    assert snapshot["retrieved_knowledge"]["price_cents"] == 19900
    assert snapshot["based_on_version"] == 1
    assert len(snapshot["trace"]) == 3

    assert client.get(url).json()["version"] == 1
    assert len(client.get(f"{url}/messages").json()) == 1
    assert len(client.get(f"{url}/suggestions").json()) == 1

    added = client.post(
        f"{url}/messages",
        json={
            "request_key": "later-message",
            "based_on_version": 1,
            "actor": "customer",
            "text": "我补充一个问题。",
        },
    )
    assert added.status_code == 201

    validity = client.get(validity_url)

    assert validity.status_code == 200
    assert validity.json()["status"] == "stale"
    assert "conversation_changed" in validity.json()["reasons"]

    fetched = client.get(
        f"{url}/suggestions/{data['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json() == data

    # 新操作使用新 key，验证旧版本不能启动一次新的生成。
    stale = client.post(
        f"{url}/suggestions",
        json={**body, "request_key": "stale-new-generation"},
    )
    assert stale.status_code == 409
    assert len(client.get(f"{url}/suggestions").json()) == 1


def test_suggestion_detail_is_scoped_to_conversation(client):
    first_url = prepare_conversation(client)
    second_url = prepare_conversation(client)

    saved = client.post(
        f"{first_url}/suggestions",
        json={
            "request_key": "generate-001",
            "based_on_version": 1,
            "product_id": "demo_python_basic",
        },
    )
    assert saved.status_code == 201

    response = client.get(
        f"{second_url}/suggestions/{saved.json()['id']}"
    )
    assert response.status_code == 404


def test_generation_change_does_not_save_suggestion(client, monkeypatch):
    url = prepare_conversation(client)
    original_generate = MockModelGateway.generate

    def changing_generate(self, **kwargs):
        added = client.post(
            f"{url}/messages",
            json={
                "request_key": "during-suggestion",
                "based_on_version": 1,
                "actor": "customer",
                "text": "生成期间补充的信息。",
            },
        )
        assert added.status_code == 201

        return original_generate(self, **kwargs)

    monkeypatch.setattr(
        MockModelGateway,
        "generate",
        changing_generate,
    )

    response = client.post(
        f"{url}/suggestions",
        json={
            "request_key": "generate-001",
            "based_on_version": 1,
            "product_id": "demo_python_basic",
        },
    )

    assert response.status_code == 409
    assert client.get(f"{url}/suggestions").json() == []


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("current", 200),
        ("message_changed", 409),
        ("memory_changed", 409),
        ("knowledge_changed", 409),
        ("check_unavailable", 503),
        ("wrong_conversation", 404),
    ],
)
def test_copy_ready(
    client,
    monkeypatch,
    case,
    expected_status,
):
    customer_id = None

    if case == "memory_changed":
        created = client.post(
            "/customers",
            json={"display_name": "合成复制测试客户"},
        )
        assert created.status_code == 201
        customer_id = created.json()["id"]

    url = prepare_conversation(client, customer_id)

    saved = client.post(
        f"{url}/suggestions",
        json={
            "request_key": "generate-001",
            "based_on_version": 1,
            "product_id": "demo_python_basic",
        },
    )
    assert saved.status_code == 201
    suggestion = saved.json()

    if case == "message_changed":
        added = client.post(
            f"{url}/messages",
            json={
                "request_key": "after-draft",
                "based_on_version": 1,
                "actor": "customer",
                "text": "补充一个问题。",
            },
        )
        assert added.status_code == 201

    elif case == "memory_changed":
        source_url = prepare_conversation(client, customer_id)

        added = client.post(
            f"{source_url}/messages",
            json={
                "request_key": "customer-background",
                "based_on_version": 1,
                "actor": "customer",
                "text": "我没有编程基础。",
            },
        )
        assert added.status_code == 201

        fact = client.post(
            f"{source_url}/facts",
            json={
                "based_on_version": 2,
                "fact_key": "current_level",
                "value": "没有编程基础",
                "source_message_id": added.json()["id"],
            },
        )
        assert fact.status_code == 201
        assert client.get(url).json()["version"] == 1

    elif case == "knowledge_changed":
        original = KnowledgeRepository.get_current_published_product

        def changed_product(self, product_id):
            product = original(self, product_id)
            assert product is not None
            return product.model_copy(
                update={"price_cents": product.price_cents + 100}
            )

        monkeypatch.setattr(
            KnowledgeRepository,
            "get_current_published_product",
            changed_product,
        )

    elif case == "check_unavailable":
        def unavailable(self, product_id):
            raise OSError("Synthetic knowledge read failure")

        monkeypatch.setattr(
            KnowledgeRepository,
            "get_current_published_product",
            unavailable,
        )

    target_url = url

    if case == "wrong_conversation":
        target_url = prepare_conversation(client)

    # 检查和获取正文不应再次调用模型。
    def unexpected_model_call(self, **kwargs):
        pytest.fail("copy-ready must not call the model")

    monkeypatch.setattr(
        MockModelGateway,
        "generate",
        unexpected_model_call,
    )
    monkeypatch.setattr(
        MockModelGateway,
        "request_product_tool",
        unexpected_model_call,
    )

    version_before = client.get(url).json()["version"]
    messages_before = client.get(f"{url}/messages").json()

    response = client.post(
        (
            f"{target_url}/suggestions/"
            f"{suggestion['id']}/copy-ready"
        )
    )

    assert response.status_code == expected_status

    if case == "current":
        assert response.json() == {
            "suggestion_id": suggestion["id"],
            "based_on_version": 1,
            "text": suggestion["reply_text"],
        }
    else:
        assert "text" not in response.json()

    if case.endswith("_changed"):
        assert response.json()["detail"]["code"] == "suggestion_stale"
        expected_reason = (
            "conversation_changed"
            if case == "message_changed"
            else case
        )
        assert expected_reason in response.json()["detail"]["reasons"]

    assert client.get(url).json()["version"] == version_before
    assert client.get(f"{url}/messages").json() == messages_before

    # 原始草稿及其生成依据没有被检查动作修改。
    historical = client.get(
        f"{url}/suggestions/{suggestion['id']}"
    )
    assert historical.json() == suggestion


def test_copy_reports_are_idempotent_and_not_chat_messages(client):
    url = prepare_conversation(client)

    saved = client.post(
        f"{url}/suggestions",
        json={
            "request_key": "generate-001",
            "based_on_version": 1,
            "product_id": "demo_python_basic",
        },
    )
    assert saved.status_code == 201
    suggestion_id = saved.json()["id"]

    base = f"{url}/suggestions/{suggestion_id}"

    ready = client.post(f"{base}/copy-ready")
    assert ready.status_code == 200

    # 获取正文不等于客户端已经报告复制成功。
    assert client.get(f"{base}/copy-events").json() == []

    first = client.post(
        f"{base}/copy-events",
        json={"request_key": "copy-action-001"},
    )
    assert first.status_code == 201

    retry = client.post(
        f"{base}/copy-events",
        json={"request_key": "copy-action-001"},
    )
    assert retry.status_code == 200
    assert retry.json() == first.json()

    second = client.post(
        f"{base}/copy-events",
        json={"request_key": "copy-action-002"},
    )
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]

    events = client.get(f"{base}/copy-events")
    assert events.status_code == 200
    assert len(events.json()) == 2

    assert client.get(url).json()["version"] == 1
    assert len(client.get(f"{url}/messages").json()) == 1
    assert client.get(base).json() == saved.json()


def test_copy_reports_cannot_use_another_conversation(client):
    first_url = prepare_conversation(client)
    second_url = prepare_conversation(client)

    saved = client.post(
        f"{first_url}/suggestions",
        json={
            "request_key": "generate-001",
            "based_on_version": 1,
            "product_id": "demo_python_basic",
        },
    )
    assert saved.status_code == 201
    suggestion_id = saved.json()["id"]

    wrong_url = (
        f"{second_url}/suggestions/{suggestion_id}/copy-events"
    )

    reported = client.post(
        wrong_url,
        json={"request_key": "wrong-conversation"},
    )
    assert reported.status_code == 404
    assert client.get(wrong_url).status_code == 404

    correct_url = (
        f"{first_url}/suggestions/{suggestion_id}/copy-events"
    )
    assert client.get(correct_url).json() == []
