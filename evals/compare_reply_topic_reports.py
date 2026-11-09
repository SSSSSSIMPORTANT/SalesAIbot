import argparse
import json
from pathlib import Path


COMPARISON_FIELDS = (
    "schema_version",
    "rubric",
    "product_id",
    "dataset_sha256",
    "catalog_sha256",
)


def read_report(path: Path) -> tuple[dict, dict[str, str]]:
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if report["schema_version"] != 1:
        raise ValueError(f"不支持的报告版本 {path}")

    rows = report["cases"]
    statuses = {row["case_id"]: row["status"] for row in rows}
    if not statuses or len(statuses) != len(rows):
        raise ValueError(f"报告为空或有重复的 case_id {path}")
    if set(statuses.values()) - {"PASS", "FAIL", "ERROR"}:
        raise ValueError(f"报告里有未知状态 {path}")
    return report, statuses


def main() -> int:
    parser = argparse.ArgumentParser(description="比较两轮回复话题评测")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()

    try:
        baseline, before = read_report(args.baseline)
        candidate, after = read_report(args.candidate)
        mismatches = [
            field for field in COMPARISON_FIELDS
            if baseline[field] != candidate[field]
        ]
        if mismatches:
            parser.error(f"报告不可比较，以下字段不同 {', '.join(mismatches)}")
        if before.keys() != after.keys():
            parser.error("报告里的 case_id 集合不同")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.error(f"无法读取报告 {exc}")

    print(f"基线模型 {baseline['model_name']} → 本轮模型 {candidate['model_name']}")
    regressions = 0
    for case_id in sorted(before):
        old, new = before[case_id], after[case_id]
        if old != new:
            print(f"{case_id} | {old} → {new}")
        if old == "PASS" and new != "PASS":
            regressions += 1

    print(f"基线通过 {sum(value == 'PASS' for value in before.values())}/{len(before)}")
    print(f"本轮通过 {sum(value == 'PASS' for value in after.values())}/{len(after)}")
    print(f"回归 {regressions} 项")
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
