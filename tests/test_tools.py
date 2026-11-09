import pytest

from app.knowledge import DEFAULT_CATALOG_PATH, KnowledgeRepository
from app.tools import SalesToolExecutor, ToolExecutionError


@pytest.fixture
def executor(tmp_path):
    path = tmp_path / "products.json"
    path.write_bytes(DEFAULT_CATALOG_PATH.read_bytes())

    return SalesToolExecutor(KnowledgeRepository(path))


def test_tool_returns_published_knowledge(executor):
    product = executor.execute(
        name="get_product_knowledge",
        arguments={"product_id": "demo_python_basic"},
    )

    assert product is not None
    assert product.status == "published"
    assert product.price_cents == 19900
    assert product.knowledge_id == "demo-terms-a"


@pytest.mark.parametrize(
    "product_id",
    ["demo_python_project", "unknown-product"],
)
def test_tool_does_not_expose_unpublished_knowledge(
    executor,
    product_id,
):
    product = executor.execute(
        name="get_product_knowledge",
        arguments={"product_id": product_id},
    )

    assert product is None


@pytest.mark.parametrize(
    ("name", "arguments", "error"),
    [
        (
            "send_message",
            {"product_id": "demo_python_basic"},
            "unknown_tool",
        ),
        (
            "get_product_knowledge",
            {},
            "invalid_tool_arguments",
        ),
        (
            "get_product_knowledge",
            {"product_id": "   "},
            "invalid_tool_arguments",
        ),
        (
            "get_product_knowledge",
            {"product_id": 123},
            "invalid_tool_arguments",
        ),
        (
            "get_product_knowledge",
            {
                "product_id": "demo_python_basic",
                "discount": True,
            },
            "invalid_tool_arguments",
        ),
    ],
)
def test_invalid_requests_never_reach_repository(
    executor,
    monkeypatch,
    name,
    arguments,
    error,
):
    def unexpected_lookup(product_id):
        pytest.fail("不合法的工具请求不应该触发查询")

    monkeypatch.setattr(
        executor.repository,
        "get_published_product",
        unexpected_lookup,
    )

    with pytest.raises(ToolExecutionError, match=error):
        executor.execute(
            name=name,
            arguments=arguments,
        )


def test_tool_definition_describes_required_arguments(executor):
    definitions = executor.definitions()

    assert len(definitions) == 1

    function = definitions[0]["function"]
    parameters = function["parameters"]

    assert function["name"] == "get_product_knowledge"
    assert parameters["required"] == ["product_id"]
    assert parameters["additionalProperties"] is False