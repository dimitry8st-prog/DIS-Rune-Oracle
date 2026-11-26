"""Read original ZIP members for the local workflow migration."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from stat import S_ISLNK
from zipfile import ZipFile

from research_stats.core import fields, load_json

from .contracts import digest, text, timestamp


MAX_ARCHIVE_BYTES = 128_000_000
MAX_JSON_BYTES = 20_000_000
MAX_INSPECTED_BYTES = 256_000_000
MAX_MEMBERS = 20_000
ARCHIVE_VERSION = "oracle-archive-import-v2"


@dataclass
class ArchiveInput:
    contents: bytes
    archive_hash: str
    outcomes: list = field(default_factory=list)
    forecasts: list = field(default_factory=list)
    cancellations: list = field(default_factory=list)
    summaries: list = field(default_factory=list)
    standalone_runs: list = field(default_factory=list)


def _parts(name):
    if not isinstance(name, str):
        raise ValueError("archive member path must be text")
    segments = name.rstrip("/").split("/")
    if any(segment in ("", ".", "..") for segment in segments) or "\\" in name or ":" in segments[0]:
        raise ValueError(f"invalid archive member path {name!r}")
    return tuple(segments)


def _array(value, name):
    if not isinstance(value, list):
        raise ValueError(f"expected an archive array: {name}")
    return value


def _standalone_run(parts):
    if "standalone_runs" not in parts[:-1]:
        return None
    index = parts.index("standalone_runs")
    return "/".join(parts[:index + 2])


def read_archive(path):
    """Read one bounded ZIP snapshot, preserving exact bytes for provenance."""
    with Path(path).open("rb") as source:
        contents = source.read(MAX_ARCHIVE_BYTES + 1)
    if len(contents) > MAX_ARCHIVE_BYTES:
        raise ValueError(f"archive exceeds {MAX_ARCHIVE_BYTES} bytes")
    result = ArchiveInput(contents, sha256(contents).hexdigest())
    with ZipFile(BytesIO(contents)) as archive:
        _read_members(archive, result)
    return result


def _read_members(archive, result):
    members = archive.infolist()
    paths = {_parts(member.filename): member for member in members}
    if len(paths) != len(members) or len(members) > MAX_MEMBERS:
        raise ValueError("duplicate or excessive ZIP members")
    if any(S_ISLNK(member.external_attr >> 16) for member in members):
        raise ValueError("ZIP symbolic links are unsupported")
    documents = sorted(parts for parts, member in paths.items() if not member.is_dir())
    inspected_size = 0

    def read(parts, *, limit=MAX_JSON_BYTES):
        nonlocal inspected_size
        name = "/".join(parts)
        member = paths.get(parts)
        if member is None or member.is_dir():
            raise ValueError(f"missing archive member: {name}")
        inspected_size += member.file_size
        if member.file_size > limit or inspected_size > MAX_INSPECTED_BYTES:
            raise ValueError(f"archive member exceeds inspection limits: {name}")
        try:
            raw = archive.read(member)
        except RuntimeError as exc:
            raise ValueError(f"cannot read archive member: {name}: {exc}") from exc
        return raw, {"path": name, "sha256": sha256(raw).hexdigest(), "archive_hash": result.archive_hash}

    def read_json(parts):
        raw, source = read(parts)
        try:
            return load_json(raw), source
        except ValueError as exc:
            raise ValueError(f"invalid archive JSON: {source['path']}: {exc}") from exc

    latest = [parts for parts in documents if parts[-1] == "latest-archive-state.json" and "updates" in parts[:-1]]
    if latest:
        roots = {parts[:parts.index("updates") + 1] for parts in latest}
        if len(roots) != 1:
            raise ValueError("ambiguous archive: multiple main history roots")
        updates = roots.pop()
        latest_doc, _ = read_json(max(latest))
        if not isinstance(latest_doc, dict):
            raise ValueError("invalid latest-archive-state.json")
        history, source = read_json(updates + _parts(latest_doc["observations_ref"]))
        result.outcomes = [(row, source) for row in _array(history, source["path"])]
        for ref in _array(latest_doc["summary_refs"], "summary_refs"):
            doc, _ = read_json(updates + _parts(ref))
            result.summaries.append(doc)
        result.cancellations = _array(latest_doc.get("cancelled_forecasts", []), "cancelled_forecasts")

    standalone = defaultdict(lambda: {"files": [], "picks": set(), "identities": set(), "unreadable_json": []})

    def add(doc, source, run, *, record_key=None):
        source = {**source, "original_hash": digest(doc)}
        if record_key is not None:
            source["record_key"] = record_key
        result.forecasts.append((doc, source))
        if run is not None:
            game, draw = _declared_identity(doc)
            if game is not None:
                standalone[run]["picks"].add((game, draw))

    for parts in documents:
        run = _standalone_run(parts)
        if run is not None:
            standalone[run]["files"].append("/".join(parts))
        filename = parts[-1]
        if filename == "cycle-v03.sqlite3" and run is not None:
            from .archive_cycle import cycle_numeric_records, read_cycle_database

            raw, source = read(parts, limit=MAX_ARCHIVE_BYTES)
            wal_path = parts[:-1] + (filename + "-wal",)
            wal = None
            if wal_path in paths:
                wal, wal_source = read(wal_path, limit=MAX_ARCHIVE_BYTES)
                source["wal"] = wal_source
            for record_key, doc in cycle_numeric_records(read_cycle_database(raw, wal)):
                add(doc, source, run, record_key=record_key)
        elif filename == "numeric-selection.json" or (run is not None and filename.lower().endswith(".json")):
            try:
                doc, source = read_json(parts)
            except ValueError as exc:
                if filename == "numeric-selection.json":
                    raise
                standalone[run]["unreadable_json"].append({"path": "/".join(parts), "reason": str(exc)})
                continue
            if filename == "numeric-selection.json" or _is_fixed_pick(doc):
                add(doc, source, run)
            elif _is_journal_export(doc):
                from .archive_cycle import cycle_numeric_records

                for record_key, payload in cycle_numeric_records(doc):
                    add(payload, source, run, record_key=record_key)
            elif isinstance(doc, dict):
                game, draw = _declared_identity(doc)
                if game is not None:
                    standalone[run]["identities"].add((game, draw))

    for path, run in standalone.items():
        picks = run["picks"]
        identities = run["identities"] | picks
        result.standalone_runs.append({"path": path, "files": run["files"],
                                      "identities": [{"game": g, "draw": d} for g, d in sorted(identities)],
                                      "unreadable_json": run["unreadable_json"],
                                      "numeric_picks": len(picks),
                                      "state": "CANONICAL_NUMERIC_PICK" if picks else "NO_CANONICAL_NUMERIC_PICK"})
    if not latest and not standalone and not result.forecasts:
        raise ValueError("no supported Oracle archive history or standalone_runs")


def _declared_identity(doc):
    if isinstance(doc, dict) and isinstance(doc.get("game"), str) and type(doc.get("draw")) is int:
        return doc["game"], doc["draw"]
    return None, None


def _is_fixed_pick(doc):
    return isinstance(doc, dict) and (
        doc.get("state") == "LOTTERY_NUMERIC_FIXED"
        or {"game", "draw", "fields", "fixed_at", "random_control"} <= doc.keys()
    )


def _is_journal_export(doc):
    return isinstance(doc, list) and bool(doc) and isinstance(doc[0], dict) and "record_key" in doc[0]


def _recorded_method(values, metadata=None):
    result = {"state": "ABSTAIN" if values is None else "PICK", "fields": None}
    if values is not None:
        fields(values)
        result["fields"] = [sorted(part) for part in values]
    if metadata is not None:
        rules = [metadata[key] for key in ("tie_break", "tie_break_rule", "tie_breaker") if metadata.get(key) is not None]
        if rules:
            if any(rule != rules[0] for rule in rules[1:]):
                raise ValueError("conflicting tie-break rules in archive method")
            if not isinstance(rules[0], (str, dict)) or not rules[0]:
                raise ValueError("archive tie-break rule must be nonempty text or an object")
            if isinstance(rules[0], str):
                text(rules[0], "tie_break")
            result["tie_break"] = rules[0]
        if metadata.get("method_version") is not None:
            text(metadata["method_version"], "method_version")
            result["method_version"] = metadata["method_version"]
    return result


def forecast_record(record, source):
    """Project fixed numeric fields from one known original, without rerunning it."""
    if not isinstance(record, dict):
        raise ValueError(f"expected archive forecast object: {source['path']}")
    cycle = record.get("state") == "LOTTERY_NUMERIC_FIXED"
    method = record.get("method_version", "lottery-rune-hash-v2")
    text(method, "method_version")
    if method == "random":
        raise ValueError("archive forecast method conflicts with the random control")
    values = record["method_fields" if cycle else "fields"]
    if values is None:
        raise ValueError("archive forecast requires original numeric fields")
    methods = {method: _recorded_method(values, record)}
    control = record.get("control_fields" if cycle else "random_control")
    if control is not None:
        methods["random"] = _recorded_method(control)
        if record.get("control_id") is not None:
            text(record["control_id"], "control_id")
            methods["random"]["method_version"] = record["control_id"]
    for limit in (20, 30, 100):
        arm = record.get(f"frequency{limit}_v1")
        if arm is None:
            continue
        if not isinstance(arm, dict):
            raise ValueError(f"invalid archive frequency{limit} arm")
        method_id = arm.get("method_id", f"frequency{limit}-v1")
        text(method_id, "frequency method_id")
        if method_id in methods or not method_id.startswith("frequency"):
            raise ValueError(f"conflicting archive frequency method: {method_id}")
        if arm.get("fields") is not None or arm.get("state") == "ABSTAIN":
            methods[method_id] = _recorded_method(arm.get("fields"), arm)
    target = record.get("target_at_declared", record.get("target_at", record.get("target_at_assumed")))
    if target is not None:
        timestamp(target)
    timestamp(record["fixed_at"])
    return {"game": record["game"], "draw": record["draw"], "target_at": target,
            "legacy_time_classification": record.get("timing_classification"),
            "target_time_assumed": "target_at_declared" not in record and "target_at" not in record and "target_at_assumed" in record,
            "fixed_at": record["fixed_at"], "origin": "LEGACY_UNATTESTED", "methods": methods,
            "source_path": source["path"], "original_hash": source["original_hash"],
            "archive_sources": [source], "study_id": None}


def join_forecasts(previous, new, key):
    """Attach related originals while preserving already recorded picks and clocks."""
    if previous["origin"] != "LEGACY_UNATTESTED":
        raise ValueError(f"archive forecast conflicts with an existing ledger forecast: {key}")
    joined = deepcopy(previous)
    for name in ("fixed_at", "target_at"):
        old_value, value = previous.get(name), new.get(name)
        if old_value is not None and value is not None and timestamp(old_value) != timestamp(value):
            raise ValueError(f"archive forecast conflict {key}: {name}")
        if old_value is None and value is not None:
            joined[name] = value
            if name == "target_at":
                joined["target_time_assumed"] = new["target_time_assumed"]
    if not previous.get("archive_sources") and previous.get("original_hash") == new["original_hash"]:
        # v1 assigned fixed method labels before retaining the original metadata.
        joined["methods"] = new["methods"]
        joined["archive_sources"] = new["archive_sources"]
        return joined
    if not previous["methods"].keys() & new["methods"].keys():
        raise ValueError(f"archive forecast conflict {key}: no matching recorded method")
    for method, arm in new["methods"].items():
        if method in previous["methods"]:
            old_arm = previous["methods"][method]
            if any(old_arm.get(name) != arm.get(name) for name in ("state", "fields")):
                raise ValueError(f"archive forecast conflict {key}: {method}")
            for name in ("tie_break", "method_version"):
                if name in old_arm and name in arm and old_arm[name] != arm[name]:
                    raise ValueError(f"archive forecast conflict {key}: {method} {name}")
            joined["methods"][method].update(arm)
        else:
            joined["methods"][method] = arm
    sources = joined.setdefault("archive_sources", [])
    for source in new["archive_sources"]:
        if source not in sources:
            sources.append(source)
    return joined
