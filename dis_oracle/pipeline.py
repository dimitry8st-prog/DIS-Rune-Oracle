"""Integrated, local-only v0.3 lifecycle. Original records are never rewritten.

The cycle lock serializes adapter dispatch across the separate private stores.
Hashes and local time declarations do not authenticate sources or predictiveness.
"""
from copy import deepcopy
from pathlib import Path

from research_stats.core import report as statistics_report, paired_summary
from . import __version__
from .contracts import (ContractError, CORES, digest, now_iso, shape, text,
                        timestamp, validate_event, validate_cards)
from .engine import freeze, evaluate
from .journal import Journal, JournalError
from .adapters import audited_inputs
from .calendar_context import validate_context, build_context
from .adapters.runes import RuneSessions
from .adapters.yijing import run as yijing_run, calculate
from .adapters.mo import MoSessions
from .adapters.qiuqian import QiuqianSessions, check_confirmation, MAX_ATTEMPTS
from .adapters.mechanics_store import integer, mode_check

VERSION = "integrated-cycle-v0.3"
LIMITATIONS = [
    "Technical tests do not demonstrate predictive efficacy; reverse time remains untested.",
    "Times, reviewer identities and outcome sources are declarations, not independent attestations.",
    "Local hash chains detect changes, not administrator replacement of all files or deletion of a chain suffix.",
    "Support percentages are not probabilities; no Brier score is inferred from core weights.",
    "Independent pairs, prespecified sampling/stopping and nonselective missingness are needed for inference.",
    "Mo/Qiuqian historical corpora and selected temple procedure remain unavailable.",
    "Additional core cards are explicit conditional models/manual observations, not source-verified historical readings.",
]


def validate_manifest(manifest, at):
    shape(manifest, ("schema_version", "provenance", "event", "adapters", "source_refs"), ("numeric_study", "calendar_context"))
    if manifest["schema_version"] != VERSION or manifest["provenance"] not in ("SYNTHETIC", "IMPORTED"):
        raise ContractError("unsupported cycle schema/provenance")
    axes = validate_event(manifest["event"])
    if not isinstance(manifest["source_refs"], list):
        raise ContractError("source_refs must be an array")
    for ref in manifest["source_refs"]:
        text(ref, "source_ref")
    if timestamp(manifest["event"]["cutoff_at"]) > timestamp(at):
        raise ContractError("event cutoff is after registration")
    if manifest["event"]["mode"] == "forecast" and any(timestamp(a["deadline"]) <= timestamp(at) for a in axes.values()):
        raise ContractError("late cycle registration; use retrospective mode")
    if "calendar_context" in manifest:
        validate_context(manifest["calendar_context"], manifest["event"], at)
    adapters = manifest["adapters"]
    shape(adapters, (), ("rune", "yijing", "mo", "qiuqian", "maya", "shakuna", "slavic", "name_grids"))
    for core, config in adapters.items():
        if core in ("maya", "shakuna", "slavic", "name_grids"):
            audited_inputs.validate_config(core, config)
            # Reported observations must already exist when the cycle is registered.
            observed = ([config["observation"]["observed_at"]] if core == "shakuna" else
                        [r["returned_at"] for r in config["rounds"]] if core == "slavic" else [])
            if any(timestamp(t) > min(timestamp(at), timestamp(manifest["event"]["cutoff_at"])) for t in observed):
                raise ContractError("reported observation is after registration/fact cutoff")
        elif core == "rune":
            shape(config, ("choices",))
            choices = config["choices"]
            if not isinstance(choices, list) or len(choices) != 3:
                raise ContractError("rune needs exactly three ordered choices")
            for choice in choices:
                shape(choice, ("slot", "rotation"))
                integer(choice["slot"], "slot", 1, 25)
                if type(choice["rotation"]) is not int or choice["rotation"] not in (0, 180):
                    raise ContractError("rotation must be integer 0 or 180")
            if len({c["slot"] for c in choices}) != 3:
                raise ContractError("duplicate rune slot")
        elif core == "yijing":
            shape(config, ("mode",), ("throws",))
            mode_check(config["mode"], "Yijing historical reading is unavailable")
            if config["mode"] == "manual":
                calculate(config.get("throws"))
            elif "throws" in config:
                raise ContractError("digital Yijing conflicts with reported throws")
        else:
            allowed = ("first_throw", "second_throw") if core == "mo" else ("stick_number", "confirmation_result")
            shape(config, ("mode",) if core == "mo" else ("mode", "max_attempts"), allowed)
            mode_check(config["mode"], f"{core} historical protocol is unavailable")
            if config["mode"] == "digital" and any(k in config for k in allowed):
                raise ContractError("digital mode conflicts with manual input")
            if core == "mo" and config["mode"] == "manual":
                for k in allowed:
                    integer(config.get(k), k, 1, 6)
            elif core == "qiuqian":
                integer(config["max_attempts"], "max_attempts", 0, MAX_ATTEMPTS)
                if config["mode"] == "manual":
                    integer(config.get("stick_number"), "stick_number", 1, 100)
                    if "confirmation_result" in config:
                        check_confirmation(config["confirmation_result"])
                        if config["max_attempts"] == 0:
                            raise ContractError("zero attempt limit conflicts with confirmation")
    study = manifest.get("numeric_study")
    if study is not None:
        # An explicit external numeric method, never a conversion from rune symbols.
        data = deepcopy(study)
        if data.get("outcomes") != []:
            raise ContractError("numeric outcomes cannot be supplied at registration")
        if data.get("provenance") != manifest["provenance"]:
            raise ContractError("numeric provenance mismatch")
        data["analysis_at"] = at
        statistics_report(data)
        if len(axes) != 1 or len(data["events"]) != 1:
            raise ContractError("numeric bridge currently supports one event and one axis")
        event = data["events"][0]
        if event["event_id"] != manifest["event"]["event_id"] or timestamp(event["target_at"]) != timestamp(next(iter(axes.values()))["deadline"]):
            raise ContractError("numeric study event/target does not match cycle")
        if manifest["event"]["mode"] != "forecast" and any(p["mode"] == "forecast" for p in data["predictions"]):
            raise ContractError("retrospective cycle cannot import prospective numeric predictions")
    return axes


class Cycle:
    """Use a NEW directory for v0.3 state; private sessions are not exported."""
    def __init__(self, directory, run_id):
        text(run_id, "run_id")
        self.root, self.run_id = Path(directory), run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.prefix = "cycle:" + digest(run_id)
        self.private = self.root / "private" / digest(run_id)
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            import fcntl
        except ImportError as exc:
            raise ContractError("integrated cycles require POSIX fcntl; Windows cycles are not supported") from exc
        self.lock = (self.root / "cycle.lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.journal = Journal(self.root / "cycle-v03.sqlite3")

    def close(self):
        self.journal.close()
        self.lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _get(self, suffix):
        self.journal.verify()
        return self.journal.get(f"{self.prefix}:{suffix}")

    def _save(self, suffix, value):
        self.journal.append(f"{self.prefix}:{suffix}", value)
        return value

    def _registration(self):
        reg = self._get("registered")
        if not reg:
            raise ContractError("start the cycle first")
        return reg

    def _time(self, manifest, at):
        if at is not None and manifest["provenance"] != "SYNTHETIC":
            raise ContractError("clock overrides are allowed only for SYNTHETIC data")
        value = at or now_iso()
        timestamp(value)
        return value

    def start(self, manifest, *, at=None):
        # Exact manifest replay is checked BEFORE adapter dispatch or RNG.
        existing = self._get("registered")
        if existing:
            if digest(existing["manifest"]) != digest(manifest):
                raise JournalError("cycle inputs/configuration changed")
            if at is not None and at != existing["registered_at"]:
                raise JournalError("registration time changed")
        else:
            fixed_at = self._time(manifest, at)
            validate_manifest(manifest, fixed_at)  # all inputs before any randomness
            registration = {"state": "REGISTERED", "pipeline_version": VERSION,
                            "package_version": __version__, "registered_at": fixed_at,
                            "synthetic_clock": at is not None, "manifest_hash": digest(manifest), "manifest": manifest}
            if "calendar_context" in manifest:
                # Capture local source data in the registration itself: a crash before
                # collection must not substitute a changed calendar corpus on restart.
                registration["calendar_snapshot"] = build_context(manifest["calendar_context"], manifest["event"], fixed_at)
            # One local run per event prevents drawing several cycles and exporting only a favorite.
            self.journal.append("cycle-event:" + digest(manifest["event"]["event_id"]),
                                {"run_id": self.run_id, "manifest_hash": digest(manifest)})
            self._save("registered", registration)
        if not self._get("collected"):
            self._collect()
        return self.status()

    def _collect(self):
        reg = self._registration()
        manifest = reg["manifest"]
        if "calendar_snapshot" in reg:
            snapshot = self._get("calendar-context-v1")
            if snapshot is None:
                self._save("calendar-context-v1", reg["calendar_snapshot"])
            elif digest(snapshot) != digest(reg["calendar_snapshot"]):
                raise JournalError("calendar snapshot differs from registration")
        eid = manifest["event"]["event_id"]
        cards = []
        for core in (c for c in CORES if c in manifest["adapters"]):
            config = manifest["adapters"][core]
            sid = f"v03-{digest([self.run_id, core])}"
            if core == "rune":
                store = RuneSessions(self.private / "rune.sqlite3")
                try:
                    state = store.prepare(sid, eid)
                    # Resume a partially completed selection without drawing a new manifest.
                    if state["choices"] != config["choices"][:len(state["choices"])]:
                        raise ContractError("saved rune choices conflict with configuration")
                    for choice in config["choices"][len(state["choices"]):]:
                        state = store.select(sid, **choice)
                    card = state["card"]
                finally:
                    store.close()
            elif core in ("maya", "shakuna", "slavic", "name_grids"):
                key = "adapter:audited:" + sid
                card = self.journal.get(key)
                if card is None:
                    card = audited_inputs.card(core, eid, config)
                    self.journal.append(key, card)
                if card["inputs"] != {"event_id": eid, **config}:
                    raise ContractError("saved audited adapter inputs differ")
            elif core == "yijing":
                card = yijing_run(self.journal, sid, eid, config.get("throws"))
            else:
                cls = MoSessions if core == "mo" else QiuqianSessions
                with cls(self.private / f"{core}.sqlite3") as store:
                    card = store.run(sid, eid, **config) if core == "mo" else store.start(sid, eid, **config)
            cards.append(card)
        validate_cards(cards, validate_event(manifest["event"]))
        return self._save("collected", {"state": "COLLECTED", "cards": cards,
                                       "registration_hash": digest(reg)})

    def _calendar_attachment(self, cards):
        reg = self._registration()
        if "calendar_context" not in reg["manifest"]:
            return None
        snapshot = self._get("calendar-context-v1")
        if snapshot is None or digest(snapshot) != digest(reg.get("calendar_snapshot")):
            raise JournalError("registered calendar snapshot is missing or differs")
        rune = next((card for card in cards if card["core_id"] == "rune"), None)
        binding = {"status": "ABSTAIN", "core_id": "rune", "reason": "RUNE_UNAVAILABLE"}
        if rune is not None:
            binding = {"status": "BOUND", "core_id": "rune", "card_input_hash": rune["input_hash"],
                       "procedure_commitment": rune["raw_result"]["commitment"]}
        return {"relation": "CULTURAL_CONTEXT_ONLY", "snapshot": snapshot,
                "snapshot_hash": digest(snapshot), "rune_binding": binding}

    def step(self, command):
        """One explicit idempotent Qiuqian command; never an automatic redraw."""
        shape(command, ("request_id", "operation"), ("confirmation_result",))
        reg = self._registration()
        if "qiuqian" not in reg["manifest"]["adapters"]:
            raise ContractError("qiuqian is not registered")
        operation = command["operation"]
        if operation not in ("confirm", "advance", "finish"):
            raise ContractError("operation must be confirm, advance or finish")
        if operation != "confirm" and "confirmation_result" in command:
            raise ContractError("only confirm accepts manual observations")
        if operation == "confirm":
            check_confirmation(command.get("confirmation_result"))
        text(command["request_id"], "request_id")
        key = "step:" + digest(command["request_id"])
        old = self._get(key)
        if old:
            if digest(old["command"]) != digest(command):
                raise JournalError("command inputs changed")
            return old
        if self._get("original") or self._get("review"):
            raise ContractError("procedure is fixed; no further commands after review/freeze")
        eid = reg["manifest"]["event"]["event_id"]
        sid = f"v03-{digest([self.run_id, 'qiuqian'])}"
        with QiuqianSessions(self.private / "qiuqian.sqlite3") as store:
            method = getattr(store, operation)
            params = (command["confirmation_result"],) if operation == "confirm" else ()
            card = method(sid, eid, command["request_id"], *params)
        return self._save(key, {"command": command, "card": card})

    def _cards(self):
        collected = self._get("collected")
        if not collected:
            raise ContractError("adapter collection is incomplete; retry start")
        cards = deepcopy(collected["cards"])
        if any(c["core_id"] == "qiuqian" for c in cards):
            sid = f"v03-{digest([self.run_id, 'qiuqian'])}"
            eid = self._registration()["manifest"]["event"]["event_id"]
            with QiuqianSessions(self.private / "qiuqian.sqlite3") as store:
                latest = store.status(sid, eid)
            cards = [latest if c["core_id"] == "qiuqian" else c for c in cards]
        return cards

    def review(self, reviews):
        """Explicit user claims only. No mapping, promotion or text replacement."""
        shape(reviews, ("claims_by_core",))
        shape(reviews["claims_by_core"], (), CORES)
        old = self._get("review")
        if old:
            if digest(old["request"]) != digest(reviews):
                raise JournalError("review fixed; changed claims require a new cycle")
            return old
        if self._get("original"):
            raise ContractError("original report is immutable")
        cards = self._cards()
        present = {c["core_id"] for c in cards}
        if set(reviews["claims_by_core"]) - present:
            raise ContractError("cannot review an unavailable core")
        for card in cards:
            card["claims"] = deepcopy(reviews["claims_by_core"].get(card["core_id"], []))
        event = self._registration()["manifest"]["event"]
        validate_cards(cards, validate_event(event))
        axes = validate_event(event)
        for card in cards:
            raw = card["raw_result"]
            reading_at = raw.get("reading_fixed_at", raw.get("generated_at")) if isinstance(raw, dict) else None
            for claim in card["claims"]:
                if claim.get("reviewed_at") and reading_at and timestamp(claim["reviewed_at"]) < timestamp(reading_at):
                    raise ContractError("claim review precedes the adapter reading")
                if claim.get("reviewed_at") and event["mode"] == "forecast":
                    # Every forecast axis must still be freezable, including other axes.
                    if any(timestamp(claim["reviewed_at"]) >= timestamp(a["deadline"]) for a in axes.values()):
                        raise ContractError("review is incompatible with forecast deadlines; state unchanged")
        return self._save("review", {"state": "REVIEWED", "request": reviews,
                                     "original_cards_hash": digest(self._cards()), "cards": cards})

    def freeze(self, *, at=None):
        old = self._get("original")
        if old:
            if at is not None and at != old["frozen"]["frozen_at"]:
                raise JournalError("original freeze time cannot be replaced")
            return old
        reg = self._registration()
        review = self._get("review")
        if review is None:
            raise ContractError("explicit review required (empty claims_by_core is valid abstention)")
        if review["original_cards_hash"] != digest(self._cards()):
            raise ContractError("adapter state changed after review; stop and audit separately")
        when = self._time(reg["manifest"], at)
        if timestamp(when) < timestamp(reg["registered_at"]):
            raise ContractError("freeze precedes registration")
        calendar = self._calendar_attachment(review["cards"])
        result = freeze(self.journal, self.run_id, reg["manifest"]["event"], review["cards"], frozen_at=when)
        original = {"state": "ORIGINAL_REPORT", "pipeline_version": VERSION,
                    "registration_hash": digest(reg), "review_hash": digest(review), "frozen": result}
        if calendar is not None:
            original["calendar_context"] = calendar
        return self._save("original", original)

    def evaluate(self, outcome, *, at=None):
        if not self._get("original"):
            raise ContractError("freeze original before outcome")
        manifest = self._registration()["manifest"]
        when = self._time(manifest, at)
        frozen = self._get("original")["frozen"]
        if timestamp(when) < timestamp(frozen["frozen_at"]):
            raise ContractError("evaluation precedes freeze")
        return evaluate(self.journal, self.run_id, outcome, evaluated_at=when)

    def science(self, request, *, at=None):
        """Immutable versioned audit, reusing PR3 computations without altering originals."""
        shape(request, ("report_id", "reason"), ("supersedes", "numeric_outcomes", "analysis_at"))
        text(request["report_id"], "report_id"); text(request["reason"], "reason")
        if "numeric_outcomes" in request and not isinstance(request["numeric_outcomes"], list):
            raise ContractError("numeric_outcomes must be an array")
        if request.get("supersedes") is not None:
            text(request["supersedes"], "supersedes")
        key = "science:" + digest(request["report_id"])
        old = self._get(key)
        if old:
            if digest(old["request"]) != digest(request):
                raise JournalError("scientific report id already used with different inputs")
            if at is not None and old.get("analysis_clock_at") != at:
                raise JournalError("scientific report clock already fixed")
            return old
        original = self._get("original")
        if not original:
            raise ContractError("freeze original first")
        previous = request.get("supersedes")
        if previous is not None and not self._get("science:" + digest(previous)):
            raise ContractError("unknown superseded scientific report")
        reg = self._registration(); manifest = reg["manifest"]; frozen = original["frozen"]
        evaluations = [self.journal.get(f"run:{self.run_id}:outcome:{a['axis_id']}") for a in manifest["event"]["axes"]]
        created_at = now_iso()  # Actual local creation time, separate from an analytical cutoff.
        if at is not None:
            clock_at = self._time(manifest, at)
        elif manifest["provenance"] == "SYNTHETIC":
            # Backward-compatible synthetic fixtures may already contain future declared times.
            boundaries = [created_at, frozen["frozen_at"]] + [r["evaluated_at"] for r in evaluations if r]
            boundaries += [r["recorded_at"] for r in request.get("numeric_outcomes", [])]
            clock_at = max(boundaries, key=timestamp)
        else:
            clock_at = created_at
        analysis_at = request.get("analysis_at", clock_at)
        if not timestamp(frozen["frozen_at"]) <= timestamp(analysis_at) <= timestamp(clock_at):
            raise ContractError("analysis cutoff must follow freeze and not exceed report clock")
        if any(r and timestamp(r["evaluated_at"]) > timestamp(analysis_at) for r in evaluations):
            raise ContractError("included evaluation is after analysis cutoff")
        history = [r["payload"] for r in self.journal.export()
                   if r["record_key"].startswith(self.prefix + ":science:")]
        parent = self._get("science:" + digest(previous)) if previous is not None else None
        if parent and parent["original_report_hash"] != digest(original):
            raise ContractError("scientific parent belongs to a different original/event")
        numeric_history = [r for r in history if r["request"].get("numeric_outcomes")]
        new_outcomes = request.get("numeric_outcomes", [])
        if numeric_history and digest(new_outcomes) != digest(history[-1]["request"].get("numeric_outcomes", [])):
            if not parent or parent != history[-1]:
                raise ContractError("changed/removed numeric outcome requires supersedes of the latest scientific version and a reason")
        if parent and timestamp(parent["analysis_at"]) > timestamp(analysis_at):
            raise ContractError("scientific correction cutoff precedes its parent")
        rows = []
        for axis, result in zip(manifest["event"]["axes"], evaluations):
            rows.append({"axis_id": axis["axis_id"], "deadline": axis["deadline"],
                         "fixed_at": frozen["frozen_at"], "state": "EVALUATED" if result else "AWAITING_OUTCOME",
                         "classification": "PROSPECTIVE_DECLARED" if manifest["event"]["mode"] == "forecast" else "RETROSPECTIVE",
                         "evaluation": result})
        scored = [r["evaluation"] for r in rows if r["evaluation"] and r["evaluation"]["error"] is not None]
        # Axes within an event are not independent event pairs. Never pool them for inference.
        paired = paired_summary([r["baseline_error"] - r["error"] for r in scored], 1) if len(rows) == 1 else None
        numeric = None
        study = manifest.get("numeric_study")
        if "numeric_outcomes" in request and study is None:
            raise ContractError("no numeric method was registered; symbols are not numeric picks")
        if study is not None:
            data = deepcopy(study)
            data["outcomes"] = request.get("numeric_outcomes", [])
            data["analysis_at"] = analysis_at
            for outcome in data["outcomes"]:
                if not evaluations[0] or timestamp(outcome["occurred_at"]) != timestamp(evaluations[0]["outcome"]["observed_at"]):
                    raise ContractError("numeric outcome requires matching registered resolved event/time")
            numeric = statistics_report(data)
        report = {"state": "SCIENTIFIC_REPORT", "science_version": "scientific-audit-v0.3.1", "analysis_at": analysis_at,
                  "created_at": created_at, "analysis_clock_at": clock_at,
                  "analysis_clock_kind": "SYNTHETIC_DECLARED" if manifest["provenance"] == "SYNTHETIC" else "LOCAL_WALL_CLOCK",
                  "event_id": manifest["event"]["event_id"], "run_id": self.run_id,
                  "parent_report_hash": digest(parent) if parent else None,
                  "scope": "one registered event; axes are not independent samples", "request": request, "pipeline_version": VERSION,
                  "original_report_hash": digest(original), "registration_hash": digest(reg),
                  "provenance": manifest["provenance"], "synthetic_clock": reg["synthetic_clock"],
                  "outcome_clock_status": "SYNTHETIC_UNATTESTED" if manifest["provenance"] == "SYNTHETIC" else "LOCAL_UNATTESTED",
                  "statistics_implementation": {"module": "research_stats.core",
                         "source_hash": digest(Path(__file__).parent.parent.joinpath("research_stats/core.py").read_text(encoding="utf-8"))},
                  "source_refs": manifest["source_refs"], "source_verification": "NOT_AUTHENTICATED",
                  "method_versions": {c["core_id"]: {"protocol": c["protocol_version"], "input_hash": c["input_hash"],
                                       "procedure_source": c["raw_result"].get("source") if isinstance(c["raw_result"], dict) else None,
                                       "source_verification": c["raw_result"].get("source_verification", "NOT_AUTHENTICATED") if isinstance(c["raw_result"], dict) else "NOT_AUTHENTICATED",
                                       "sources": {k: c["inputs"][k] for k in ("map_version", "map_hash", "set_id", "profile", "day_boundary", "stroke_standard", "regional_variant", "protocol_ref") if k in c["inputs"]}}
                                      for c in frozen["raw_cards"]},
                  "router": {"core_weight": "0.10", "support_is_probability": False, "comparison": frozen["comparison"]},
                  "trials": rows, "registered_axes": len(rows), "resolved_axes": sum(r is not None for r in evaluations),
                  "scored_axes": len(scored), "categorical_control": "event axis.baseline fixed before adapters",
                  "categorical_paired": paired, "paired_orientation": "control error minus method error; positive favors method",
                  "numeric_external_method": numeric,
                  "lottery-rune-hash-v2": {"status": "UNAVAILABLE", "extension": "explicit versioned numeric_study import; no symbol conversion"},
                  "errors_and_leakage": {"input_validation": "PASSED", "independent_time_attestation": "UNAVAILABLE",
                                         "outcome_source_verification": "UNAVAILABLE", "undetected_leakage": "NOT_EXCLUDED"},
                  "limitations": LIMITATIONS}
        if "calendar_context" in original:
            report["calendar_context"] = deepcopy(original["calendar_context"])
        return self._save(key, report)

    def status(self):
        reg = self._registration()
        original = self._get("original")
        cards = self._cards()
        result = {"run_id": self.run_id, "registration": reg,
                  "cards": cards, "review": self._get("review"), "original": original,
                  "chain": self.journal.verify()}
        calendar = self._calendar_attachment(cards)
        if calendar is not None:
            result["calendar_context"] = calendar
        return result
