import argparse
import sys

from sqlalchemy.orm import Session

from app.database import DATABASE_PATH, engine
from app.schemas.suggestions import CreateSuggestionRequest
from app.services.errors import ServiceError
from app.services.generation_requests import (
    get_generation_request,
    mark_generation_failed,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="服务停止后，将确认中断的生成请求标记为失败。"
    )
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--request-key", required=True)
    args = parser.parse_args(argv)

    if not DATABASE_PATH.is_file():
        print(f"业务数据库不存在：{DATABASE_PATH}", file=sys.stderr)
        return 1

    conversation_id = args.conversation_id
    request_key = args.request_key.strip()

    with Session(engine) as db:
        try:
            row = get_generation_request(
                conversation_id,
                request_key,
                db,
            )
        except ServiceError as exc:
            print(exc.detail, file=sys.stderr)
            return 1

        if row.status != "running":
            print(f"当前状态为 {row.status}，无需恢复。")
            return 0

        body = CreateSuggestionRequest(
            request_key=row.request_key,
            based_on_version=row.based_on_version,
            product_id=row.product_id,
        )

        # 先复制原请求的输入，再结束读取事务。
        db.rollback()

        changed = mark_generation_failed(
            conversation_id,
            body,
            db,
            error_code="generation_interrupted",
        )

    if not changed:
        print("记录状态已变化，请重新查询。", file=sys.stderr)
        return 1

    print("请求已标记为 failed，错误码为 generation_interrupted。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
