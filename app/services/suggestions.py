"""Suggestion persistence, guarded copy preparation and idempotent copy reports."""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import (
    Conversation,
    ReplySuggestion,
    SuggestionCopyEvent,
    SuggestionGenerationRequest,
)
from app.knowledge import KnowledgeRepository
from app.schemas.suggestions import (
    CopyReadyResponse,
    CopyReportRequest,
    CreateSuggestionRequest,
)
from app.services.errors import ServiceError
from app.services.generation_requests import claim_generation, mark_generation_failed
from app.services.memory_recall import recall_memory
from app.services.replies import build_reply_preview
from app.services.suggestion_validity import (
    SuggestionCheckUnavailableError,
    SuggestionValidity,
    check_suggestion,
)
from app.services.turn_engine import SalesTurnEngine
from app.tools import SalesToolExecutor


logger = logging.getLogger(__name__)


@dataclass
class SuggestionCreationResult:
    suggestion: ReplySuggestion
    created: bool


@dataclass
class CopyReportResult:
    event: SuggestionCopyEvent
    created: bool


def create_suggestion(
    conversation_id: str,
    body: CreateSuggestionRequest,
    db: Session,
    *,
    turn_engine: SalesTurnEngine,
    tool_executor: SalesToolExecutor,
) -> SuggestionCreationResult:
    # 放在 try 外：重复请求被拒绝，不应改变原请求的状态。
    claim = claim_generation(conversation_id, body, db)

    if not claim.created:
        suggestion = get_suggestion(conversation_id, claim.suggestion_id, db)
        return SuggestionCreationResult(suggestion=suggestion, created=False)

    try:
        preview = build_reply_preview(
            conversation_id,
            body,
            db,
            turn_engine=turn_engine,
            tool_executor=tool_executor,
        )

        # 模型调用已结束，重新开始保存事务。
        db.rollback()

        # 当前使用 SQLite：
        # 条件更新检查版本，并取得写锁，版本值保持原样。
        locked = db.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.version == body.based_on_version,
            )
            .values(version=Conversation.version)
            .execution_options(synchronize_session=False)
        )

        if locked.rowcount != 1:
            raise ServiceError(
                status_code=409,
                detail="Conversation changed before saving",
            )

        current_memory = recall_memory(
            db,
            conversation_id=conversation_id,
        )

        current_facts = [
            fact.model_dump(mode="json") for fact in current_memory.recalled_memory
        ]
        previous_facts = [
            fact.model_dump(mode="json") for fact in preview.recalled_memory
        ]

        if (
            current_facts != previous_facts
            or current_memory.conflicts != preview.memory_conflicts
        ):
            raise ServiceError(
                status_code=409,
                detail="Customer memory changed before saving",
            )

        suggestion = ReplySuggestion(
            conversation_id=conversation_id,
            based_on_version=preview.based_on_version,
            product_id=body.product_id,
            reply_text=preview.reply.text,
            generation_snapshot=preview.model_dump(mode="json"),
        )

        db.add(suggestion)
        db.flush()

        completed = db.execute(
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
                status="succeeded",
                suggestion_id=suggestion.id,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            .execution_options(synchronize_session=False)
        )

        if completed.rowcount != 1:
            raise ServiceError(
                status_code=409,
                detail={"code": "generation_request_not_running"},
            )

        # 建议和成功状态一起提交，任何一项出错都一起回滚。
        db.commit()

    except Exception as exc:
        db.rollback()

        error_code = "generation_internal_error"
        if isinstance(exc, ServiceError):
            error_code = f"generation_http_{exc.status_code}"
            if exc.status_code == 503 and isinstance(exc.detail, dict):
                error_code = "model_timeout" if exc.detail.get("code") == "model_timeout" else "model_unavailable"

        try:
            mark_generation_failed(
                conversation_id,
                body,
                db,
                error_code=error_code,
            )
        except Exception as record_exc:
            # 数据库本身不可用时，记录失败也可能失败。
            # 保留原始业务错误，只记录异常类型。
            logger.error(
                "generation_failure_record_failed error_type=%s",
                type(record_exc).__name__,
            )

        if isinstance(exc, ServiceError):
            raise

        logger.error(
            "suggestion_generation_failed error_type=%s",
            type(exc).__name__,
        )
        raise ServiceError(
            status_code=503,
            detail="generation_internal_error",
        ) from exc

    db.refresh(suggestion)
    return SuggestionCreationResult(suggestion=suggestion, created=True)


def list_suggestions(conversation_id: str, db: Session):
    if db.get(Conversation, conversation_id) is None:
        raise ServiceError(
            status_code=404,
            detail="Conversation not found",
        )

    return db.scalars(
        select(ReplySuggestion)
        .where(ReplySuggestion.conversation_id == conversation_id)
        .order_by(
            ReplySuggestion.created_at.desc(),
            ReplySuggestion.id.desc(),
        )
        .limit(50)
    ).all()


def get_suggestion(conversation_id: str, suggestion_id: str, db: Session):
    suggestion = db.scalar(
        select(ReplySuggestion).where(
            ReplySuggestion.id == suggestion_id,
            ReplySuggestion.conversation_id == conversation_id,
        )
    )

    if suggestion is None:
        raise ServiceError(
            status_code=404,
            detail="Suggestion not found",
        )

    return suggestion


def get_suggestion_validity(
    conversation_id: str,
    suggestion_id: str,
    db: Session,
    *,
    repository: KnowledgeRepository,
) -> SuggestionValidity:
    suggestion = db.scalar(
        select(ReplySuggestion).where(
            ReplySuggestion.id == suggestion_id,
            ReplySuggestion.conversation_id == conversation_id,
        )
    )

    if suggestion is None:
        raise ServiceError(
            status_code=404,
            detail="Suggestion not found",
        )

    try:
        return check_suggestion(
            db,
            suggestion=suggestion,
            repository=repository,
        )
    except SuggestionCheckUnavailableError as exc:
        raise ServiceError(
            status_code=503,
            detail=str(exc),
        ) from exc


def prepare_suggestion_copy(
    conversation_id: str,
    suggestion_id: str,
    db: Session,
    *,
    repository: KnowledgeRepository,
) -> CopyReadyResponse:
    try:
        # 当前使用 SQLite：先取得写锁，让数据库中的
        # 消息、记忆变更不会与本次检查交错。
        # 版本值不变，最后回滚释放锁。
        locked = db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(version=Conversation.version)
            .execution_options(synchronize_session=False)
        )

        if locked.rowcount != 1:
            raise ServiceError(
                status_code=404,
                detail="Suggestion not found",
            )

        suggestion = db.scalar(
            select(ReplySuggestion).where(
                ReplySuggestion.id == suggestion_id,
                ReplySuggestion.conversation_id == conversation_id,
            )
        )

        if suggestion is None:
            raise ServiceError(
                status_code=404,
                detail="Suggestion not found",
            )

        validity = check_suggestion(
            db,
            suggestion=suggestion,
            repository=repository,
        )

        if validity.status != "current":
            raise ServiceError(
                status_code=409,
                detail={
                    "code": "suggestion_stale",
                    "reasons": validity.reasons,
                },
            )

        return CopyReadyResponse(
            suggestion_id=suggestion.id,
            based_on_version=suggestion.based_on_version,
            text=suggestion.reply_text,
        )

    except SuggestionCheckUnavailableError as exc:
        raise ServiceError(
            status_code=503,
            detail=str(exc),
        ) from exc
    finally:
        db.rollback()


def report_suggestion_copy(
    conversation_id: str,
    suggestion_id: str,
    body: CopyReportRequest,
    db: Session,
) -> CopyReportResult:
    suggestion = db.scalar(
        select(ReplySuggestion).where(
            ReplySuggestion.id == suggestion_id,
            ReplySuggestion.conversation_id == conversation_id,
        )
    )

    if suggestion is None:
        raise ServiceError(
            status_code=404,
            detail="Suggestion not found",
        )

    def find_existing():
        return db.scalar(
            select(SuggestionCopyEvent).where(
                SuggestionCopyEvent.suggestion_id == suggestion_id,
                SuggestionCopyEvent.request_key == body.request_key,
            )
        )

    existing = find_existing()

    if existing is not None:
        return CopyReportResult(event=existing, created=False)

    event = SuggestionCopyEvent(
        suggestion_id=suggestion_id,
        request_key=body.request_key,
    )

    try:
        db.add(event)
        db.commit()
    except IntegrityError:
        db.rollback()

        # 另一次同 key 请求可能已经提交成功。
        existing = find_existing()

        if existing is None:
            raise

        return CopyReportResult(event=existing, created=False)

    db.refresh(event)
    return CopyReportResult(event=event, created=True)


def list_suggestion_copy_events(conversation_id: str, suggestion_id: str, db: Session):
    suggestion = db.scalar(
        select(ReplySuggestion).where(
            ReplySuggestion.id == suggestion_id,
            ReplySuggestion.conversation_id == conversation_id,
        )
    )

    if suggestion is None:
        raise ServiceError(
            status_code=404,
            detail="Suggestion not found",
        )

    return db.scalars(
        select(SuggestionCopyEvent)
        .where(SuggestionCopyEvent.suggestion_id == suggestion_id)
        .order_by(
            SuggestionCopyEvent.created_at.asc(),
            SuggestionCopyEvent.id.asc(),
        )
    ).all()
