"""Self-contained synthetic lifecycle, never a real study registration."""
from pathlib import Path

from research_stats.core import load_json
from . import combination_lab as lab
from .contracts import ContractError, canonical
from .journal import Journal


def demo(directory):
    root = Path(directory)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ContractError("demo needs a new empty directory; no outputs overwritten")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = load_json(Path(__file__).with_name("lab_demo.json").read_text(encoding="utf-8"))
    journal = Journal(root / "lab.sqlite3")
    try:
        study_id = data["protocol"]["study_id"]
        registered = lab.register(journal, data["protocol"], at=data["registration_at"])
        frozen = lab.freeze(journal, study_id, data["trial"], at=data["freeze_at"])
        replay = lab.freeze(journal, study_id, data["trial"], at=data["freeze_at"])
        if frozen != replay:
            raise ContractError("synthetic replay differs")
        outcome = lab.evaluate(journal, study_id, data["outcome"], at=data["resolve_at"])
        report = lab.summary(journal, study_id)
        for name, value in [("registration.json", registered), ("selection.json", frozen),
                            ("evaluation.json", outcome), ("summary.json", report)]:
            with (root / name).open("x", encoding="utf-8") as out:
                out.write(canonical(value) + "\n")
        return {"provenance": "SYNTHETIC", "notice": data["notice"], "directory": str(root),
                "summary": report, "journal": journal.verify(), "exact_replay": frozen == replay}
    finally:
        journal.close()
