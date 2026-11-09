from app.config import load_settings
from app.llm import QwenModelGateway


def main():
    settings = load_settings()

    if settings.llm_mode != "live":
        raise RuntimeError("请先将 LLM_MODE 设置为 live")

    source_text = "我没有编程基础。我想学会写自动化脚本。"

    batch = QwenModelGateway(settings).extract_memory_candidates(
        source_text=source_text,
    )

    print("合成客户原话：")
    print(source_text)
    print("待人工确认的候选，尚未保存：")
    print(batch.model_dump_json(indent=2))


if __name__ == "__main__":
    main()