"""在短事务中领取一次生成任务。"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import (
    Conversation,
    ReplySuggestion,
    SuggestionGenerationRequest,
)
from app.schemas.suggestions import CreateSuggestionRequest
from app.services.errors import ServiceError


@dataclass(frozen=True)
class GenerationClaim:
    created: bool
    suggestion_id: str | None = None


def claim_generation(
    conversation_id: str,
    body: CreateSuggestionRequest,
    db: Session,
) -> GenerationClaim:
    # 本函数负责提交或回滚。
    # 不要传入包含其他待保存修改的 Session。
    try:
        locked = db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(version=Conversation.version)
            .execution_options(synchronize_session=False)
        )

        if locked.rowcount != 1:
            raise ServiceError(
                status_code=404,
                detail="Conversation not found",
            )

        existing = db.get(
            SuggestionGenerationRequest,
            (conversation_id, body.request_key),
            populate_existing=True,
        )

        if existing is not None:
            if (
                existing.based_on_version != body.based_on_version
                or existing.product_id != body.product_id
            ):
                raise ServiceError(
                    status_code=409,
                    detail={"code": "generation_request_mismatch"},
                )

            if existing.status == "running":
                raise ServiceError(
                    status_code=409,
                    detail={"code": "generation_in_progress"},
                )

            if existing.status == "failed":
                raise ServiceError(
                    status_code=409,
                    detail={"code": "generation_failed"},
                )

            suggestion_id = db.scalar(
                select(ReplySuggestion.id).where(
                    ReplySuggestion.id == existing.suggestion_id,
                    ReplySuggestion.conversation_id == conversation_id,
                    ReplySuggestion.based_on_version
                    == existing.based_on_version,
                    ReplySuggestion.product_id == existing.product_id,
                )
            )

            if suggestion_id is None:
                raise ServiceError(
                    status_code=503,
                    detail={"code": "generation_result_unavailable"},
                )

            result = GenerationClaim(
                created=False,
                suggestion_id=suggestion_id,
            )

        else:
            state = db.execute(
                select(Conversation.version, Conversation.suggestions_paused)
                .where(Conversation.id == conversation_id)
            ).one()

            if state.version != body.based_on_version:
                raise ServiceError(
                    status_code=409,
                    detail="Conversation changed; refresh before generating",
                )

            if state.suggestions_paused:
                raise ServiceError(status_code=409, detail={"code": "suggestions_paused"})

            db.add(
                SuggestionGenerationRequest(
                    conversation_id=conversation_id,
                    request_key=body.request_key,
                    based_on_version=body.based_on_version,
                    product_id=body.product_id,
                    status="running",
                )
            )

            result = GenerationClaim(created=True)

        db.commit()
        return result

    except Exception:
        db.rollback()
        raise


def mark_generation_failed(
    conversation_id: str,
    body: CreateSuggestionRequest,
    db: Session,
    *,
    error_code: str,
) -> bool:
    # 调用前先回滚失败的业务事务；这里单独提交失败状态。
    try:
        updated = db.execute(
            update(SuggestionGenerationRequest)
            .where(
                SuggestionGenerationRequest.conversation_id == conversation_id,
                SuggestionGenerationRequest.request_key == body.request_key,
                SuggestionGenerationRequest.based_on_version
                == body.based_on_version,
                SuggestionGenerationRequest.product_id == body.product_id,
                SuggestionGenerationRequest.status == "running",
            )
            .values(
                status="failed",
                error_code=error_code,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return updated.rowcount == 1
    except Exception:
        db.rollback()
        raise


def get_generation_request(
    conversation_id: str,
    request_key: str,
    db: Session,
) -> SuggestionGenerationRequest:
    row = db.get(
        SuggestionGenerationRequest,
        (conversation_id, request_key),
        populate_existing=True,
    )

    if row is None:
        raise ServiceError(
            status_code=404,
            detail="Generation request not found",
        )

    return row
