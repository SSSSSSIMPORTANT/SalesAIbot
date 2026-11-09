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


@pytest.mark.parametrize(("topics", "draft", "source"), [
    (
        ["price", "trial"],
        "理解你想先体验再决定。\n[[PRICE_FACT]]\n[[TRIAL_FACT]]",
        "model",
    ),
    (["price", "trial"], "理解你的顾虑。\n[[PRICE_FACT]]", "template"),
    (["price", "trial"], "[[PRICE_FACT]]\n[[TRIAL_FACT]]", "template"),
    (
        ["price", "trial"],
        "理解你担心跟不上，零基础学员我们也有配套支持。\n[[PRICE_FACT]]\n[[TRIAL_FACT]]",
        "template",
    ),
    (["price"], "今天只收49元。\n[[PRICE_FACT]]", "template"),
    (["trial"], "可以免费试听。\n[[TRIAL_FACT]]", "template"),
    (["price", "refund_request"], "先看看价格。\n[[PRICE_FACT]]", "template"),
])
def test_engine_validates_model_written_reply(monkeypatch, topics, draft, source):
    product = ProductKnowledge(
        knowledge_id="test-terms",
        revision="v1",
        product_id="test-product",
        name="合成测试课程",
        status="published",
        price_cents=19900,
        source="合成测试资料",
    )
    gateway = StubGateway("v1")

    def generate(**kwargs):
        return ModelPlan(
            draft=ReplyDraft(
                topics=topics,
                knowledge_id=product.knowledge_id,
                knowledge_revision=product.revision,
                reply_text=draft,
            ),
            model_name="stub",
            mode="mock",
        )

    monkeypatch.setattr(gateway, "generate", generate)
    reply = SalesTurnEngine(gateway).run(
        messages=[ModelMessage(role="user", content="这门课多少钱？")],
        product=product,
    )

    assert reply.text_source == source
    assert "[[" not in reply.text
    assert "49元" not in reply.text
    assert "免费试听" not in reply.text
    assert "配套支持" not in reply.text

    if source == "model":
        assert reply.text.startswith("理解你想先体验再决定。")
        assert "199.00元" in reply.text
        assert "试听安排需要进一步核实。" in reply.text
    if "refund_request" in topics:
        assert "由人工处理退款申请" in reply.text
        assert "199.00元" not in reply.text
