from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.knowledge import KnowledgeRepository, ProductKnowledge


class ProductKnowledgeArguments(BaseModel):
    """课程查询工具接受的参数。"""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    product_id: str = Field(
        min_length=1,
        max_length=100,
        description="需要查询的课程产品 ID",
    )


class ToolExecutionError(Exception):
    """工具请求不合法，保存可以对外返回的错误代码。"""


class SalesToolExecutor:
    """执行明确允许的销售工具。"""

    PRODUCT_TOOL_NAME = "get_product_knowledge"

    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository

    def definitions(self) -> list[dict]:
        """向模型描述可用工具，暂时只有一个。"""

        return [
            {
                "type": "function",
                "function": {
                    "name": self.PRODUCT_TOOL_NAME,
                    "description": (
                        "根据产品 ID 查询已发布的课程资料。"
                        "只读取资料，不修改数据。"
                        "找不到课程或课程资料未发布时返回空结果。"
                    ),
                    "parameters": (
                        ProductKnowledgeArguments.model_json_schema()
                    ),
                },
            }
        ]

    def execute(
        self,
        *,
        name: str,
        arguments: dict[str, object],
    ) -> ProductKnowledge | None:
        # 先检查工具名称，不根据外部输入动态加载函数。
        if name != self.PRODUCT_TOOL_NAME:
            raise ToolExecutionError("unknown_tool")

        # 参数通过校验后，才允许查询知识库。
        try:
            parsed = ProductKnowledgeArguments.model_validate(
                arguments
            )
        except ValidationError:
            raise ToolExecutionError(
                "invalid_tool_arguments"
            ) from None

        return self.repository.get_published_product(
            parsed.product_id
        )