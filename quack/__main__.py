import argparse
import json
import sys
from dataclasses import asdict


def run_index(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m quack index")
    parser.add_argument("--full", action="store_true", help="ignore the checkpoint")
    parser.add_argument("--limit", type=int, help="index at most N pages, oldest first")
    options = parser.parse_args(argv)

    from quack.retrieval import indexer

    report = indexer.run(full=options.full, limit=options.limit)
    print(json.dumps(asdict(report), indent=2))
    sys.exit(0 if report.complete else 1)


def run_question(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m quack")
    parser.add_argument("--lc", action="store_true", help="use the LangChain agent")
    parser.add_argument("question", nargs="+", help="your question")
    options = parser.parse_args(argv)

    if options.lc:
        from quack.agent_lc import ask
    else:
        from quack.agent import ask

    print(ask(" ".join(options.question)))


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "index":
        run_index(argv[1:])
    else:
        run_question(argv)


if __name__ == "__main__":
    main()
