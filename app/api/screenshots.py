from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.dependencies import AppRuntime, get_runtime
from app.schemas.screenshot_transcription import (
    ConfirmScreenshotImportRequest,
    ConfirmScreenshotImportResponse,
    ScreenshotTranscriptResponse,
)
from app.services.errors import ServiceError
from app.services.screenshot_imports import confirm_screenshot_import
from app.services.screenshots import (
    IMAGE_FORMATS,
    MAX_UPLOAD_BYTES,
    build_screenshot_transcript,
    normalize_screenshot,
)


router = APIRouter(tags=["screenshots"])
BINARY_SCHEMA = {"type": "string", "format": "binary"}


async def read_normalized_screenshot(request: Request) -> bytes:
    media_type = (
        request.headers.get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if media_type not in IMAGE_FORMATS:
        raise ServiceError(status_code=415, detail="Use PNG or JPEG")

    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ServiceError(status_code=413, detail="Upload exceeds 5 MiB")
        raw.extend(chunk)

    return await run_in_threadpool(
        normalize_screenshot, bytes(raw), media_type
    )


@router.post(
    "/conversations/{conversation_id}/screenshots/preview",
    response_class=Response,
    responses={200: {"content": {"image/png": {"schema": BINARY_SCHEMA}}}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media_type: {"schema": BINARY_SCHEMA}
                for media_type in IMAGE_FORMATS
            },
        }
    },
)
async def preview_screenshot(
    conversation_id: str,
    request: Request,
) -> Response:
    preview = await read_normalized_screenshot(request)
    return Response(
        content=preview,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post(
    "/conversations/{conversation_id}/screenshots/transcribe",
    response_model=ScreenshotTranscriptResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media_type: {"schema": BINARY_SCHEMA}
                for media_type in IMAGE_FORMATS
            },
        }
    },
)
async def transcribe_screenshot(
    conversation_id: str,
    request: Request,
    response: Response,
    based_on_version: int = Query(ge=0),
    db: Session = Depends(get_db),
    runtime: AppRuntime = Depends(get_runtime),
) -> ScreenshotTranscriptResponse:
    png = await read_normalized_screenshot(request)

    transcript = await run_in_threadpool(
        build_screenshot_transcript,
        db,
        conversation_id=conversation_id,
        based_on_version=based_on_version,
        png=png,
        gateway=runtime.gateway,
    )
    response.headers["Cache-Control"] = "no-store"
    return transcript


@router.post(
    "/conversations/{conversation_id}/screenshots/import",
    response_model=ConfirmScreenshotImportResponse,
    status_code=201,
    responses={200: {"description": "Already imported"}},
)
def import_screenshot(
    conversation_id: str,
    body: ConfirmScreenshotImportRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> ConfirmScreenshotImportResponse:
    result, created = confirm_screenshot_import(
        db, conversation_id=conversation_id, body=body
    )
    response.status_code = 201 if created else 200
    return result
