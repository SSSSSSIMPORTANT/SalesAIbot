def create_conversation(client):
    response = client.post(
        "/conversations",
        json={"customer_name": "合成测试客户"},
    )

    assert response.status_code == 201
    return response.json()["id"]


def test_retry_does_not_duplicate_message(client):
    conversation_id = create_conversation(client)
    url = f"/conversations/{conversation_id}/messages"

    body = {
        "request_key": "request-001",
        "based_on_version": 0,
        "actor": "customer",
        "text": "我想了解课程价格",
    }

    first = client.post(url, json=body)
    retry = client.post(url, json=body)

    assert first.status_code == 201
    assert retry.status_code == 200
    assert first.json() == retry.json()

    history = client.get(url)

    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["text"] == body["text"]


def test_same_key_with_different_content_returns_conflict(client):
    conversation_id = create_conversation(client)
    url = f"/conversations/{conversation_id}/messages"

    body = {
        "request_key": "request-001",
        "based_on_version": 0,
        "actor": "customer",
        "text": "我想了解课程价格",
    }

    first = client.post(url, json=body)
    assert first.status_code == 201

    changed_body = {
        **body,
        "text": "可以试听吗？",
    }

    conflict = client.post(url, json=changed_body)

    assert conflict.status_code == 409

    history = client.get(url)

    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["text"] == body["text"]

def test_stale_version_is_rejected(client):
    conversation_id = create_conversation(client)
    conversation_url = f"/conversations/{conversation_id}"
    messages_url = f"{conversation_url}/messages"

    first_body = {
        "request_key": "request-001",
        "based_on_version": 0,
        "actor": "customer",
        "text": "我想了解课程价格",
    }

    first = client.post(messages_url, json=first_body)
    assert first.status_code == 201
    assert client.get(conversation_url).json()["version"] == 1

    # 模拟另一个页面仍基于旧版本提交。
    second_body = {
        "request_key": "request-002",
        "based_on_version": 0,
        "actor": "customer",
        "text": "可以试听吗？",
    }

    stale = client.post(messages_url, json=second_body)

    assert stale.status_code == 409
    assert client.get(conversation_url).json()["version"] == 1
    assert len(client.get(messages_url).json()) == 1

    # 已成功请求的重试，仍返回原消息，版本保持不变。
    retry = client.post(messages_url, json=first_body)

    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert client.get(conversation_url).json()["version"] == 1

    # 模拟刷新并核对后，基于最新版本重新提交。
    second_body["based_on_version"] = 1

    second = client.post(messages_url, json=second_body)

    assert second.status_code == 201
    assert client.get(conversation_url).json()["version"] == 2
    assert len(client.get(messages_url).json()) == 2