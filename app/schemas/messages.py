from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CustomerMessageRequest(BaseModel):
    """客户端提交的客户消息。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(
        min_length=1,
        max_length=2000,
        description="客户消息正文",
    )


class CreateMessageRequest(BaseModel):
    """向会话补录一条消息。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    request_key: str = Field(min_length=1, max_length=64)
    based_on_version: int = Field(ge=0, strict=True)
    actor: Literal["customer", "human"]
    text: str = Field(min_length=1, max_length=2000)
    source_suggestion_id: str | None = Field(
        default=None, min_length=1, max_length=32
    )

    @model_validator(mode="after")
    def check_suggestion_source(self):
        if self.source_suggestion_id is not None and self.actor != "human":
            raise ValueError("Only human messages can reference a suggestion")
        return self


class MessageResponse(BaseModel):
    """返回一条已保存的消息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: str
    actor: Literal["customer", "human"]
    text: str
    source_suggestion_id: str | None
    adoption_mode: Literal["verbatim", "edited"] | None
    created_at: str
