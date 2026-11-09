from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TranscriptLine(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True
    )

    actor: Literal["customer", "human", "unknown"]
    text: str = Field(min_length=1, max_length=2000)
    unclear: bool


class TranscriptDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lines: list[TranscriptLine] = Field(max_length=20)


class TranscriptResult(TranscriptDraft):
    model_name: str
    mode: Literal["mock", "live"]


class ScreenshotTranscriptResponse(TranscriptResult):
    conversation_id: str
    based_on_version: int


class ConfirmedTranscriptLine(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True
    )

    actor: Literal["customer", "human"]
    text: str = Field(min_length=1, max_length=2000)


class ConfirmScreenshotImportRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True
    )

    request_key: str = Field(min_length=1, max_length=64)
    based_on_version: int = Field(ge=0)
    lines: list[ConfirmedTranscriptLine] = Field(min_length=1, max_length=20)


class ConfirmScreenshotImportResponse(BaseModel):
    conversation_id: str
    request_key: str
    version: int
    message_ids: list[int]
