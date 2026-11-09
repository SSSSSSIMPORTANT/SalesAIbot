from io import BytesIO
from struct import error as StructError
from zlib import error as ZlibError

from PIL import Image, ImageOps

from app.services.errors import ServiceError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Conversation
from app.llm import ModelCallError, ModelGateway
from app.schemas.screenshot_transcription import ScreenshotTranscriptResponse


IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PREVIEW_BYTES = 10 * 1024 * 1024
MAX_SIDE = 4096
MAX_PIXELS = 8_000_000
MAX_VISION_PNG_BYTES = 7 * 1024 * 1024


def build_screenshot_transcript(
    db: Session,
    *,
    conversation_id: str,
    based_on_version: int,
    png: bytes,
    gateway: ModelGateway,
) -> ScreenshotTranscriptResponse:
    def read_version() -> int | None:
        version = db.scalar(
            select(Conversation.version).where(
                Conversation.id == conversation_id
            )
        )
        db.rollback()
        return version

    version = read_version()
    if version is None:
        raise ServiceError(status_code=404, detail="Conversation not found")
    if version != based_on_version:
        raise ServiceError(
            status_code=409,
            detail={"code": "conversation_version_conflict"},
        )

    if len(png) > MAX_VISION_PNG_BYTES:
        raise ServiceError(status_code=413, detail="PNG too large for transcription")

    with Image.open(BytesIO(png), formats=("PNG",)) as image:
        short_side, long_side = sorted(image.size)
    if short_side <= 10 or long_side > 200 * short_side:
        raise ServiceError(status_code=422, detail="Unsupported image dimensions")

    try:
        result = gateway.transcribe_screenshot(png=png)
    except ModelCallError as exc:
        raise ServiceError(status_code=503, detail=str(exc)) from None

    if read_version() != based_on_version:
        raise ServiceError(
            status_code=409,
            detail={"code": "conversation_version_conflict"},
        )

    return ScreenshotTranscriptResponse(
        conversation_id=conversation_id,
        based_on_version=based_on_version,
        **result.model_dump(),
    )


def normalize_screenshot(raw: bytes, media_type: str) -> bytes:
    expected_format = IMAGE_FORMATS.get(media_type)
    if expected_format is None:
        raise ServiceError(status_code=415, detail="Use PNG or JPEG")

    try:
        with Image.open(BytesIO(raw), formats=("PNG", "JPEG")) as image:
            if image.format != expected_format:
                raise ServiceError(
                    status_code=415,
                    detail="Content-Type does not match the image format",
                )

            width, height = image.size
            if max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
                raise ServiceError(status_code=413, detail="Image dimensions too large")

            if getattr(image, "n_frames", 1) != 1:
                raise ServiceError(status_code=422, detail="Use a single-frame image")

            image.verify()

        with Image.open(BytesIO(raw), formats=(expected_format,)) as source:
            source.load()
            ImageOps.exif_transpose(source, in_place=True)

            with source.convert("RGBA") as pixels, Image.new("RGB", source.size, "white") as canvas:
                with pixels.getchannel("A") as alpha:
                    canvas.paste(pixels, mask=alpha)
                with BytesIO() as output:
                    canvas.save(output, format="PNG")
                    if output.tell() > MAX_PREVIEW_BYTES:
                        raise ServiceError(status_code=413, detail="PNG preview too large")
                    return output.getvalue()

    except Image.DecompressionBombError:
        raise ServiceError(status_code=413, detail="Image dimensions too large") from None
    except (OSError, ValueError, SyntaxError, EOFError, StructError, ZlibError):
        raise ServiceError(status_code=422, detail="Invalid or damaged image") from None
