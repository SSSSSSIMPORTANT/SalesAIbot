import pytest

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