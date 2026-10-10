import argparse
import json
import sys

from evals import runner


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals", description="Score Quack against evals/questions.json")
    parser.add_argument("--ids", help="comma-separated question ids to run")
    parser.add_argument("--repeat", type=int, default=1, help="runs per question")
    parser.add_argument("--file", help="path to a questions file", default=str(runner.QUESTIONS_PATH))
    args = parser.parse_args()

    ids = set(args.ids.split(",")) if args.ids else None
    try:
        questions = runner.load_questions(args.file, ids)
    except (runner.EvalSetError, OSError, ValueError) as e:
        sys.exit(f"Could not load questions: {e}")
    if not questions:
        sys.exit("No questions to run. Add entries to evals/questions.json.")

    rows = runner.run_all(
        questions, on_result=lambda row: print(runner.format_row(row), flush=True), repeat=max(1, args.repeat)
    )
    path = runner.write_report(rows)

    summary = json.loads(path.read_text(encoding="utf-8"))["summary"]
    print()
    print(json.dumps(summary, indent=2))
    print(f"Report: {path}")
    sys.exit(0 if summary["fail"] == 0 and summary["error"] == 0 else 1)


if __name__ == "__main__":
    main()
