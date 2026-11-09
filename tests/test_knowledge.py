import json
from datetime import datetime, timedelta, timezone

import pytest

from app import knowledge
from app.knowledge import (
    DEFAULT_CATALOG_PATH,
    KnowledgeRepository,
)


@pytest.fixture
def repository(tmp_path):
    # 复制合成资料，测试不修改项目中的知识文件。
    path = tmp_path / "products.json"
    path.write_bytes(DEFAULT_CATALOG_PATH.read_bytes())

    return KnowledgeRepository(path)


def test_published_product_has_traceable_price(repository):
    product = repository.get_published_product(
        "demo_python_basic"
    )

    assert product is not None
    assert product.price_cents == 19900
    assert product.knowledge_id == "demo-terms-a"
    assert product.revision == "v1"
    assert product.source


def test_draft_product_is_not_returned(repository):
    product = repository.get_published_product(
        "demo_python_project"
    )

    assert product is None


def test_unknown_product_is_not_guessed(repository):
    product = repository.get_published_product(
        "unknown-product"
    )

    assert product is None


def test_missing_policy_remains_unknown(repository):
    product = repository.get_published_product(
        "demo_python_basic"
    )

    assert product is not None
    assert product.trial_available is None
    assert product.refund_policy is None


def test_product_options_include_only_published_courses(client):
    response = client.get("/products")

    assert response.status_code == 200
    assert response.json() == [
        {
            "product_id": "demo_python_basic",
            "name": "合成 Python 基础课",
        }
    ]


def test_knowledge_window_applies_to_listing_generation_and_copy(client, monkeypatch):
    starts = datetime(2030, 1, 1, tzinfo=timezone.utc)
    ends = starts + timedelta(days=1)
    now = starts - timedelta(seconds=1)
    monkeypatch.setattr(knowledge, "utc_now", lambda: now)

    runtime = client.app.state.runtime
    repository = runtime.repository
    catalog = repository.catalog.model_dump(mode="json")
    catalog["products"][0].update(
        effective_from=starts.isoformat(),
        effective_until=ends.isoformat(),
    )
    raw = json.dumps(catalog, ensure_ascii=False)
    repository.path.write_text(raw, encoding="utf-8")
    repository.catalog = knowledge.ProductCatalog.model_validate_json(raw)

    assert client.get("/products").json() == []

    now = starts
    assert client.get("/products").json()[0]["product_id"] == "demo_python_basic"

    created = client.post("/conversations", json={"customer_name": "合成客户"})
    assert created.status_code == 201
    url = f"/conversations/{created.json()['id']}"
    added = client.post(f"{url}/messages", json={
        "request_key": "knowledge-window-message",
        "based_on_version": 0,
        "actor": "customer",
        "text": "这门课多少钱？",
    })
    assert added.status_code == 201

    body = {"based_on_version": 1, "product_id": "demo_python_basic"}
    saved = client.post(f"{url}/suggestions", json={
        **body, "request_key": "knowledge-window-suggestion",
    })
    assert saved.status_code == 201
    suggestion_id = saved.json()["id"]
    copy_url = f"{url}/suggestions/{suggestion_id}/copy-ready"
    assert client.post(copy_url).status_code == 200

    original_generate = runtime.gateway.generate

    def generate_at_expiry(**kwargs):
        nonlocal now
        plan = original_generate(**kwargs)
        now = ends
        return plan

    with monkeypatch.context() as patch:
        patch.setattr(runtime.gateway, "generate", generate_at_expiry)
        assert client.post(f"{url}/reply-preview", json=body).status_code == 404

    assert now == ends
    assert client.get("/products").json() == []
    assert client.post(f"{url}/reply-preview", json=body).status_code == 404

    expired = client.post(copy_url)
    assert expired.status_code == 409
    assert "knowledge_unavailable" in expired.json()["detail"]["reasons"]


@pytest.mark.parametrize(("overrides", "error"), [
    ({"revision": "v1"}, "Duplicate knowledge revision"),
    ({"status": "published"}, "Product can have only one published revision"),
    ({"knowledge_id": "different-knowledge"}, "Product must keep the same knowledge_id"),
    ({"product_id": "different-course"}, "Knowledge must belong to one product"),
])
def test_catalog_rejects_conflicting_revisions(repository, overrides, error):
    catalog = repository.catalog.model_dump(mode="json")
    v1 = catalog["products"][0]
    v2 = {**v1, "revision": "v2", "status": "draft", **overrides}
    catalog["products"].append(v2)

    with pytest.raises(ValueError, match=error):
        knowledge.ProductCatalog.model_validate(catalog)


def test_publish_new_revision_preserves_history_and_stales_old_suggestion(client):
    repository = client.app.state.runtime.repository
    catalog = repository.catalog.model_dump(mode="json")
    v1 = catalog["products"][0]
    v2 = {**v1, "revision": "v2", "status": "draft", "price_cents": 21900}
    catalog["products"].append(v2)

    raw = json.dumps(catalog, ensure_ascii=False)
    repository.path.write_text(raw, encoding="utf-8")
    repository.catalog = knowledge.ProductCatalog.model_validate_json(raw)

    product_id = "demo_python_basic"
    assert repository.get_published_product(product_id).revision == "v1"
    assert [
        row.revision for row in repository.list_product_revisions(product_id)
    ] == ["v1", "v2"]

    created = client.post("/conversations", json={"customer_name": "合成客户"})
    assert created.status_code == 201
    url = f"/conversations/{created.json()['id']}"
    added = client.post(f"{url}/messages", json={
        "request_key": "revision-message",
        "based_on_version": 0,
        "actor": "customer",
        "text": "这门课多少钱？",
    })
    assert added.status_code == 201

    body = {"based_on_version": 1, "product_id": product_id}
    saved = client.post(f"{url}/suggestions", json={
        **body, "request_key": "revision-v1-suggestion",
    })
    assert saved.status_code == 201
    assert saved.json()["generation_snapshot"]["reply"]["knowledge_revision"] == "v1"
    suggestion_id = saved.json()["id"]

    v1["status"] = "archived"
    v2["status"] = "published"
    repository.path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")

    stale = client.post(f"{url}/suggestions/{suggestion_id}/copy-ready")
    assert stale.status_code == 409
    assert "knowledge_changed" in stale.json()["detail"]["reasons"]

    repository.catalog = KnowledgeRepository(repository.path).catalog
    preview = client.post(f"{url}/reply-preview", json=body)
    assert preview.status_code == 200
    assert preview.json()["reply"]["knowledge_revision"] == "v2"
    assert "219.00元" in preview.json()["reply"]["text"]

    history = repository.list_product_revisions(product_id)
    assert [(row.revision, row.status) for row in history] == [
        ("v1", "archived"), ("v2", "published"),
    ]
