"""CLI for numeric mechanics in a dedicated database, separate from engine CLI."""

import argparse
import json
import sqlite3
import sys

from ..contracts import ContractError
from ..journal import JournalError
from .mo import MoSessions
from .qiuqian import QiuqianSessions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("mo-run", "mo-status", "qiuqian-start", "qiuqian-status",
                    "qiuqian-confirm", "qiuqian-advance", "qiuqian-finish"):
        item = commands.add_parser(command)
        item.add_argument("--db", required=True, help="dedicated mechanics SQLite database")
        item.add_argument("--session-id", required=True)
        item.add_argument("--event-id", required=True)
        if command in ("mo-run", "qiuqian-start"):
            item.add_argument("--mode", required=True, choices=("manual", "digital", "historical"))
        if command == "mo-run":
            item.add_argument("--first-throw", type=int)
            item.add_argument("--second-throw", type=int)
        if command == "qiuqian-start":
            item.add_argument("--max-attempts", type=int, default=3)
            item.add_argument("--stick-number", type=int)
            item.add_argument("--confirmation-result")
        if command in ("qiuqian-confirm", "qiuqian-advance", "qiuqian-finish"):
            item.add_argument("--request-id", required=True)
        if command == "qiuqian-confirm":
            item.add_argument("--confirmation-result", required=True)
    args = parser.parse_args(argv)
    cls = MoSessions if args.command.startswith("mo-") else QiuqianSessions
    try:
        with cls(args.db) as sessions:
            ids = (args.session_id, args.event_id)
            if args.command == "mo-run":
                card = sessions.run(*ids, mode=args.mode, first_throw=args.first_throw, second_throw=args.second_throw)
            elif args.command == "qiuqian-start":
                card = sessions.start(*ids, mode=args.mode, max_attempts=args.max_attempts,
                                      stick_number=args.stick_number, confirmation_result=args.confirmation_result)
            elif args.command == "qiuqian-confirm":
                card = sessions.confirm(*ids, args.request_id, args.confirmation_result)
            elif args.command == "qiuqian-advance":
                card = sessions.advance(*ids, args.request_id)
            elif args.command == "qiuqian-finish":
                card = sessions.finish(*ids, args.request_id)
            else:
                card = sessions.status(*ids)
        print(json.dumps(card, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (ContractError, JournalError, sqlite3.Error, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
