from pathlib import Path

import pytest
from sqlalchemy import event, func, select

from app.database import ReplySuggestion, SuggestionGenerationRequest, get_db
from app.llm import MockModelGateway, ModelCallError
from app.schemas.suggestions import CreateSuggestionRequest
from app.services.generation_requests import (
    claim_generation,
    mark_generation_failed,
)
from scripts import recover_generation_request


@pytest.fixture
def db(client):
    # 与 HTTP 请求使用同一个临时数据库，但使用独立 Session。
    yield from client.app.dependency_overrides[get_db]()


@pytest.fixture
def model_calls(monkeypatch):
    calls = {"request_product_tool": 0, "generate": 0}
    original_tool = MockModelGateway.request_product_tool
    original_generate = MockModelGateway.generate

    def count_tool(self, **kwargs):
        calls["request_product_tool"] += 1
        return original_tool(self, **kwargs)

    def count_generate(self, **kwargs):
        calls["generate"] += 1
        return original_generate(self, **kwargs)

    monkeypatch.setattr(MockModelGateway, "request_product_tool", count_tool)
    monkeypatch.setattr(MockModelGateway, "generate", count_generate)
    return calls


def prepare(client):
    created = client.post(
        "/conversations", json={"customer_name": "合成生成幂等测试客户"}
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    url = f"/conversations/{conversation_id}"
    added = client.post(
        f"{url}/messages",
        json={
            "request_key": "source-001",
            "based_on_version": 0,
            "actor": "customer",
            "text": "课程多少钱？",
        },
    )
    assert added.status_code == 201
    return conversation_id, url


def generation_body(**changes):
    body = {
        "request_key": "generate-001",
        "based_on_version": 1,
        "product_id": "demo_python_basic",
    }
    body.update(changes)
    return body


def test_success_retry_returns_same_suggestion_without_model(
    client, db, model_calls
):
    conversation_id, url = prepare(client)
    first = client.post(f"{url}/suggestions", json=generation_body())
    retry = client.post(f"{url}/suggestions", json=generation_body())

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert model_calls == {"request_product_tool": 1, "generate": 1}
    assert client.get(url).json()["version"] == 1
    assert len(client.get(f"{url}/messages").json()) == 1
    assert len(client.get(f"{url}/suggestions").json()) == 1

    row = db.get(SuggestionGenerationRequest, (conversation_id, "generate-001"))
    assert row.status == "succeeded"
    assert row.suggestion_id == first.json()["id"]
    assert row.error_code is None
    assert row.finished_at is not None


def test_success_retry_survives_later_changes_but_copy_is_checked(
    client, db, model_calls
):
    conversation_id, url = prepare(client)
    first = client.post(f"{url}/suggestions", json=generation_body())
    assert first.status_code == 201
    added = client.post(
        f"{url}/messages",
        json={
            "request_key": "source-002",
            "based_on_version": 1,
            "actor": "customer",
            "text": "我补充一个问题。",
        },
    )
    assert added.status_code == 201

    retry = client.post(f"{url}/suggestions", json=generation_body())
    assert retry.status_code == 200
    assert retry.json() == first.json()

    ready = client.post(f"{url}/suggestions/{first.json()['id']}/copy-ready")
    assert ready.status_code == 409
    assert ready.json()["detail"]["code"] == "suggestion_stale"

    # 新 key 发起新操作，必须通过当前版本校验。
    stale = client.post(
        f"{url}/suggestions", json=generation_body(request_key="generate-002")
    )
    assert stale.status_code == 409
    assert model_calls == {"request_product_tool": 1, "generate": 1}
    assert db.get(
        SuggestionGenerationRequest, (conversation_id, "generate-002")
    ) is None


@pytest.mark.parametrize(
    "changes", [{"based_on_version": 2}, {"product_id": "another-product"}]
)
def test_changed_input_cannot_reuse_success_key(client, model_calls, changes):
    _, url = prepare(client)
    first = client.post(f"{url}/suggestions", json=generation_body())
    assert first.status_code == 201

    conflict = client.post(f"{url}/suggestions", json=generation_body(**changes))
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "generation_request_mismatch"

    retry = client.post(f"{url}/suggestions", json=generation_body())
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert model_calls == {"request_product_tool": 1, "generate": 1}


def test_duplicate_during_generation_does_not_fail_original_request(
    client, db, model_calls, monkeypatch
):
    conversation_id, url = prepare(client)
    original = MockModelGateway.request_product_tool

    def duplicate_during_model_call(self, **kwargs):
        duplicate = client.post(f"{url}/suggestions", json=generation_body())
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "generation_in_progress"
        return original(self, **kwargs)

    monkeypatch.setattr(
        MockModelGateway, "request_product_tool", duplicate_during_model_call
    )
    first = client.post(f"{url}/suggestions", json=generation_body())

    assert first.status_code == 201
    assert model_calls == {"request_product_tool": 1, "generate": 1}
    row = db.get(SuggestionGenerationRequest, (conversation_id, "generate-001"))
    assert row.status == "succeeded"
    assert row.suggestion_id == first.json()["id"]


@pytest.mark.parametrize("stage", ["request_product_tool", "generate"])
def test_model_failure_is_recorded_and_same_key_does_not_retry(
    client, db, model_calls, monkeypatch, stage
):
    conversation_id, url = prepare(client)
    original = getattr(MockModelGateway, stage)

    def fail(self, **kwargs):
        model_calls[stage] += 1
        raise ModelCallError("model_timeout")

    monkeypatch.setattr(MockModelGateway, stage, fail)
    first = client.post(f"{url}/suggestions", json=generation_body())
    assert first.status_code == 503
    detail = first.json()["detail"]
    assert detail["code"] == "model_timeout"
    assert detail["routing"]["action"] == "human_handoff"
    assert detail["routing"]["handoff_reason"] == "model_unavailable"
    assert detail["source_message_id"] == client.get(f"{url}/messages").json()[-1]["id"]
    counts_after_failure = dict(model_calls)

    retry = client.post(f"{url}/suggestions", json=generation_body())
    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "generation_failed"
    assert model_calls == counts_after_failure
    assert client.get(f"{url}/suggestions").json() == []

    row = db.get(SuggestionGenerationRequest, (conversation_id, "generate-001"))
    assert row.status == "failed"
    assert row.error_code == "model_timeout"
    assert row.suggestion_id is None
    assert row.finished_at is not None
    db.rollback()

    # 恢复模型后，用户明确用新 key 发起另一次尝试。
    monkeypatch.setattr(MockModelGateway, stage, original)
    new_attempt = client.post(
        f"{url}/suggestions", json=generation_body(request_key="generate-002")
    )
    assert new_attempt.status_code == 201
    assert len(client.get(f"{url}/suggestions").json()) == 1
    assert db.get(
        SuggestionGenerationRequest, (conversation_id, "generate-001")
    ).status == "failed"
    assert db.get(
        SuggestionGenerationRequest, (conversation_id, "generate-002")
    ).status == "succeeded"


def test_conversation_change_during_generation_records_failure(
    client, db, monkeypatch
):
    conversation_id, url = prepare(client)
    original = MockModelGateway.generate

    def change_conversation(self, **kwargs):
        added = client.post(
            f"{url}/messages",
            json={
                "request_key": "during-generation",
                "based_on_version": 1,
                "actor": "customer",
                "text": "生成期间补充的信息。",
            },
        )
        assert added.status_code == 201
        return original(self, **kwargs)

    monkeypatch.setattr(MockModelGateway, "generate", change_conversation)
    response = client.post(f"{url}/suggestions", json=generation_body())

    assert response.status_code == 409
    assert client.get(f"{url}/suggestions").json() == []
    row = db.get(SuggestionGenerationRequest, (conversation_id, "generate-001"))
    assert row.status == "failed"
    assert row.error_code == "generation_http_409"
    assert row.suggestion_id is None


def test_suggestion_and_success_state_are_atomic(client, db):
    conversation_id, url = prepare(client)
    observed = []
    engine = db.get_bind()

    def fail_success_update(connection, cursor, statement, parameters, context, many):
        if (
            statement.startswith("UPDATE suggestion_generation_requests")
            and "succeeded" in parameters
        ):
            # 建议已经 INSERT，但还没有提交。
            observed.append(
                connection.scalar(select(func.count()).select_from(ReplySuggestion))
            )
            raise RuntimeError("synthetic private database failure")

    event.listen(engine, "before_cursor_execute", fail_success_update)
    try:
        response = client.post(f"{url}/suggestions", json=generation_body())
    finally:
        event.remove(engine, "before_cursor_execute", fail_success_update)

    assert response.status_code == 503
    assert response.json()["detail"] == "generation_internal_error"
    assert observed == [1]
    assert db.scalar(select(func.count()).select_from(ReplySuggestion)) == 0
    row = db.get(SuggestionGenerationRequest, (conversation_id, "generate-001"))
    assert row.status == "failed"
    assert row.suggestion_id is None
    assert row.error_code == "generation_internal_error"


@pytest.mark.parametrize("key", [None, "   "])
def test_generation_key_is_required(client, model_calls, key):
    _, url = prepare(client)
    body = generation_body(request_key=key)
    if key is None:
        body.pop("request_key")

    response = client.post(f"{url}/suggestions", json=body)

    assert response.status_code == 422
    assert model_calls == {"request_product_tool": 0, "generate": 0}


def test_lookup_success_without_calling_model(client, model_calls):
    conversation_id, url = prepare(client)
    key = "lookup/001?source=swagger"

    saved = client.post(
        f"{url}/suggestions",
        json=generation_body(request_key=key),
    )
    assert saved.status_code == 201

    lookup_url = f"{url}/generation-requests/by-key"
    response = client.get(
        lookup_url,
        params={"request_key": key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == conversation_id
    assert data["request_key"] == key
    assert data["based_on_version"] == 1
    assert data["product_id"] == "demo_python_basic"
    assert data["status"] == "succeeded"
    assert data["suggestion_id"] == saved.json()["id"]
    assert data["error_code"] is None
    assert data["started_at"] is not None
    assert data["finished_at"] is not None

    repeated = client.get(
        lookup_url,
        params={"request_key": key},
    )
    assert repeated.json() == data

    assert model_calls == {"request_product_tool": 1, "generate": 1}
    assert client.get(url).json()["version"] == 1
    assert len(client.get(f"{url}/messages").json()) == 1
    assert len(client.get(f"{url}/suggestions").json()) == 1


@pytest.mark.parametrize("status", ["running", "failed"])
def test_lookup_running_or_failed_request(
    client, db, model_calls, status
):
    _, url = prepare(client)
    conversation_id = url.rsplit("/", 1)[-1]
    body = CreateSuggestionRequest(**generation_body())

    claim_generation(conversation_id, body, db)

    if status == "failed":
        mark_generation_failed(
            conversation_id,
            body,
            db,
            error_code="generation_http_503",
        )

    response = client.get(
        f"{url}/generation-requests/by-key",
        params={"request_key": body.request_key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == status
    assert data["suggestion_id"] is None

    if status == "failed":
        assert data["error_code"] == "generation_http_503"
        assert data["finished_at"] is not None
    else:
        assert data["error_code"] is None
        assert data["finished_at"] is None

    assert model_calls == {"request_product_tool": 0, "generate": 0}
    assert client.get(f"{url}/suggestions").json() == []


def test_lookup_is_scoped_to_conversation(client, model_calls):
    _, first_url = prepare(client)
    _, second_url = prepare(client)

    saved = client.post(
        f"{first_url}/suggestions",
        json=generation_body(),
    )
    assert saved.status_code == 201

    for url, key in [
        (second_url, "generate-001"),
        (first_url, "unknown-key"),
        ("/conversations/missing", "generate-001"),
    ]:
        response = client.get(
            f"{url}/generation-requests/by-key",
            params={"request_key": key},
        )
        assert response.status_code == 404

    assert model_calls == {"request_product_tool": 1, "generate": 1}


@pytest.mark.parametrize("initial_status", ["running", "succeeded"])
def test_recovery_only_changes_running_requests(
    client, db, model_calls, monkeypatch, initial_status
):
    conversation_id, url = prepare(client)
    payload = generation_body()
    key = payload["request_key"]

    if initial_status == "running":
        claim_generation(
            conversation_id,
            CreateSuggestionRequest(**payload),
            db,
        )
    else:
        saved = client.post(f"{url}/suggestions", json=payload)
        assert saved.status_code == 201

    test_engine = db.get_bind()
    monkeypatch.setattr(recover_generation_request, "engine", test_engine)
    monkeypatch.setattr(
        recover_generation_request,
        "DATABASE_PATH",
        Path(test_engine.url.database),
    )

    args = [
        "--conversation-id", conversation_id,
        "--request-key", key,
    ]
    lookup_url = f"{url}/generation-requests/by-key"
    params = {"request_key": key}
    before = client.get(lookup_url, params=params).json()
    calls_before = dict(model_calls)

    assert recover_generation_request.main(args) == 0

    response = client.get(lookup_url, params=params)
    assert response.status_code == 200
    after = response.json()

    if initial_status == "running":
        assert after["status"] == "failed"
        assert after["error_code"] == "generation_interrupted"
        assert after["finished_at"] is not None
        assert after["suggestion_id"] is None
        assert client.get(f"{url}/suggestions").json() == []

        retry = client.post(f"{url}/suggestions", json=payload)
        assert retry.status_code == 409
        assert retry.json()["detail"]["code"] == "generation_failed"
    else:
        assert after == before

    # 再执行一次，保留第一次结束时的状态和时间。
    assert recover_generation_request.main(args) == 0
    assert client.get(lookup_url, params=params).json() == after
    assert model_calls == calls_before


def test_pause_blocks_new_generation_and_invalidates_old_suggestion(client, model_calls):
    _, url = prepare(client)
    original = generation_body()
    first = client.post(f"{url}/suggestions", json=original)
    assert first.status_code == 201
    draft_url = f"{url}/suggestions/{first.json()['id']}"
    calls_before_pause = dict(model_calls)

    paused = client.put(
        f"{url}/assistance",
        json={"based_on_version": 1, "suggestions_paused": True},
    )
    assert paused.status_code == 200
    assert paused.json()["suggestions_paused"] is True
    assert paused.json()["version"] == 2

    repeated = client.put(
        f"{url}/assistance",
        json={"based_on_version": 2, "suggestions_paused": True},
    )
    assert repeated.status_code == 200
    assert repeated.json()["version"] == 2

    stale_resume = client.put(
        f"{url}/assistance",
        json={"based_on_version": 1, "suggestions_paused": False},
    )
    assert stale_resume.status_code == 409

    preview = client.post(
        f"{url}/reply-preview",
        json={"based_on_version": 2, "product_id": "demo_python_basic"},
    )
    blocked = client.post(
        f"{url}/suggestions",
        json=generation_body(based_on_version=2, request_key="paused-001"),
    )
    for response in (preview, blocked):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "suggestions_paused"

    assert client.get(
        f"{url}/generation-requests/by-key", params={"request_key": "paused-001"}
    ).status_code == 404

    retry = client.post(f"{url}/suggestions", json=original)
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert model_calls == calls_before_pause

    copy = client.post(f"{draft_url}/copy-ready")
    assert copy.status_code == 409
    assert "suggestions_paused" in copy.json()["detail"]["reasons"]

    message = client.post(f"{url}/messages", json={
        "request_key": "while-paused", "based_on_version": 2,
        "actor": "customer", "text": "可以试听吗？",
    })
    assert message.status_code == 201
    assert client.get(url).json()["suggestions_paused"] is True

    resumed = client.put(
        f"{url}/assistance",
        json={"based_on_version": 3, "suggestions_paused": False},
    )
    assert resumed.status_code == 200
    assert resumed.json()["version"] == 4
    assert resumed.json()["suggestions_paused"] is False
    assert client.post(f"{draft_url}/copy-ready").status_code == 409

    fresh = client.post(
        f"{url}/suggestions",
        json=generation_body(based_on_version=4, request_key="resumed-001"),
    )
    assert fresh.status_code == 201


def test_pause_while_model_is_running_discards_the_result(client, monkeypatch):
    _, url = prepare(client)
    original_generate = MockModelGateway.generate

    def pause_during_generation(self, **kwargs):
        paused = client.put(
            f"{url}/assistance",
            json={"based_on_version": 1, "suggestions_paused": True},
        )
        assert paused.status_code == 200
        return original_generate(self, **kwargs)

    monkeypatch.setattr(MockModelGateway, "generate", pause_during_generation)

    response = client.post(f"{url}/suggestions", json=generation_body())
    assert response.status_code == 409
    assert client.get(f"{url}/suggestions").json() == []
    lookup = client.get(
        f"{url}/generation-requests/by-key", params={"request_key": "generate-001"}
    )
    assert lookup.status_code == 200
    assert lookup.json()["status"] == "failed"
