from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    customer_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    customer_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
    )

    @model_validator(mode="after")
    def check_customer_reference(self):
        has_name = self.customer_name is not None
        has_id = self.customer_id is not None

        if has_name == has_id:
            raise ValueError("Provide exactly one of customer_name or customer_id")

        return self


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_name: str
    version: int
    created_at: str
    customer_id: str | None
    suggestions_paused: bool


class SetAssistanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_version: int = Field(ge=0, strict=True)
    suggestions_paused: bool = Field(strict=True)
