"""Local CLI. It never publishes, places bets or sends user information."""

import argparse
import json
from pathlib import Path
import sys
import sqlite3

from .contracts import canonical, ContractError, shape
from .calendar_context import build_context
from .engine import freeze, evaluate, markdown_report, summary
from .journal import Journal, JournalError
from .router import compare
from .adapters.runes import RuneSessions
from .adapters.yijing import run as yijing_run
from .cycle_cli import add_commands, execute as execute_cycle
from research_stats.core import load_json


def read_json(path):
    return load_json(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="DIS universal research engine v0.3")
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
    for command in ("rune-prepare", "rune-select", "rune-status", "rune-reveal"):
        item = commands.add_parser(command)
        item.add_argument("--db", required=True, help="Private session DB, not the public journal")
        item.add_argument("--session-id", required=True)
        if command == "rune-prepare":
            item.add_argument("--event-id", required=True)
        elif command == "rune-select":
            item.add_argument("--slot", required=True, type=int)
            item.add_argument("--rotation", required=True, type=int, choices=(0, 180))
    yi = commands.add_parser("yijing", help="Six-line raw result only; no invented reading")
    yi.add_argument("--db", required=True)
    yi.add_argument("--run-id", required=True)
    yi.add_argument("--event-id", required=True)
    yi.add_argument("--throws", help="JSON array of six three-coin throws reported by the user")
    bundle = commands.add_parser("assemble", help="Build event/cards input from preserved adapter results")
    bundle.add_argument("--event", required=True, help="Event JSON")
    bundle.add_argument("--rune-db", required=True)
    bundle.add_argument("--rune-session", required=True)
    bundle.add_argument("--yijing-db", required=True)
    bundle.add_argument("--yijing-run", required=True)
    calendar = commands.add_parser("calendar-context", help="Calculate declared cultural calendar labels without drawing runes")
    calendar.add_argument("input", help="JSON with event, calendar_context and registered_at")
    add_commands(commands)
    args = parser.parse_args(argv)
    journal = None
    sessions = None
    try:
        if args.command == "calendar-context":
            data = read_json(args.input)
            shape(data, ("event", "calendar_context", "registered_at"))
            result = build_context(data["calendar_context"], data["event"], data["registered_at"])
        elif args.command.startswith("cycle-"):
            result = execute_cycle(args)
        elif args.command.startswith("rune-"):
            if args.command != "rune-prepare" and not Path(args.db).is_file():
                raise ContractError("rune session DB does not exist")
            sessions = RuneSessions(args.db)
            if args.command == "rune-prepare":
                result = sessions.prepare(args.session_id, args.event_id)
            elif args.command == "rune-select":
                result = sessions.select(args.session_id, args.slot, args.rotation)
            elif args.command == "rune-status":
                result = sessions.status(args.session_id)
            else:
                result = sessions.reveal(args.session_id)
        elif args.command == "yijing":
            journal = Journal(args.db)
            result = yijing_run(journal, args.run_id, args.event_id,
                                read_json(args.throws) if args.throws else None)
        elif args.command == "assemble":
            if not Path(args.rune_db).is_file() or not Path(args.yijing_db).is_file():
                raise ContractError("adapter database does not exist")
            sessions = RuneSessions(args.rune_db)
            journal = Journal(args.yijing_db); journal.verify()
            rune = sessions.status(args.rune_session)["card"]
            yi = journal.get(f"adapter:yijing:{args.yijing_run}")
            if rune is None or yi is None:
                raise ContractError("both adapter results must be completed")
            ev = read_json(args.event)
            compare(ev, [rune, yi])
            result = {"event": ev, "cards": [rune, yi]}
        elif args.command == "compare":
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
    except (ContractError, JournalError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if journal:
            journal.close()
        if sessions:
            sessions.close()


if __name__ == "__main__":
    raise SystemExit(main())
