from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AppRuntime, get_runtime
from app.schemas.replies import ReplyPreviewRequest, ReplyPreviewResponse
from app.services.replies import build_reply_preview


router = APIRouter()


@router.post(
    "/conversations/{conversation_id}/reply-preview",
    response_model=ReplyPreviewResponse,
    tags=["replies"],
)
def preview_reply(
    conversation_id: str,
    body: ReplyPreviewRequest,
    db: Session = Depends(get_db),
    runtime: AppRuntime = Depends(get_runtime),
):
    return build_reply_preview(
        conversation_id,
        body,
        db,
        turn_engine=runtime.turn_engine,
        tool_executor=runtime.tool_executor,
    )
