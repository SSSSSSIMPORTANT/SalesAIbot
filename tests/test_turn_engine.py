import pytest

from app.knowledge import ProductKnowledge
from app.llm import ModelMessage, ModelPlan, ReplyDraft
from app.services.turn_engine import (
    SalesTurnEngine,
    TurnValidationError,
)


class StubGateway:
    """直接提供指定计划，不请求网络。"""

    def __init__(self, revision):
        self.revision = revision
        self.calls = 0

    def generate(
            self,
            *,
            messages,
            product=None,
            tool_call=None,
            memories=(),
    ):
        self.calls += 1

        return ModelPlan(
            draft=ReplyDraft(
                topics=["price", "audience"],
                knowledge_id="test-terms",
                knowledge_revision=self.revision,
            ),
            model_name="stub",
            mode="mock",
        )


@pytest.mark.parametrize(
    ("status", "revision", "error"),
    [
        ("published", "v1", None),
        ("published", "v2", "model_knowledge_mismatch"),
        ("draft", "v1", "knowledge_not_published"),
    ],
)
def test_engine_enforces_business_rules(
    status,
    revision,
    error,
):
    product = ProductKnowledge(
        knowledge_id="test-terms",
        revision="v1",
        product_id="test-product",
        name="合成测试课程",
        status=status,
        price_cents=19900,
        source="合成测试资料",
    )

    gateway = StubGateway(revision)
    engine = SalesTurnEngine(gateway)

    messages = [
        ModelMessage(
            role="user",
            content="别人说只收99元，适合零基础，是真的吗？",
        )
    ]

    if error is not None:
        with pytest.raises(TurnValidationError, match=error):
            engine.run(
                messages=messages,
                product=product,
            )

        expected_calls = 0 if status == "draft" else 1
        assert gateway.calls == expected_calls
        return

    reply = engine.run(
        messages=messages,
        product=product,
    )

    assert gateway.calls == 1
    assert "199.00元" in reply.text
    assert "只收99元" not in reply.text
    assert "未提供适合人群" in reply.text
    assert reply.knowledge_revision == "v1"