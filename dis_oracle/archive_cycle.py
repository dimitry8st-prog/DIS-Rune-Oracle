"""Read preserved v0.3 cycle journals from a ZIP without running their code."""

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from research_stats.core import fields, load_json

from .contracts import digest, shape, text, timestamp


LOTTERY_METHOD = "lottery-rune-hash-v2"
LOTTERY_SUFFIX = ":" + LOTTERY_METHOD


def read_cycle_database(database_bytes, wal_bytes=None):
    """Read a private temporary copy, including a committed SQLite WAL if present."""
    with TemporaryDirectory(prefix="dis-oracle-import-") as directory:
        path = Path(directory) / "cycle-v03.sqlite3"
        path.write_bytes(database_bytes)
        if wal_bytes is not None:
            path.with_name(path.name + "-wal").write_bytes(wal_bytes)
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA trusted_schema=OFF")
            table = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE name = 'entries' AND type = 'table'"
            ).fetchone()
            if table is None:
                raise ValueError("cycle SQLite archive does not contain the entries table")
            if [row[0] for row in connection.execute("PRAGMA quick_check")] != ["ok"]:
                raise ValueError("cycle SQLite archive failed integrity check")
            columns = "seq, record_key, recorded_at, payload, previous_hash, hash"
            return [
                dict(row, payload=load_json(row["payload"]))
                for row in connection.execute(f"SELECT {columns} FROM entries ORDER BY seq")
            ]
        finally:
            connection.close()


def cycle_numeric_records(entries):
    """Check a Journal.export chain and recover explicit lottery-plan selections."""
    if not isinstance(entries, list):
        raise ValueError("cycle journal export must be an array")
    previous_hash = "0" * 64
    records = {}
    for seq, row in enumerate(entries, 1):
        shape(row, ("seq", "record_key", "recorded_at", "payload", "previous_hash", "hash"))
        key = row["record_key"]
        text(key, "record_key")
        timestamp(row["recorded_at"])
        if not isinstance(row["payload"], dict):
            raise ValueError("cycle journal payload must be an object")
        expected_hash = digest({
            "key": key, "recorded_at": row["recorded_at"], "payload": row["payload"],
            "previous_hash": previous_hash,
        })
        if (type(row["seq"]) is not int or row["seq"] != seq or row["previous_hash"] != previous_hash
                or row["hash"] != expected_hash or key in records):
            raise ValueError("cycle journal chain verification failed")
        previous_hash = expected_hash
        records[key] = row["payload"]

    selections = []
    for key, record in records.items():
        if not key.endswith(LOTTERY_SUFFIX):
            continue
        if not key.startswith("cycle:") or record.get("state") != "LOTTERY_NUMERIC_FIXED":
            raise ValueError(f"invalid saved lottery selection {key}")
        prefix = key.removesuffix(LOTTERY_SUFFIX)
        registration = records.get(prefix + ":registered", {})
        manifest = registration.get("manifest")
        plan = manifest.get("lottery_plan") if isinstance(manifest, dict) else None
        bound_fields = ("game", "draw", "target_at", "method_version", "control_rule")
        if (not isinstance(plan, dict)
                or any(field not in plan or record.get(field) != plan[field] for field in bound_fields)
                or record.get("method_version") != LOTTERY_METHOD
                or record.get("registered_at") != registration.get("registered_at")):
            raise ValueError(f"saved lottery selection does not match its registered plan: {key}")
        text(record["game"], "lottery game")
        if type(record["draw"]) is not int or record["draw"] < 1:
            raise ValueError(f"invalid saved lottery draw: {key}")
        timestamp(record["registered_at"])
        timestamp(record["fixed_at"])
        if record["target_at"] is not None:
            timestamp(record["target_at"])
        fields(record["method_fields"])
        fields(record["control_fields"])
        selections.append((key, record))
    return selections
