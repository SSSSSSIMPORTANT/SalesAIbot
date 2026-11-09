from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.knowledge import KnowledgeRepository
from app.llm import MockModelGateway, ModelMessage, ModelPlan, ReplyDraft
from app.services.reply_rendering import ReplyTopic
from app.services.turn_engine import (
    ProductKnowledgeNotFoundError,
    SalesTurnEngine,
    TurnValidationError,
)
from app.tools import SalesToolExecutor


EVAL_DIR = Path(__file__).resolve().parent


class ReplyCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    message: str
    product_id: str
    model_topics: list[ReplyTopic] = Field(default_factory=lambda: ["price"])
    model_product_id: str | None = None
    model_revision: str | None = None
    expected_source: tuple[str, str] | None = None
    expected_error: str | None = None
    expected_generate_calls: int = 1
    required_text: list[str] = Field(default_factory=list)
    forbidden_text: list[str] = Field(default_factory=list)


class EvalGateway(MockModelGateway):
    def __init__(self, case: ReplyCase):
        self.case = case
        self.generate_calls = 0

    def request_product_tool(self, *, messages, product_id, tools):
        return super().request_product_tool(
            messages=messages,
            product_id=self.case.model_product_id or product_id,
            tools=tools,
        )

    def generate(self, *, messages, product=None, tool_call=None, memories=()):
        self.generate_calls += 1
        assert product is not None

        return ModelPlan(
            draft=ReplyDraft(
                topics=self.case.model_topics,
                knowledge_id=product.knowledge_id,
                knowledge_revision=self.case.model_revision or product.revision,
            ),
            model_name="scripted-eval",
            mode="mock",
        )


def run_case(case: ReplyCase, tools: SalesToolExecutor) -> list[str]:
    gateway = EvalGateway(case)
    result = None
    error = None

    try:
        result = SalesTurnEngine(gateway).preview(
            messages=[ModelMessage(role="user", content=case.message)],
            product_id=case.product_id,
            tools=tools,
        )
    except ProductKnowledgeNotFoundError:
        error = "published_knowledge_not_found"
    except TurnValidationError as exc:
        error = str(exc)

    failures = []
    if error != case.expected_error:
        failures.append(f"预期错误 {case.expected_error!r}，实际 {error!r}")
    if gateway.generate_calls != case.expected_generate_calls:
        failures.append(f"生成步骤实际执行 {gateway.generate_calls} 次")

    if result is not None:
        reply = result.reply
        source = (reply.knowledge_id, reply.knowledge_revision)
        if source != case.expected_source:
            failures.append(f"预期来源 {case.expected_source!r}，实际 {source!r}")
        for text in case.required_text:
            if text not in reply.text:
                failures.append(f"缺少正文片段 {text!r}")
        for text in case.forbidden_text:
            if text in reply.text:
                failures.append(f"出现禁止片段 {text!r}")

    return failures


def main() -> int:
    cases_path = Path(__file__).resolve().parent / "fixtures" / "reply_cases.json"
    cases_raw = cases_path.read_bytes()
    cases = TypeAdapter(list[ReplyCase]).validate_json(cases_raw)
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("评测集必须有样例，且 case_id 不能重复")

    catalog_path = EVAL_DIR / "fixtures" / "reply_catalog.json"
    tools = SalesToolExecutor(KnowledgeRepository(catalog_path))
    print(f"离线评测 | 样例 {sha256(cases_raw).hexdigest()[:12]}")
    print(f"知识快照 | {sha256(catalog_path.read_bytes()).hexdigest()[:12]}")

    passed = 0
    for case in cases:
        failures = run_case(case, tools)
        if failures:
            print(f"[FAIL] {case.case_id} | {'；'.join(failures)}")
        else:
            print(f"[PASS] {case.case_id}")
            passed += 1

    print(f"通过 {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())