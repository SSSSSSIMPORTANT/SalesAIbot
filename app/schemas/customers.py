from pydantic import BaseModel, ConfigDict, Field


class CreateCustomerRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    display_name: str = Field(min_length=1, max_length=100)


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    created_at: str
