"""Simple parsing evaluation; explicitly label rules vs live LLM modes.

Run: python scripts/evaluate.py --mode rules
     python scripts/evaluate.py --mode llm  # requires API key and sends requests
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ossie_demo.catalog import Catalog, SemanticError  # noqa: E402
from ossie_demo.parsing import rule_parse, llm_parse  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["rules", "llm"], default="rules")
    args = parser.parse_args()
    catalog = Catalog(ROOT / "models/gaming.yaml")
    cases = [json.loads(line) for line in (ROOT / "evals/questions.jsonl").read_text().splitlines()]
    ok = 0
    for case in cases:
        try:
            q = (rule_parse(case["question"], catalog, today=date.today()) if args.mode == "rules"
                 else llm_parse(case["question"], catalog, today=date.today()))
            matched = (q.metrics == case["metrics"] and q.dimensions == case["dimensions"]
                       and q.filters == case["filters"]
                       and q.time_grain == case.get("time_grain"))
        except (SemanticError, ValueError) as exc:
            print(f"FAIL: {case['question']} ({exc})")
            matched = False
        ok += bool(matched)
        print(("PASS" if matched else "FAIL"), case["question"])
    print(f"\n{args.mode} semantic parsing accuracy: {ok}/{len(cases)}")
    if ok != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
