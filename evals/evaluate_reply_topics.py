import argparse
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.config import load_settings
from app.knowledge import KnowledgeRepository
from app.llm import ModelCallError, ModelMessage, QwenModelGateway
from app.services.reply_rendering import ReplyTopic
from app.services.turn_engine import (
    ProductKnowledgeNotFoundError,
    SalesTurnEngine,
    TurnValidationError,
)
from app.tools import SalesToolExecutor, ToolExecutionError


FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRODUCT_ID = "demo_python_basic"


class TopicCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    messages: list[ModelMessage] = Field(min_length=1)
    expected_topics: list[ReplyTopic] = Field(min_length=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="千问回复话题评测")
    parser.add_argument(
        "--live",
        action="store_true",
        help="发送合成样例到已配置的模型服务，可能产生费用",
    )
    parser.add_argument("--report", type=Path, help="将评测结果保存到指定 JSON 文件")
    args = parser.parse_args()
    if not args.live:
        parser.error("在线评测需要显式传入 --live")

    if args.report is not None and args.report.exists():
        parser.error("报告文件已存在，请换一个文件名")

    try:
        settings = load_settings()
    except ValidationError:
        parser.error("模型配置校验失败，请检查 LLM_* 配置")
    if settings.llm_mode != "live":
        parser.error("请使用已配置的 live 模式")

    cases_raw = (FIXTURES / "reply_topic_cases.json").read_bytes()
    cases = TypeAdapter(list[TopicCase]).validate_json(cases_raw)
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("样例不能为空，case_id 不能重复")
    for case in cases:
        if case.messages[-1].role != "user":
            raise ValueError(f"{case.case_id} 的最后一条必须是客户消息")

    catalog_path = FIXTURES / "reply_catalog.json"
    tools = SalesToolExecutor(KnowledgeRepository(catalog_path))
    engine = SalesTurnEngine(QwenModelGateway(settings))

    print(f"模型 {settings.llm_model}")
    print(f"样例 {sha256(cases_raw).hexdigest()[:12]}")
    print(f"知识快照 {sha256(catalog_path.read_bytes()).hexdigest()[:12]}")

    run_started_at = datetime.now(timezone.utc).isoformat()
    catalog_sha256 = sha256(catalog_path.read_bytes()).hexdigest()
    rows = []
    passed = failed = errors = 0

    for case in cases:
        started = perf_counter()
        expected = set(case.expected_topics)
        row = {
            "case_id": case.case_id,
            "expected_topics": sorted(expected),
        }

        try:
            result = engine.preview(
                messages=case.messages,
                product_id=PRODUCT_ID,
                tools=tools,
            )
            if result.reply.mode != "live":
                raise TurnValidationError("non_live_reply_in_topic_eval")
        except (
            ModelCallError,
            ToolExecutionError,
            TurnValidationError,
            ProductKnowledgeNotFoundError,
        ) as exc:
            errors += 1
            row.update(status="ERROR", actual_topics=None, error=str(exc))
            detail = str(exc)
        else:
            actual_topics = result.reply.topics
            actual = set(actual_topics)
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            duplicates = len(actual) != len(actual_topics)

            row.update(actual_topics=actual_topics, missing=missing, extra=extra)
            if missing or extra or duplicates:
                failed += 1
                row["status"] = "FAIL"
                detail = f"漏选 {missing} | 多选 {extra} | 重复 {duplicates}"
            else:
                passed += 1
                row["status"] = "PASS"
                detail = str(sorted(actual))

        row["duration_ms"] = round((perf_counter() - started) * 1000)
        rows.append(row)
        print(
            f"[{row['status']}] {case.case_id}"
            f" | {row['duration_ms']} ms | {detail}"
        )

    if args.report is not None:
        report = {
            "schema_version": 1,
            "rubric": "exact_topics_v1",
            "started_at": run_started_at,
            "model_name": settings.llm_model,
            "product_id": PRODUCT_ID,
            "dataset_sha256": sha256(cases_raw).hexdigest(),
            "catalog_sha256": catalog_sha256,
            "cases": rows,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")
        print(f"报告已保存到 {args.report}")

    print(f"通过 {passed}/{len(cases)} | 话题失败 {failed} | 调用或校验错误 {errors}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
