import pytest
from app.llm import MockModelGateway

def create_customer(client):
    response = client.post(
        "/customers",
        json={"display_name": "同名合成客户"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def create_conversation(client, customer_id):
    body = (
        {"customer_id": customer_id}
        if customer_id is not None
        else {"customer_name": "同名合成客户"}
    )

    response = client.post("/conversations", json=body)
    assert response.status_code == 201

    return f"/conversations/{response.json()['id']}"


def save_level(client, url, value):
    submitted = client.post(
        f"{url}/messages",
        json={
            "request_key": "recall-source",
            "based_on_version": 0,
            "actor": "customer",
            "text": value,
        },
    )
    assert submitted.status_code == 201

    saved = client.post(
        f"{url}/facts",
        json={
            "based_on_version": 1,
            "fact_key": "current_level",
            "value": value,
            "source_message_id": submitted.json()["id"],
        },
    )
    assert saved.status_code == 201

    return saved.json()["id"]


@pytest.mark.parametrize(
    "case",
    [
        "same_value",
        "different_value",
        "other_customer",
        "unassigned",
        "revoked",
    ],
)
def test_cross_conversation_memory(client, case):
    first_customer = (
        None if case == "unassigned"
        else create_customer(client)
    )

    second_customer = first_customer

    if case == "other_customer":
        second_customer = create_customer(client)

    first_url = create_conversation(client, first_customer)
    second_url = create_conversation(client, second_customer)

    first_fact_id = save_level(
        client,
        first_url,
        "我没有编程基础",
    )

    second_fact_id = save_level(
        client,
        second_url,
        (
            "我已经学过 Python"
            if case == "different_value"
            else "我没有编程基础"
        ),
    )

    if case == "revoked":
        response = client.post(
            f"{second_url}/facts/{second_fact_id}/revoke",
            json={"based_on_version": 2},
        )
        assert response.status_code == 200

    before = client.get(first_url).json()["version"]

    response = client.get(f"{first_url}/memory-recall")
    assert response.status_code == 200
    data = response.json()

    if case == "different_value":
        assert data["recalled_memory"] == []
        assert len(data["conflicts"]) == 1

        conflict = data["conflicts"][0]
        assert conflict["fact_key"] == "current_level"
        assert {
            fact["id"] for fact in conflict["alternatives"]
        } == {first_fact_id, second_fact_id}
    else:
        assert data["conflicts"] == []

        expected_ids = (
            {first_fact_id, second_fact_id}
            if case == "same_value"
            else {first_fact_id}
        )

        assert {
            fact["id"] for fact in data["recalled_memory"]
        } == expected_ids

    # 查询不推进会话版本。
    assert client.get(first_url).json()["version"] == before


def test_recall_unknown_conversation(client):
    response = client.get(
        "/conversations/unknown-conversation/memory-recall"
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "case",
    [
        "recall",
        "conflict",
        "revoke_during_generation",
        "replace_during_generation",
        "unrelated_customer_change",
    ],
)
def test_reply_uses_current_customer_memory(
    client,
    monkeypatch,
    case,
):
    customer_id = create_customer(client)
    source_url = create_conversation(client, customer_id)
    target_url = create_conversation(client, customer_id)

    fact_id = save_level(
        client,
        source_url,
        "我没有编程基础",
    )

    if case == "conflict":
        save_level(
            client,
            target_url,
            "我已经学过 Python",
        )
    else:
        submitted = client.post(
            f"{target_url}/messages",
            json={
                "request_key": "target-question",
                "based_on_version": 0,
                "actor": "customer",
                "text": "这门课程适合我吗？",
            },
        )
        assert submitted.status_code == 201

    unrelated_url = None
    unrelated_fact_id = None

    if case == "unrelated_customer_change":
        other_customer = create_customer(client)
        unrelated_url = create_conversation(
            client,
            other_customer,
        )
        unrelated_fact_id = save_level(
            client,
            unrelated_url,
            "我没有编程基础",
        )

    source_message_id = client.get(
        f"{source_url}/messages"
    ).json()[0]["id"]

    captured = []
    original_generate = MockModelGateway.generate

    def recording_generate(self, **kwargs):
        captured.extend(kwargs["memories"])

        if case == "revoke_during_generation":
            changed = client.post(
                f"{source_url}/facts/{fact_id}/revoke",
                json={"based_on_version": 2},
            )
            assert changed.status_code == 200

        elif case == "replace_during_generation":
            changed = client.post(
                f"{source_url}/facts",
                json={
                    "based_on_version": 2,
                    "fact_key": "current_level",
                    "value": "没有编程基础",
                    "source_message_id": source_message_id,
                },
            )
            assert changed.status_code == 201

        elif case == "unrelated_customer_change":
            changed = client.post(
                (
                    f"{unrelated_url}/facts/"
                    f"{unrelated_fact_id}/revoke"
                ),
                json={"based_on_version": 2},
            )
            assert changed.status_code == 200

        return original_generate(self, **kwargs)

    monkeypatch.setattr(
        MockModelGateway,
        "generate",
        recording_generate,
    )

    version = client.get(target_url).json()["version"]

    response = client.post(
        f"{target_url}/reply-preview",
        json={
            "based_on_version": version,
            "product_id": "demo_python_basic",
        },
    )

    # 模型运行期间没有向目标会话添加消息。
    assert client.get(target_url).json()["version"] == version

    if case in {
        "revoke_during_generation",
        "replace_during_generation",
    }:
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Customer memory changed while generating"
        )
        assert [item.id for item in captured] == [fact_id]
        return

    assert response.status_code == 200
    data = response.json()

    if case == "conflict":
        assert captured == []
        assert data["recalled_memory"] == []

        conflicts = data["memory_conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["fact_key"] == "current_level"
        assert len(conflicts[0]["alternatives"]) == 2
    else:
        assert [item.id for item in captured] == [fact_id]
        assert data["recalled_memory"][0]["id"] == fact_id
        assert data["recalled_memory"][0]["conversation_id"] == (
            source_url.rsplit("/", 1)[-1]
        )
        assert data["memory_conflicts"] == []