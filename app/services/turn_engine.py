from app.knowledge import ProductKnowledge
from app.services.reply_rendering import render_business_reply
from app.llm import (
    ModelGateway,
    ModelMessage,
    ModelReply,
    PendingToolCall,
    ConfirmedFactSnapshot,
)
from pydantic import BaseModel

from app.tools import SalesToolExecutor

import logging
from collections.abc import Callable
from time import perf_counter
from typing import TypeVar


class TurnValidationError(Exception):
    """销售回合未通过业务校验。"""


class ProductKnowledgeNotFoundError(Exception):
    """没有查到可用的已发布资料。"""


logger = logging.getLogger(__name__)

T = TypeVar("T")


class TurnTraceStep(BaseModel):
    step: str
    status: str
    duration_ms: float
    error_type: str | None = None


def run_traced_step(
        *,
        trace: list[TurnTraceStep],
        step: str,
        operation: Callable[[], T],
) -> T:
    started = perf_counter()

    try:
        result = operation()
    except Exception as exc:
        duration_ms = round(
            (perf_counter() - started) * 1000,
            3,
        )
        trace.append(
            TurnTraceStep(
                step=step,
                status="failed",
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
            )
        )
        logger.warning(
            "sales_turn_step_failed step=%s duration_ms=%.3f error_type=%s",
            step,
            duration_ms,
            type(exc).__name__,
        )
        raise

    duration_ms = round(
        (perf_counter() - started) * 1000,
        3,
    )
    trace.append(
        TurnTraceStep(
            step=step,
            status="succeeded",
            duration_ms=duration_ms,
        )
    )
    logger.info(
        "sales_turn_step_succeeded step=%s duration_ms=%.3f",
        step,
        duration_ms,
    )
    return result


class SalesTurnResult(BaseModel):
    """一个完整回合返回的业务结果。"""

    reply: ModelReply
    retrieved_knowledge: ProductKnowledge
    trace: list[TurnTraceStep]


class SalesTurnEngine:
    """执行一次：模型规划、业务校验、正文生成。"""

    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def run(
            self,
            *,
            messages: list[ModelMessage],
            product: ProductKnowledge,
            tool_call: PendingToolCall | None = None,
            memories: tuple[ConfirmedFactSnapshot, ...] = (),
    ) -> ModelReply:
        # 在调用模型之前检查资料状态。
        if product.status != "published":
            raise TurnValidationError(
                "knowledge_not_published"
            )

        plan = self.gateway.generate(
            messages=messages,
            product=product,
            tool_call=tool_call,
            memories=memories,
        )

        expected_reference = (
            product.knowledge_id,
            product.revision,
        )
        actual_reference = (
            plan.draft.knowledge_id,
            plan.draft.knowledge_revision,
        )

        if actual_reference != expected_reference:
            raise TurnValidationError(
                "model_knowledge_mismatch"
            )

        text = render_business_reply(
            product=product,
            topics=plan.draft.topics,
        )

        return ModelReply(
            text=text,
            topics=plan.draft.topics,
            model_name=plan.model_name,
            mode=plan.mode,
            knowledge_id=product.knowledge_id,
            knowledge_revision=product.revision,
        )

    def preview(
            self,
            *,
            messages: list[ModelMessage],
            product_id: str,
            tools: SalesToolExecutor,
            memories: tuple[ConfirmedFactSnapshot, ...] = (),
    ) -> SalesTurnResult:
        trace: list[TurnTraceStep] = []
        # 第一次模型调用：提出查询请求。
        call = run_traced_step(
            trace=trace,
            step="request_tool",
            operation=lambda: self.gateway.request_product_tool(
                messages=messages,
                product_id=product_id,
                tools=tools.definitions(),
            ),
        )

        # 引擎再次检查业务范围，不能完全依赖网关。
        if call.arguments.get("product_id") != product_id:
            raise TurnValidationError(
                "model_product_mismatch"
            )

        # 执行器检查工具名称、参数，再执行查询。
        product = run_traced_step(
            trace=trace,
            step="execute_tool",
            operation=lambda: tools.execute(
                name=call.name,
                arguments=call.arguments,
            ),
        )

        if product is None:
            raise ProductKnowledgeNotFoundError(
                "Published product knowledge not found"
            )

        # 第二次模型调用、版本校验和正文生成。
        reply = run_traced_step(
            trace=trace,
            step="generate_reply",
            operation=lambda: self.run(
                messages=messages,
                product=product,
                tool_call=call,
                memories=memories,
            ),
        )

        return SalesTurnResult(
            reply=reply,
            retrieved_knowledge=product,
            trace=trace,
        )
