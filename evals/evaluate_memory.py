from app.config import load_settings
from app.llm import QwenModelGateway

CASES = [
    {
        "name": "明确陈述",
        "text": "我没有编程基础。我想学会写自动化脚本。",
        "expected_quotes": {
            "current_level": ["没有编程基础"],
            "learning_goal": ["学会写自动化脚本"],
        },
    },
    {
        "name": "他人情况",
        "text": "我妹妹没有编程基础，我想替她问下课程。",
        "expected_quotes": {},
    },
    {
        "name": "假设问题",
        "text": "如果我零基础转行，能找到工作吗？",
        "expected_quotes": {},
    },
    {
        "name": "保留否定",
        "text": "我不是零基础，之前学过一些 Java。",
        "expected_quotes": {
            "current_level": ["不是零基础"],
        },
    },
    {
        "name": "明确偏好",
        "text": "我更喜欢周末线上学习。",
        "expected_quotes": {
            "preferred_format": ["周末线上学习"],
        },
    },
    {
        "name": "明确顾虑",
        "text": "我担心基础不够，可能跟不上。",
        "expected_quotes": {
            "concern": ["担心基础不够", "可能跟不上"],
        },
    },
]


def main():
    settings = load_settings()

    if settings.llm_mode != "live":
        raise RuntimeError("请先将 LLM_MODE 设置为 live")

    gateway = QwenModelGateway(settings)

    true_positive = 0
    false_positive = 0
    false_negative = 0
    failed_cases = []

    for case in CASES:
        batch = gateway.extract_memory_candidates(
            source_text=case["text"],
        )

        expected_quotes = case["expected_quotes"]
        expected = set(expected_quotes)
        matched = set()
        case_false_positive = 0

        for candidate in batch.candidates:
            # 只计入标签符合预期且内容确实来自原话的候选。
            preserves_expected_meaning = any(
                quote in candidate.value
                for quote in expected_quotes.get(
                    candidate.fact_key,
                    [],
                )
            )

            if (
                    candidate.fact_key in expected
                    and candidate.value in case["text"]
                    and preserves_expected_meaning
                    and candidate.fact_key not in matched
            ):
                matched.add(candidate.fact_key)
                true_positive += 1
            else:
                false_positive += 1
                case_false_positive += 1

        missing = expected - matched
        false_negative += len(missing)

        passed = not missing and case_false_positive == 0
        if not passed:
            failed_cases.append(case["name"])

        print(f"\n[{'PASS' if passed else 'FAIL'}] {case['name']}")
        print(f"原话：{case['text']}")
        print(f"预期类别：{sorted(expected)}")
        print(
            "模型候选："
            + str(
                [
                    {
                        "fact_key": item.fact_key,
                        "value": item.value,
                    }
                    for item in batch.candidates
                ]
            )
        )

    precision = true_positive / max(
        true_positive + false_positive,
        1,
    )
    recall = true_positive / max(
        true_positive + false_negative,
        1,
    )

    print("\n评测统计")
    print(f"Precision: {precision:.3f}")
    print(f"Recall:    {recall:.3f}")
    print(f"通过样例:  {len(CASES) - len(failed_cases)}/{len(CASES)}")

    if failed_cases:
        print(f"未通过: {', '.join(failed_cases)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
