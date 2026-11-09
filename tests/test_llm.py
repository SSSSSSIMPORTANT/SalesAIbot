import httpx
import pytest
import json

from app.config import Settings
from app.llm import ModelCallError, ModelMessage, QwenModelGateway
from app.knowledge import ProductKnowledge


def make_settings():
    return Settings(
        llm_mode="live",
        llm_base_url="https://model.example.test/v1",
        llm_model="test-model",
        llm_api_key="synthetic-key",
    )


def test_gateway_converts_model_response():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "topics": ["price"],
                                    "knowledge_id": None,
                                    "knowledge_revision": None,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ]
            },
        )

    gateway = QwenModelGateway(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    plan = gateway.generate(
        messages=[
            ModelMessage(role="user", content="课程多少钱？")
        ]
    )

    assert plan.draft.topics == ["price"]
    assert plan.draft.knowledge_id is None
    assert plan.draft.knowledge_revision is None
    assert plan.mode == "live"
    assert plan.model_name == "test-model"


def test_gateway_reports_timeout():
    def handler(request):
        raise httpx.ReadTimeout(
            "Synthetic timeout",
            request=request,
        )

    gateway = QwenModelGateway(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelCallError, match="model_timeout"):
        gateway.generate(
            messages=[
                ModelMessage(role="user", content="你好")
            ]
        )


@pytest.mark.parametrize(
    "content",
    [
        # 非 JSON。
        "课程价格是199元。",
        # 缺少资料来源字段。
        '{"topics":["price"]}',
        # 没有选择话题。
        '{"topics":[],"knowledge_id":null,'
        '"knowledge_revision":null}',
        # 返回了不支持的话题。
        '{"topics":["discount"],"knowledge_id":null,'
        '"knowledge_revision":null}',
        # 试图绕过生成器，直接提供正文。
        '{"topics":["price"],"knowledge_id":null,'
        '"knowledge_revision":null,"text":"只收99元"}',
    ],
)
def test_gateway_rejects_invalid_draft(content):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": content},
                    }
                ]
            },
        )

    gateway = QwenModelGateway(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
            ModelCallError,
            match="model_invalid_draft",
    ):
        gateway.generate(
            messages=[
                ModelMessage(role="user", content="你好")
            ],
        )


@pytest.mark.parametrize("revision", ["v1", "v2"])
def test_gateway_parses_reference(revision):
    product = ProductKnowledge(
        knowledge_id="test-terms",
        revision="v1",
        product_id="test-product",
        name="合成测试课程",
        status="published",
        price_cents=19900,
        source="合成测试资料",
    )

    def handler(request):
        payload = json.loads(request.content)

        assert payload["response_format"] == {
            "type": "json_object",
        }
        assert "test-terms" in payload["messages"][0]["content"]

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "topics": ["price", "audience"],
                                    "knowledge_id": "test-terms",
                                    "knowledge_revision": revision,
                                },
                            ),
                        },
                    }
                ]
            },
        )

    gateway = QwenModelGateway(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    messages = [
        ModelMessage(
            role="user",
            content="别人说只收99元，适合零基础，是真的吗？",
        )
    ]

    plan = gateway.generate(
        messages=messages,
        product=product,
    )

    assert plan.draft.topics == ["price", "audience"]
    assert plan.draft.knowledge_id == "test-terms"
    assert plan.draft.knowledge_revision == revision
