import pytest

from app.knowledge import ProductKnowledge
from app.services.reply_rendering import render_business_reply


def make_product(**overrides):
    data = {
        "knowledge_id": "test-terms",
        "revision": "v1",
        "product_id": "test-product",
        "name": "合成测试课程",
        "status": "published",
        "price_cents": 19900,
        "trial_available": None,
        "refund_policy": None,
        "source": "合成测试资料",
    }
    data.update(overrides)

    return ProductKnowledge.model_validate(data)


@pytest.mark.parametrize(
    ("price_cents", "expected"),
    [
        (19901, "199.01元"),
        (0, "0.00元"),
    ],
)
def test_price_preserves_cents(price_cents, expected):
    product = make_product(price_cents=price_cents)

    text = render_business_reply(
        product=product,
        topics=["price"],
    )

    assert expected in text


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (None, "试听安排需要进一步核实。"),
        (False, "资料显示该课程不提供试听。"),
        (
            True,
            "资料显示该课程提供试听，"
            "具体安排及是否收费需要进一步核实。",
        ),
    ],
)
def test_trial_distinguishes_unknown_from_false(
    available,
    expected,
):
    product = make_product(trial_available=available)

    text = render_business_reply(
        product=product,
        topics=["trial"],
    )

    assert text == expected


def test_missing_facts_do_not_become_product_promises():
    product = make_product()

    text = render_business_reply(
        product=product,
        topics=["audience", "curriculum", "refund"],
    )

    assert "未提供适合人群" in text
    assert "未提供课程大纲" in text
    assert "退款政策需要进一步核实" in text
    assert "面向零基础" not in text
    assert "随时退款" not in text


def test_refund_policy_comes_from_knowledge():
    policy = "合成测试条款：开课前可申请退款。"
    product = make_product(refund_policy=policy)

    text = render_business_reply(
        product=product,
        topics=["refund"],
    )

    assert text == f"退款政策：{policy}"
    assert "随时退款" not in text