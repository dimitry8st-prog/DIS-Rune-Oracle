"""Read-only JSON CLI: python -m research_stats report input.json."""

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

from .core import field_distribution, joint_distribution, total_distribution, load_json, report, simulate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("distribution")
    report_parser = commands.add_parser("report")
    report_parser.add_argument("input", type=Path)
    sim = commands.add_parser("simulate")
    sim.add_argument("--n", type=int, required=True)
    sim.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "report":
            raw = args.input.read_bytes().replace(b"\r\n", b"\n")
            result = report(load_json(raw))
            result["input_sha256"] = hashlib.sha256(raw).hexdigest()
        elif args.command == "simulate":
            result = simulate(args.n, args.seed)
        else:
            result = {"assumption": "uniform 4-of-20; fields independent",
                      "per_field": field_distribution(), "joint": joint_distribution(),
                      "total": total_distribution()}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False,
                         default=lambda x: {"exact": str(x), "decimal": float(x)} if isinstance(x, Fraction) else str(x)))
    except (ValueError, OSError, OverflowError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
