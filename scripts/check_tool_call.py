from app.config import load_settings
from app.knowledge import KnowledgeRepository
from app.llm import ModelMessage, QwenModelGateway
from app.services.turn_engine import SalesTurnEngine
from app.tools import SalesToolExecutor


def main():
    settings = load_settings()

    if settings.llm_mode != "live":
        raise RuntimeError("请先将 LLM_MODE 设置为 live")

    executor = SalesToolExecutor(KnowledgeRepository())
    gateway = QwenModelGateway(settings)
    engine = SalesTurnEngine(gateway)

    messages = [
        ModelMessage(
            role="user",
            content="这门课多少钱？能试听吗？可以退款吗？",
        )
    ]

    # 第一次模型调用：取得待执行的工具请求。
    call = gateway.request_product_tool(
        messages=messages,
        product_id="demo_python_basic",
        tools=executor.definitions(),
    )

    print("模型提出的工具请求：")
    print(call.model_dump_json(indent=2))

    # Python 程序执行工具。
    product = executor.execute(
        name=call.name,
        arguments=call.arguments,
    )

    if product is None:
        print("没有查到已发布资料，停止本次流程。")
        return

    print("程序执行后的查询结果：")
    print(product.model_dump_json(indent=2))

    # 第二次模型调用：回传工具结果，再校验和生成正文。
    reply = engine.run(
        messages=messages,
        product=product,
        tool_call=call,
    )

    print("最终回复：")
    print(reply.model_dump_json(indent=2))


if __name__ == "__main__":
    main()