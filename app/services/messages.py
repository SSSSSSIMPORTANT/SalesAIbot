from dataclasses import dataclass
from typing import Literal

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Conversation, Message, MessageSubmission, ReplySuggestion


class ConversationNotFoundError(Exception):
    """指定会话不存在。"""


class MessageConflictError(Exception):
    """提交内容或会话版本存在冲突。"""


class SourceSuggestionNotFoundError(Exception):
    """指定会话中找不到这条建议。"""


@dataclass
class AddMessageResult:
    message: Message
    created: bool


def add_message(
    db: Session,
    *,
    conversation_id: str,
    request_key: str,
    based_on_version: int,
    actor: Literal["customer", "human"],
    text: str,
    source_suggestion_id: str | None = None,
) -> AddMessageResult:
    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise ConversationNotFoundError("Conversation not found")

    submission_id = (conversation_id, request_key)

    def return_existing(
        submission: MessageSubmission,
    ) -> AddMessageResult:
        message = db.get(Message, submission.message_id)

        if message is None:
            raise RuntimeError("Submission record is inconsistent")

        if (
            message.actor != actor
            or message.text != text
            or message.source_suggestion_id != source_suggestion_id
        ):
            raise MessageConflictError(
                "Request key already used for different content"
            )

        return AddMessageResult(
            message=message,
            created=False,
        )

    existing = db.get(MessageSubmission, submission_id)

    if existing is not None:
        return return_existing(existing)

    adoption_mode = None

    if source_suggestion_id is not None:
        suggestion = db.get(ReplySuggestion, source_suggestion_id)
        if suggestion is None or suggestion.conversation_id != conversation_id:
            raise SourceSuggestionNotFoundError(
                "Source suggestion not found in this conversation"
            )

        adoption_mode = (
            "verbatim" if text == suggestion.reply_text.strip() else "edited"
        )

    message = Message(
        conversation_id=conversation_id,
        actor=actor,
        text=text,
        source_suggestion_id=source_suggestion_id,
        adoption_mode=adoption_mode,
    )

    try:
        statement = (
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.version == based_on_version,
            )
            .values(version=Conversation.version + 1)
            .execution_options(synchronize_session=False)
        )

        result = db.execute(statement)

        if result.rowcount == 0:
            db.rollback()

            existing = db.get(MessageSubmission, submission_id)

            if existing is not None:
                return return_existing(existing)

            raise MessageConflictError(
                "Conversation changed; refresh before submitting"
            )

        db.add(message)
        db.flush()

        submission = MessageSubmission(
            conversation_id=conversation_id,
            request_key=request_key,
            message_id=message.id,
        )

        db.add(submission)
        db.commit()

    except IntegrityError:
        db.rollback()

        existing = db.get(MessageSubmission, submission_id)

        if existing is None:
            raise

        return return_existing(existing)

    db.refresh(message)

    return AddMessageResult(
        message=message,
        created=True,
    )