"""Unified CLI lifecycle, with explicit synthetic clock overrides only."""
from pathlib import Path
from research_stats.core import load_json
from .contracts import canonical, ContractError
from .pipeline import Cycle


def add_commands(commands):
    for action in ("start", "step", "review", "freeze", "science", "evaluate", "status"):
        item = commands.add_parser("cycle-" + action, help="Integrated v0.3: " + action)
        item.add_argument("--directory", required=True, help="New v0.3 state directory; do not reuse old journal paths")
        item.add_argument("--run-id", required=True)
        if action in ("start", "step", "review", "science", "evaluate"):
            item.add_argument("input")
        if action in ("start", "freeze", "evaluate"):
            item.add_argument("--at", help="Clock declaration, accepted only for SYNTHETIC fixtures")
    demo = commands.add_parser("cycle-demo", help="Complete SYNTHETIC cycle with explicit future simulated outcome")
    demo.add_argument("--directory", required=True, help="Must be a new empty directory")


def execute(args):
    if args.command == "cycle-demo":
        return demo(args.directory)
    with Cycle(args.directory, args.run_id) as cycle:
        action = args.command.removeprefix("cycle-")
        data = load_json(Path(args.input).read_text(encoding="utf-8")) if hasattr(args, "input") else None
        if action == "start":
            return cycle.start(data, at=args.at)
        if action == "freeze":
            return cycle.freeze(at=args.at)
        if action == "evaluate":
            return cycle.evaluate(data, at=args.at)
        if action == "status":
            return cycle.status()
        return getattr(cycle, action)(data)


def demo(directory):
    root = Path(directory)
    if root.exists() and any(root.iterdir()):
        raise ContractError("demo directory must be empty; no outputs are overwritten")
    fixtures = Path(__file__).with_name("demo_manifest.json")
    manifest = load_json(fixtures.read_text(encoding="utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    review = {"claims_by_core": {}}
    outcome = {"event_id": manifest["event"]["event_id"], "axis_id": "target", "scenario_id": "A",
               "source": "SYNTHETIC deterministic teaching fixture; no actual draw", "observed_at": "2099-01-01T00:00:00Z"}
    numeric = {"event_id": outcome["event_id"], "occurred_at": outcome["observed_at"],
               "recorded_at": "2099-01-01T00:00:01Z", "confirmation": "CONFIRMED",
               "source_ref": outcome["source"], "fields": [[1, 2, 3, 4], [5, 6, 7, 8]]}
    for filename, value in (("manifest.json", manifest), ("review.json", review), ("outcome.json", outcome)):
        with (root / filename).open("x", encoding="utf-8") as stream:
            stream.write(canonical(value) + "\n")
    with Cycle(root / "state", "synthetic-v03") as cycle:
        cycle.start(manifest)
        cycle.step({"request_id": "observed-refusal", "operation": "confirm", "confirmation_result": "yin_bei"})
        cycle.step({"request_id": "finish-without-redraw", "operation": "finish"})
        cycle.review(review)
        original = cycle.freeze()
        before = cycle.science({"report_id": "before-outcome-v1", "reason": "Initial audit before synthetic outcome"})
        evaluation = cycle.evaluate(outcome, at="2099-01-01T00:00:02Z")
        after = cycle.science({"report_id": "after-outcome-v1", "reason": "Synthetic outcome added; original unchanged",
                               "supersedes": "before-outcome-v1", "numeric_outcomes": [numeric]})
        for name, value in (("original-report.json", original), ("science-before.json", before),
                            ("evaluation.json", evaluation), ("science-after.json", after)):
            with (root / name).open("x", encoding="utf-8") as stream:
                stream.write(canonical(value) + "\n")
        return {"provenance": "SYNTHETIC", "notice": "Outcome uses a future simulated clock, not a real forecast test",
                "directory": str(root), "categorical_abstained": evaluation["abstained"],
                "numeric_explicit_external_method_pairs": after["numeric_external_method"]["paired_total"]["n"],
                "chain": cycle.journal.verify()}
