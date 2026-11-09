from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "products.json"
)


class ProductKnowledge(BaseModel):
    """一份产品条款记录。"""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    knowledge_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)

    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: Literal["draft", "published"]

    price_cents: int = Field(ge=0)
    trial_available: bool | None = None
    refund_policy: str | None = None

    source: str = Field(min_length=1)


class ProductCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    products: list[ProductKnowledge]

    @model_validator(mode="after")
    def check_unique_ids(self):
        for field in ("product_id", "knowledge_id"):
            values = [
                getattr(product, field)
                for product in self.products
            ]

            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {field}")

        return self


class KnowledgeRepository:
    """读取产品目录，提供明确范围的查询。"""

    def __init__(
        self,
        path: Path = DEFAULT_CATALOG_PATH,
    ):
        raw = path.read_text(encoding="utf-8")
        self.catalog = ProductCatalog.model_validate_json(raw)
        self.path = path

    def list_published_products(self) -> list[ProductKnowledge]:
        return [
            product
            for product in self.catalog.products
            if product.status == "published"
        ]

    def get_published_product(
        self,
        product_id: str,
    ) -> ProductKnowledge | None:
        for product in self.list_published_products():
            if product.product_id == product_id:
                return product

        return None

    def get_current_published_product(
        self,
        product_id: str,
    ) -> ProductKnowledge | None:
        # 重新读取文件，避免只检查启动时的缓存。
        current = KnowledgeRepository(self.path)
        return current.get_published_product(product_id)

