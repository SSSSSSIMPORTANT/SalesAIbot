from collections.abc import Sequence

from app.database import Message
from app.llm import ModelMessage


MAX_RECENT_MESSAGES = 16


def build_recent_context(
    history: Sequence[Message],
    *,
    max_messages: int = MAX_RECENT_MESSAGES,
) -> list[ModelMessage]:
    if max_messages < 1:
        raise ValueError("max_messages must be at least 1")

    recent = history[-max_messages:]

    return [
        ModelMessage(
            role="user" if message.actor == "customer" else "assistant",
            content=message.text,
        )
        for message in recent
    ]