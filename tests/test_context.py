from types import SimpleNamespace

import pytest

from app.services.context import (
    MAX_RECENT_MESSAGES,
    build_recent_context,
)


def make_message(actor, text):
    return SimpleNamespace(actor=actor, text=text)


def test_context_keeps_only_recent_messages_in_order():
    history = [
        make_message(
            "customer" if index % 2 == 0 else "human",
            f"message-{index}",
        )
        for index in range(20)
    ]

    context = build_recent_context(history)

    assert len(context) == MAX_RECENT_MESSAGES
    assert context[0].content == "message-4"
    assert context[-1].content == "message-19"


def test_context_maps_sales_messages_to_assistant():
    history = [
        make_message("customer", "你好"),
        make_message("human", "您好"),
    ]

    context = build_recent_context(history)

    assert [message.role for message in context] == [
        "user",
        "assistant",
    ]


def test_context_rejects_non_positive_limit():
    with pytest.raises(ValueError, match="at least 1"):
        build_recent_context([], max_messages=0)