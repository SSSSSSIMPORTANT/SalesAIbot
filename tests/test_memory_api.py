import pytest
from app.llm import MockModelGateway, ModelCallError
from app.memory_candidates import MemoryCandidate, MemoryCandidateBatch


def create_source(client, *, actor="customer"):
    created = client.post(
        "/conversations",
        json={"customer_name": "合成记忆测试客户"},
    )
    assert created.status_code == 201

    conversation_id = created.json()["id"]
    url = f"/conversations/{conversation_id}"

    submitted = client.post(
        f"{url}/messages",
        json={
            "request_key": "memory-source",
            "based_on_version": 0,
            "actor": actor,
            "text": "我没有编程基础。",
        },
    )
    assert submitted.status_code == 201

    return url, submitted.json()["id"]


def test_saved_fact_is_recalled_and_old_version_is_rejected(client):
    url, source_id = create_source(client)

    body = {
        "based_on_version": 1,
        "fact_key": "current_level",
        "value": "没有编程基础",
        "source_message_id": source_id,
    }

    saved = client.post(f"{url}/facts", json=body)

    assert saved.status_code == 201
    fact_id = saved.json()["id"]
    assert client.get(url).json()["version"] == 2

    # 原版本不能再次保存，也不能产生新记录。
    stale = client.post(f"{url}/facts", json=body)
    assert stale.status_code == 409
    assert client.get(url).json()["version"] == 2

    facts = client.get(f"{url}/facts")
    assert facts.status_code == 200
    assert [fact["id"] for fact in facts.json()] == [fact_id]

    preview = client.post(
        f"{url}/reply-preview",
        json={
            "based_on_version": 2,
            "product_id": "demo_python_basic",
        },
    )
    assert preview.status_code == 200

    recalled = preview.json()["recalled_memory"]
    assert recalled[0]["id"] == fact_id
    assert recalled[0]["value"] == "没有编程基础"

    # 保存记忆和生成草稿都不增加实际聊天消息。
    assert len(client.get(f"{url}/messages").json()) == 1


@pytest.mark.parametrize(
    "case",
    [
        "other_conversation",
        "human_source",
        "blank_value",
        "unsupported_value",
    ],
)
def test_invalid_fact_does_not_change_memory_or_version(client, case):
    url, source_id = create_source(
        client,
        actor="human" if case == "human_source" else "customer",
    )

    if case == "other_conversation":
        _, source_id = create_source(client)

    response = client.post(
        f"{url}/facts",
        json={
            "based_on_version": 1,
            "fact_key": "current_level",
            "value": (
                "   "
                if case == "blank_value"
                else (
                    "每周学习四十小时"
                    if case == "unsupported_value"
                    else "没有编程基础"
                )
            ),
            "source_message_id": source_id,
        },
    )

    assert response.status_code == 422
    assert client.get(f"{url}/facts").json() == []
    assert client.get(url).json()["version"] == 1

@pytest.mark.parametrize(
    ("case", "expected_status", "expected_calls"),
    [
        ("valid", 200, 1),
        ("stale", 409, 0),
        ("human_source", 422, 0),
        ("other_conversation", 404, 0),
        ("missing_source", 404, 0),
        ("changed", 409, 1),
        ("timeout", 503, 1),
    ],
)
def test_extract_memory_candidates(
    client,
    monkeypatch,
    case,
    expected_status,
    expected_calls,
):
    url, source_id = create_source(
        client,
        actor="human" if case == "human_source" else "customer",
    )

    if case == "other_conversation":
        _, source_id = create_source(client)
    elif case == "missing_source":
        source_id = 999999

    calls = []

    def fake_extract(self, *, source_text):
        calls.append(source_text)

        if case == "timeout":
            raise ModelCallError("model_timeout")

        if case == "changed":
            # 模拟模型等待期间，有人补录了新消息。
            added = client.post(
                f"{url}/messages",
                json={
                    "request_key": "during-extraction",
                    "based_on_version": 1,
                    "actor": "customer",
                    "text": "补充一条新消息。",
                },
            )
            assert added.status_code == 201

        return MemoryCandidateBatch(
            candidates=[
                MemoryCandidate(
                    fact_key="current_level",
                    value=source_text,
                )
            ]
        )

    monkeypatch.setattr(
        MockModelGateway,
        "extract_memory_candidates",
        fake_extract,
    )

    response = client.post(
        f"{url}/memory-candidates",
        json={
            "based_on_version": 0 if case == "stale" else 1,
            "source_message_id": source_id,
        },
    )

    assert response.status_code == expected_status
    assert len(calls) == expected_calls

    # 候选提取不会保存确认事实。
    assert client.get(f"{url}/facts").json() == []

    # 只有模拟的新消息推进了版本。
    expected_version = 2 if case == "changed" else 1
    assert client.get(url).json()["version"] == expected_version

    if case == "valid":
        data = response.json()

        assert calls == ["我没有编程基础。"]
        assert data["source_message_id"] == source_id
        assert data["source_text"] == "我没有编程基础。"
        assert data["based_on_version"] == 1
        assert data["candidates"] == [
            {
                "fact_key": "current_level",
                "value": "我没有编程基础。",
            }
        ]


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("valid", 200),
        ("stale", 409),
        ("other_conversation", 404),
    ],
)
def test_revoke_fact(client, case, expected_status):
    url, source_id = create_source(client)

    saved = client.post(
        f"{url}/facts",
        json={
            "based_on_version": 1,
            "fact_key": "current_level",
            "value": "没有编程基础",
            "source_message_id": source_id,
        },
    )
    assert saved.status_code == 201
    fact_id = saved.json()["id"]

    target_url = url

    if case == "other_conversation":
        target_url, _ = create_source(client)

    response = client.post(
        f"{target_url}/facts/{fact_id}/revoke",
        json={
            "based_on_version": 1 if case == "stale" else 2,
        },
    )

    assert response.status_code == expected_status

    if case != "valid":
        assert client.get(url).json()["version"] == 2
        assert len(client.get(f"{url}/facts").json()) == 1
        return

    data = response.json()
    assert data["status"] == "revoked"
    assert data["revoked_at"] is not None
    assert data["source_message_id"] == source_id
    assert client.get(url).json()["version"] == 3
    assert client.get(f"{url}/facts").json() == []

    preview = client.post(
        f"{url}/reply-preview",
        json={
            "based_on_version": 3,
            "product_id": "demo_python_basic",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["recalled_memory"] == []

    # 即使用最新版本，也不能重复撤销。
    repeated = client.post(
        f"{url}/facts/{fact_id}/revoke",
        json={"based_on_version": 3},
    )
    assert repeated.status_code == 409
    assert client.get(url).json()["version"] == 3