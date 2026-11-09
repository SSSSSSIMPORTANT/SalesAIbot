from concurrent.futures import ThreadPoolExecutor

import pytest

from app.api.auth import require_operator
from app.llm import ModelPlan, ReplyDraft
from app.schemas.auth import OperatorIdentity


def conversation(client):
    response = client.post("/conversations", json={"customer_name": "合成客户"})
    assert response.status_code == 201
    return f"/conversations/{response.json()['id']}"


def message(client, url, *, version=0, actor="customer", text="请帮我退款。"):
    response = client.post(f"{url}/messages", json={
        "request_key": f"message-{version}", "based_on_version": version,
        "actor": actor, "text": text,
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_handoff_retries_and_resolution_are_auditable(client):
    url = conversation(client)
    source = message(client, url)
    path = f"{url}/messages/{source}/handoff"
    body = {"reason": "refund_request"}

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, retry = list(workers.map(lambda _: client.put(path, json=body), range(2)))
    assert sorted([first.status_code, retry.status_code]) == [200, 201]
    assert first.json() == retry.json()
    assert first.json()["created_by_operator_id"] == "0" * 32
    assert first.json()["status"] == "pending"
    assert client.put(path, json={"reason": "complaint"}).status_code == 409

    resolution = {"resolution": "人工已核对并回复。"}
    done = client.put(f"{path}/resolution", json=resolution)
    assert done.status_code == 200
    assert done.json()["status"] == "resolved"
    assert done.json()["resolved_by_operator_id"] == "0" * 32
    assert client.put(f"{path}/resolution", json=resolution).json() == done.json()
    changed = client.put(f"{path}/resolution", json={"resolution": "覆盖原结果"})
    assert changed.status_code == 409
    assert client.get(f"{url}/handoffs").json() == [done.json()]
    assert client.get(url).json()["version"] == 1
    assert len(client.get(f"{url}/messages").json()) == 1


def test_handoff_requires_owned_customer_message_and_same_origin(client):
    url = conversation(client)
    source = message(client, url)
    human = message(client, url, version=1, actor="human", text="人工回复")
    other_url = conversation(client)
    body = {"reason": "complaint"}
    path = f"{url}/messages/{source}/handoff"
    assert client.put(f"{other_url}/messages/{source}/handoff", json=body).status_code == 404
    assert client.put(f"{url}/messages/{human}/handoff", json=body).status_code == 409
    assert client.put(path, json=body, headers={"Origin": "https://other.test"}).status_code == 403
    assert client.put(path, json={**body, "operator_id": "forged"}).status_code == 422
    assert client.get(f"{url}/handoffs").json() == []

    client.app.dependency_overrides[require_operator] = lambda: OperatorIdentity(
        id="1" * 32, username="another-operator",
    )
    assert client.get(f"{url}/handoffs").status_code == 404
    assert client.put(path, json=body).status_code == 404
    assert client.put(f"{path}/resolution", json={"resolution": "越权"}).status_code == 404


@pytest.mark.parametrize(("text", "action", "risks"), [
    ("这门课多少钱？", "clarify_product", []),
    ("请帮我退款。", "human_handoff", ["refund_request"]),
    ("我要投诉！", "human_handoff", ["complaint"]),
    ("我被重复扣款了。", "human_handoff", ["payment_dispute"]),
    ("如果我被重复扣款，应该找谁？", "clarify_product", []),
])
def test_no_product_routes_before_model_and_persists_snapshot(client, monkeypatch, text, action, risks):
    runtime = client.app.state.runtime

    def unexpected_call(*args, **kwargs):
        pytest.fail("固定路由不需要查询资料或调用模型")

    monkeypatch.setattr(runtime.gateway, "request_product_tool", unexpected_call)
    monkeypatch.setattr(runtime.gateway, "generate", unexpected_call)
    monkeypatch.setattr(runtime.tool_executor, "execute", unexpected_call)
    monkeypatch.setattr(runtime.repository, "get_current_published_product", unexpected_call)
    url = conversation(client)
    source = message(client, url, text=text)
    body = {"based_on_version": 1}
    preview = client.post(f"{url}/reply-preview", json=body)
    assert preview.status_code == 200
    assert preview.json()["routing"]["action"] == action
    assert preview.json()["routing"]["risk_flags"] == risks
    assert preview.json()["source_message_id"] == source
    assert preview.json()["retrieved_knowledge"] is None

    request = {**body, "request_key": "rule"}
    saved = client.post(f"{url}/suggestions", json=request)
    assert saved.status_code == 201
    assert saved.json()["product_id"] is None
    snapshot = saved.json()["generation_snapshot"]
    for field in ("reply", "routing", "retrieved_knowledge", "source_message_id"):
        assert snapshot[field] == preview.json()[field]
    retry = client.post(f"{url}/suggestions", json={**request, "product_id": None})
    assert retry.status_code == 200
    assert retry.json()["id"] == saved.json()["id"]
    suggestion_id = saved.json()["id"]
    assert client.post(f"{url}/suggestions/{suggestion_id}/copy-ready").status_code == 200
    assert client.get(f"{url}/handoffs").json() == []


@pytest.mark.parametrize(("topic", "text", "cue"), [
    ("complaint", "我反馈过多次服务问题，请帮我正式提交投诉。", "人工客服进一步核实"),
    ("payment_dispute", "报名付款页面刷新了，卡上出现了两笔扣款。", "核实订单和付款记录"),
])
def test_model_risk_topics_override_price(client, monkeypatch, topic, text, cue):
    runtime = client.app.state.runtime

    def generate(*, product, **kwargs):
        return ModelPlan(
            draft=ReplyDraft(
                topics=["price", topic],
                knowledge_id=product.knowledge_id,
                knowledge_revision=product.revision,
            ),
            model_name="mock-risk",
            mode="mock",
        )

    monkeypatch.setattr(runtime.gateway, "generate", generate)
    url = conversation(client)
    message(client, url, text=text)
    response = client.post(f"{url}/reply-preview", json={
        "based_on_version": 1, "product_id": "demo_python_basic",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["routing"] == {
        "intents": ["price", topic],
        "risk_flags": [topic],
        "action": "human_handoff",
        "handoff_reason": topic,
    }
    assert cue in data["reply"]["text"]
    assert "199.00" not in data["reply"]["text"]
    assert client.get(f"{url}/handoffs").json() == []
