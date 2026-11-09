from pydantic import BaseModel, ConfigDict


class ProductOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: str
    name: str