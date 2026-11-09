from typing import Literal

from app.knowledge import ProductKnowledge


ReplyTopic = Literal[
    "price",
    "trial",
    "refund",
    "audience",
    "curriculum",
    "other",
]


def render_business_reply(
    *,
    product: ProductKnowledge | None,
    topics: list[ReplyTopic],
) -> str:
    """只使用资料中已有的事实生成业务回复。"""

    if not topics:
        raise ValueError("At least one reply topic is required")

    if product is None:
        return "请先确认您想了解哪门课程，再核实相关信息。"

    price = (
        f"{product.price_cents // 100}."
        f"{product.price_cents % 100:02d}"
    )

    if product.trial_available is None:
        trial_text = "试听安排需要进一步核实。"
    elif product.trial_available:
        trial_text = (
            "资料显示该课程提供试听，"
            "具体安排及是否收费需要进一步核实。"
        )
    else:
        trial_text = "资料显示该课程不提供试听。"

    refund_text = (
        f"退款政策：{product.refund_policy}"
        if product.refund_policy
        else "退款政策需要进一步核实。"
    )

    answers: dict[ReplyTopic, str] = {
        "price": f"《{product.name}》的价格是{price}元。",
        "trial": trial_text,
        "refund": refund_text,
        "audience": "目前资料未提供适合人群的信息，需要进一步核实。",
        "curriculum": "目前资料未提供课程大纲，需要进一步核实。",
        "other": "您咨询的这项信息需要进一步核实。",
    }

    # 保留话题顺序，同时避免重复回答同一个话题。
    unique_topics = dict.fromkeys(topics)

    return "\n".join(
        answers[topic]
        for topic in unique_topics
    )