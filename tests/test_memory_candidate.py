import json

import httpx
import pytest

from app.config import Settings
from app.llm import ModelCallError, QwenModelGateway


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("valid", None),
        ("empty", None),
        ("invented", "model_memory_quote_mismatch"),
        ("unknown_key", "model_invalid_memory_candidates"),
        ("extra_field", "model_invalid_memory_candidates"),
        ("duplicate_key", "model_invalid_memory_candidates"),
        ("truncated", "model_output_incomplete"),
    ],
)
def test_memory_candidate_validation(case, expected_error):
    source_text = "我没有编程基础。"

    candidate = {
        "fact_key": "current_level",
        "value": source_text,
    }

    if case == "invented":
        candidate["value"] = "我有三年编程经验。"
    elif case == "unknown_key":
        candidate["fact_key"] = "course_price"
    elif case == "extra_field":
        candidate["confirmed"] = True

    candidates = [candidate]

    if case == "empty":
        candidates = []
    elif case == "duplicate_key":
        candidates = [candidate, candidate]

    def handler(request):
        payload = json.loads(request.content)

        assert payload["messages"][-1] == {
            "role": "user",
            "content": source_text,
        }
        assert payload["response_format"] == {
            "type": "json_object",
        }

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": (
                            "length"
                            if case == "truncated"
                            else "stop"
                        ),
                        "message": {
                            "content": json.dumps(
                                {"candidates": candidates},
                                ensure_ascii=False,
                            ),
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

    if expected_error is not None:
        with pytest.raises(ModelCallError, match=expected_error):
            gateway.extract_memory_candidates(
                source_text=source_text,
            )
        return

    batch = gateway.extract_memory_candidates(
        source_text=source_text,
    )

    if case == "empty":
        assert batch.candidates == []
    else:
        assert len(batch.candidates) == 1
        assert batch.candidates[0].fact_key == "current_level"
        assert batch.candidates[0].value == source_text

def test_concern_rule_is_in_system_prompt():
    source_text = "我担心基础不够，可能跟不上。"
    response_content = {
        "candidates": [
            {
                "fact_key": "concern",
                "value": "可能跟不上",
            }
        ]
    }

    def handler(request):
        payload = json.loads(request.content)
        system_prompt = payload["messages"][0]["content"]

        assert "担心基础不够" in system_prompt
        assert "这是 concern 顾虑" in system_prompt
        assert "不能据此同时断定 current_level" in system_prompt

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                response_content,
                                ensure_ascii=False,
                            ),
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

    batch = gateway.extract_memory_candidates(
        source_text=source_text,
    )

    assert len(batch.candidates) == 1
    assert batch.candidates[0].fact_key == "concern"
    assert batch.candidates[0].value == "可能跟不上"