import json
from hashlib import sha256

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.database import Conversation, Message, ScreenshotImport
from app.schemas.screenshot_transcription import (
    ConfirmScreenshotImportRequest,
    ConfirmScreenshotImportResponse,
)
from app.services.errors import ServiceError


def confirm_screenshot_import(
    db: Session,
    *,
    conversation_id: str,
    body: ConfirmScreenshotImportRequest,
) -> tuple[ConfirmScreenshotImportResponse, bool]:
    payload = json.dumps(
        body.model_dump(exclude={"request_key"}),
        sort_keys=True,
        separators=(",", ":"),
    )
    payload_hash = sha256(payload.encode("utf-8")).hexdigest()
    new_version = body.based_on_version + len(body.lines)

    with db.begin():
        claim = (
            insert(ScreenshotImport)
            .values(
                conversation_id=conversation_id,
                request_key=body.request_key,
                payload_hash=payload_hash,
                version=new_version,
                message_ids=[],
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ScreenshotImport.conversation_id,
                    ScreenshotImport.request_key,
                ]
            )
            .returning(ScreenshotImport)
        )
        receipt = db.scalar(claim)
        created = receipt is not None

        if receipt is None:
            receipt = db.get(ScreenshotImport, (conversation_id, body.request_key))
            if receipt is None:
                raise RuntimeError("Screenshot import receipt is missing")
            if receipt.payload_hash != payload_hash:
                raise ServiceError(
                    status_code=409,
                    detail={"code": "screenshot_import_key_conflict"},
                )
        else:
            changed = db.execute(
                update(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.version == body.based_on_version,
                )
                .values(version=new_version)
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise ServiceError(
                    status_code=409,
                    detail={"code": "conversation_version_conflict"},
                )

            messages = [
                Message(conversation_id=conversation_id, actor=line.actor, text=line.text)
                for line in body.lines
            ]
            db.add_all(messages)
            db.flush()
            receipt.message_ids = [message.id for message in messages]

        result = ConfirmScreenshotImportResponse(
            conversation_id=conversation_id,
            request_key=body.request_key,
            version=receipt.version,
            message_ids=receipt.message_ids,
        )

    return result, created
