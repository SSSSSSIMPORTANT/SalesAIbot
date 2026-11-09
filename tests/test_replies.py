import pytest

def test_reply_preview_does_not_add_message(client):
    created = client.post(
        "/conversations",
        json={"customer_name": "合成测试客户"},
    )
    assert created.status_code == 201

    conversation_id = created.json()["id"]
    conversation_url = f"/conversations/{conversation_id}"
    messages_url = f"{conversation_url}/messages"
    preview_url = f"{conversation_url}/reply-preview"

    submitted = client.post(
        messages_url,
        json={
            "request_key": "reply-test-001",
            "based_on_version": 0,
            "actor": "customer",
            "text": "课程多少钱？",
        },
    )
    assert submitted.status_code == 201

    preview = client.post(
        preview_url,
        json={
            "based_on_version": 1,
            "product_id": "demo_python_basic",
        },
    )

    assert preview.status_code == 200
    assert preview.json()["based_on_version"] == 1
    assert preview.json()["reply"]["mode"] == "mock"

    # 回复草稿没有成为实际聊天，也没有推进版本。
    assert len(client.get(messages_url).json()) == 1
    assert client.get(conversation_url).json()["version"] == 1

    stale = client.post(
        preview_url,
        json={
            "based_on_version": 0,
            "product_id": "demo_python_basic",
        },
    )
    assert stale.status_code == 409

    data = preview.json()

    assert data["retrieved_knowledge"]["knowledge_id"] == "demo-terms-a"
    assert data["retrieved_knowledge"]["revision"] == "v1"
    assert data["retrieved_knowledge"]["price_cents"] == 19900
    assert "199.00" in data["reply"]["text"]

@pytest.mark.parametrize(
    "product_id",
    ["demo_python_project", "unknown-product"],
)
def test_preview_rejects_unavailable_knowledge(client, product_id):
    created = client.post(
        "/conversations",
        json={"customer_name": "合成测试客户"},
    )
    assert created.status_code == 201

    conversation_id = created.json()["id"]
    url = f"/conversations/{conversation_id}"

    submitted = client.post(
        f"{url}/messages",
        json={
            "request_key": "knowledge-preview-001",
            "based_on_version": 0,
            "actor": "customer",
            "text": "这门课程多少钱？",
        },
    )
    assert submitted.status_code == 201

    preview = client.post(
        f"{url}/reply-preview",
        json={
            "based_on_version": 1,
            "product_id": product_id,
        },
    )

    assert preview.status_code == 404
    assert client.get(url).json()["version"] == 1
    assert len(client.get(f"{url}/messages").json()) == 1


def test_explicit_refund_rule_can_be_saved_and_copied(client, monkeypatch):
    runtime = client.app.state.runtime

    def unexpected_call(*args, **kwargs):
        pytest.fail("明确的退款办理请求应直接走服务端规则")

    monkeypatch.setattr(runtime.gateway, "request_product_tool", unexpected_call)
    monkeypatch.setattr(runtime.gateway, "generate", unexpected_call)
    monkeypatch.setattr(runtime.tool_executor, "execute", unexpected_call)
    monkeypatch.setattr(
        runtime.repository, "get_current_published_product", unexpected_call
    )

    created = client.post("/conversations", json={"customer_name": "合成退款客户"})
    assert created.status_code == 201
    url = f"/conversations/{created.json()['id']}"

    added = client.post(
        f"{url}/messages",
        json={
            "request_key": "refund-rule-message",
            "based_on_version": 0,
            "actor": "customer",
            "text": "请帮我办理退款。",
        },
    )
    assert added.status_code == 201

    body = {"based_on_version": 1, "product_id": "demo_python_basic"}
    preview = client.post(f"{url}/reply-preview", json=body)
    assert preview.status_code == 200
    data = preview.json()
    assert data["reply"]["mode"] == "rule"
    assert data["reply"]["topics"] == ["refund_request"]
    assert data["retrieved_knowledge"] is None
    assert [step["step"] for step in data["trace"]] == ["rule_refund_request"]

    saved = client.post(
        f"{url}/suggestions",
        json={**body, "request_key": "refund-rule-suggestion"},
    )
    assert saved.status_code == 201
    suggestion_id = saved.json()["id"]

    copied = client.post(f"{url}/suggestions/{suggestion_id}/copy-ready")
    assert copied.status_code == 200
    assert copied.json()["text"] == data["reply"]["text"]
    assert client.get(url).json()["version"] == 1
    assert len(client.get(f"{url}/messages").json()) == 1
