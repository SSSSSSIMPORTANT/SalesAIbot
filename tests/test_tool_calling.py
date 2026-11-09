import json

import httpx
import pytest

from app.config import Settings
from app.knowledge import DEFAULT_CATALOG_PATH, KnowledgeRepository
from app.llm import ModelCallError, ModelMessage, QwenModelGateway
from app.tools import SalesToolExecutor
from app.services.turn_engine import SalesTurnEngine
from app.llm import MockModelGateway, PendingToolCall
from app.services.turn_engine import (
    ProductKnowledgeNotFoundError,
    TurnValidationError,
)
from app.tools import ToolExecutionError


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("valid", None),
        ("valid_stop", None),
        ("missing", "model_tool_call_expected"),
        ("multiple", "model_tool_call_count"),
        ("wrong_product", "model_product_mismatch"),
        ("truncated", "model_output_incomplete"),
    ],
)
def test_product_tool_call(tmp_path, case, error):
    path = tmp_path / "products.json"
    path.write_bytes(DEFAULT_CATALOG_PATH.read_bytes())
    executor = SalesToolExecutor(KnowledgeRepository(path))

    def handler(request):
        payload = json.loads(request.content)

        assert payload["tools"] == executor.definitions()
        assert payload["tool_choice"]["function"]["name"] == (
            "get_product_knowledge"
        )
        assert "response_format" not in payload

        product_id = (
            "another-product"
            if case == "wrong_product"
            else "demo_python_basic"
        )

        call = {
            "id": "call_test_001",
            "type": "function",
            "function": {
                "name": "get_product_knowledge",
                "arguments": json.dumps(
                    {"product_id": product_id}
                ),
            },
        }

        calls = [call, call] if case == "multiple" else [call]
        if case == "missing":
            calls = []

        finish_reason = {
            "valid_stop": "stop",
            "missing": "stop",
            "truncated": "length",
        }.get(case, "tool_calls")

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": calls,
                        },
                    }
                ]
            },
        )

    gateway = QwenModelGateway(
        Settings(
            llm_mode="live",
            llm_base_url="https://model.example.test/v1",
            llm_model="test-model",
            llm_api_key="synthetic-key",
        ),
        transport=httpx.MockTransport(handler),
    )

    arguments = {
        "messages": [
            ModelMessage(role="user", content="这门课多少钱？")
        ],
        "product_id": "demo_python_basic",
        "tools": executor.definitions(),
    }

    if error is not None:
        with pytest.raises(ModelCallError, match=error):
            gateway.request_product_tool(**arguments)
        return

    call = gateway.request_product_tool(**arguments)

    assert call.call_id == "call_test_001"

    product = executor.execute(
        name=call.name,
        arguments=call.arguments,
    )

    assert product is not None
    assert product.product_id == "demo_python_basic"
    assert product.price_cents == 19900


def test_tool_result_is_returned_to_model(tmp_path):
    path = tmp_path / "products.json"
    path.write_bytes(DEFAULT_CATALOG_PATH.read_bytes())
    executor = SalesToolExecutor(KnowledgeRepository(path))

    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)

        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_roundtrip",
                        "type": "function",
                        "function": {
                            "name": "get_product_knowledge",
                            "arguments": json.dumps(
                                {"product_id": "demo_python_basic"}
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            assert len(requests) == 2

            assistant_message = payload["messages"][-2]
            tool_message = payload["messages"][-1]

            assert assistant_message["role"] == "assistant"
            assert tool_message["role"] == "tool"

            call_id = assistant_message["tool_calls"][0]["id"]
            assert tool_message["tool_call_id"] == call_id

            knowledge = json.loads(tool_message["content"])
            assert knowledge["price_cents"] == 19900
            assert knowledge["trial_available"] is None

            message = {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "topics": ["price", "trial", "refund"],
                        "knowledge_id": knowledge["knowledge_id"],
                        "knowledge_revision": knowledge["revision"],
                    }
                ),
            }
            finish_reason = "stop"

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": message,
                    }
                ]
            },
        )

    gateway = QwenModelGateway(
        Settings(
            llm_mode="live",
            llm_base_url="https://model.example.test/v1",
            llm_model="test-model",
            llm_api_key="synthetic-key",
        ),
        transport=httpx.MockTransport(handler),
    )

    messages = [
        ModelMessage(
            role="user",
            content="多少钱？能试听和退款吗？",
        )
    ]

    result = SalesTurnEngine(gateway).preview(
        messages=messages,
        product_id="demo_python_basic",
        tools=executor,
    )

    assert len(requests) == 2
    assert "199.00元" in result.reply.text
    assert "试听安排需要进一步核实" in result.reply.text
    assert "退款政策需要进一步核实" in result.reply.text
    assert result.retrieved_knowledge.price_cents == 19900
    assert [step.step for step in result.trace] == [
        "request_tool",
        "execute_tool",
        "generate_reply",
    ]
    assert all(step.status == "succeeded" for step in result.trace)
    assert all(step.duration_ms >= 0 for step in result.trace)

@pytest.mark.parametrize(
    ("case", "error_type", "error_code", "expected_steps"),
    [
        (
            "valid",
            None,
            None,
            ["request", "execute", "generate"],
        ),
        (
            "wrong_product",
            TurnValidationError,
            "model_product_mismatch",
            ["request"],
        ),
        (
            "unknown_tool",
            ToolExecutionError,
            "unknown_tool",
            ["request", "execute"],
        ),
        (
            "missing",
            ProductKnowledgeNotFoundError,
            "Published product knowledge not found",
            ["request", "execute"],
        ),
    ],
)
def test_engine_stops_at_failed_step(
    tmp_path,
    case,
    error_type,
    error_code,
    expected_steps,
):
    path = tmp_path / "products.json"
    path.write_bytes(DEFAULT_CATALOG_PATH.read_bytes())
    executor = SalesToolExecutor(KnowledgeRepository(path))

    steps = []

    class RecordingGateway(MockModelGateway):
        def request_product_tool(
            self,
            *,
            messages,
            product_id,
            tools,
        ):
            steps.append("request")

            return PendingToolCall(
                call_id="test-call",
                name=(
                    "send_message"
                    if case == "unknown_tool"
                    else "get_product_knowledge"
                ),
                arguments={
                    "product_id": (
                        "another-product"
                        if case == "wrong_product"
                        else product_id
                    ),
                },
            )

        def generate(self, **kwargs):
            steps.append("generate")
            return super().generate(**kwargs)

    class RecordingExecutor(SalesToolExecutor):
        def execute(self, **kwargs):
            steps.append("execute")
            return super().execute(**kwargs)

    tools = RecordingExecutor(executor.repository)
    engine = SalesTurnEngine(RecordingGateway())

    arguments = {
        "messages": [
            ModelMessage(role="user", content="课程多少钱？")
        ],
        "product_id": (
            "unknown-product"
            if case == "missing"
            else "demo_python_basic"
        ),
        "tools": tools,
    }

    if error_type is not None:
        with pytest.raises(error_type, match=error_code):
            engine.preview(**arguments)
    else:
        result = engine.preview(**arguments)
        assert "199.00元" in result.reply.text
        assert [step.step for step in result.trace] == [
            "request_tool",
            "execute_tool",
            "generate_reply",
        ]

    assert steps == expected_steps

