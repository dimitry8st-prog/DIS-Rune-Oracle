"""Local CLI. It never publishes, places bets or sends user information."""

import argparse
import json
from pathlib import Path
import sys

from .contracts import canonical, ContractError
from .engine import freeze, evaluate, markdown_report, summary
from .journal import Journal, JournalError
from .router import compare


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="DIS universal research engine v0.1")
    commands = parser.add_subparsers(dest="command", required=True)
    route = commands.add_parser("compare", help="Validate and compare without freezing a forecast")
    route.add_argument("input", help="JSON with event and cards")
    frozen = commands.add_parser("freeze", help="Freeze registered inputs and comparison")
    frozen.add_argument("input")
    frozen.add_argument("--run-id", required=True)
    frozen.add_argument("--db", required=True)
    frozen.add_argument("--markdown", help="New local report path; existing file is not overwritten")
    outcome = commands.add_parser("evaluate", help="Record a resolved outcome")
    outcome.add_argument("input", help="Outcome JSON")
    outcome.add_argument("--run-id", required=True)
    outcome.add_argument("--db", required=True)
    for command in ("verify", "export", "summary"):
        item = commands.add_parser(command)
        item.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    journal = None
    try:
        if args.command == "compare":
            data = read_json(args.input)
            result = compare(data["event"], data["cards"])
        else:
            # A missing DB is only created for a new freeze, never for audit/evaluation.
            if args.command != "freeze" and not Path(args.db).is_file():
                raise ContractError("journal does not exist")
            journal = Journal(args.db)
            if args.command == "freeze":
                if args.markdown and Path(args.markdown).exists():
                    raise ContractError("report file exists; choose a new path")
                data = read_json(args.input)
                result = freeze(journal, args.run_id, data["event"], data["cards"])
                if args.markdown:
                    with Path(args.markdown).open("x", encoding="utf-8") as file:
                        file.write(markdown_report(result))
            elif args.command == "evaluate":
                result = evaluate(journal, args.run_id, read_json(args.input))
            elif args.command == "verify":
                result = journal.verify()
            elif args.command == "summary":
                result = summary(journal)
            else:
                result = journal.export()
        print(canonical(result))
        return 0
    except (ContractError, JournalError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
