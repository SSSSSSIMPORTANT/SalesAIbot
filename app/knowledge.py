from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "products.json"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    status: Literal["draft", "published", "archived"]

    price_cents: int = Field(ge=0)
    trial_available: bool | None = None
    refund_policy: str | None = None

    source: str = Field(min_length=1)
    effective_from: AwareDatetime | None = None
    effective_until: AwareDatetime | None = None

    @field_validator("effective_from", "effective_until", mode="before")
    @classmethod
    def parse_effective_time(cls, value):
        if isinstance(value, str):
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def check_effective_window(self):
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_from >= self.effective_until
        ):
            raise ValueError("effective_from must be before effective_until")
        return self

    def is_active(self, at: datetime | None = None) -> bool:
        instant = utc_now() if at is None else at
        return (
            self.status == "published"
            and (self.effective_from is None or self.effective_from <= instant)
            and (self.effective_until is None or instant < self.effective_until)
        )


class ProductCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    products: list[ProductKnowledge]

    @model_validator(mode="after")
    def check_revisions(self):
        revisions: set[tuple[str, str]] = set()
        knowledge_by_product: dict[str, str] = {}
        product_by_knowledge: dict[str, str] = {}
        published_products: set[str] = set()

        for row in self.products:
            key = (row.knowledge_id, row.revision)
            if key in revisions:
                raise ValueError("Duplicate knowledge revision")
            revisions.add(key)

            knowledge_id = knowledge_by_product.setdefault(
                row.product_id, row.knowledge_id
            )
            if knowledge_id != row.knowledge_id:
                raise ValueError("Product must keep the same knowledge_id")

            product_id = product_by_knowledge.setdefault(
                row.knowledge_id, row.product_id
            )
            if product_id != row.product_id:
                raise ValueError("Knowledge must belong to one product")

            if row.status == "published":
                if row.product_id in published_products:
                    raise ValueError("Product can have only one published revision")
                published_products.add(row.product_id)

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
        now = utc_now()
        return [
            product
            for product in self.catalog.products
            if product.is_active(now)
        ]

    def list_product_revisions(self, product_id: str) -> list[ProductKnowledge]:
        return [
            row
            for row in self.catalog.products
            if row.product_id == product_id
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

