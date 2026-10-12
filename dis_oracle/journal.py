"""Append-only service journal with a hash chain and idempotent record keys.

The chain detects changed records; it is not independent timestamp attestation
and cannot protect against an administrator rewriting the whole database.
"""

import json
from pathlib import Path
import sqlite3

from .contracts import canonical, digest, now_iso


class JournalError(ValueError):
    pass


class Journal:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                record_key TEXT NOT NULL UNIQUE,
                recorded_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                hash TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON entries
              BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON entries
              BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
        """)

    def close(self):
        self.connection.close()

    def get(self, key):
        row = self.connection.execute("SELECT payload FROM entries WHERE record_key=?", (key,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def append(self, key, payload):
        serialized = canonical(payload)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.verify()
            row = self.connection.execute("SELECT payload,hash FROM entries WHERE record_key=?", (key,)).fetchone()
            if row:
                if row["payload"] != serialized:
                    raise JournalError("record key exists with different content")
                self.connection.commit()
                return row["hash"]
            row = self.connection.execute("SELECT hash FROM entries ORDER BY seq DESC LIMIT 1").fetchone()
            previous = row["hash"] if row else "0" * 64
            recorded = now_iso()
            record_hash = digest({"key": key, "recorded_at": recorded,
                                  "payload": payload, "previous_hash": previous})
            self.connection.execute(
                "INSERT INTO entries(record_key,recorded_at,payload,previous_hash,hash) VALUES (?,?,?,?,?)",
                (key, recorded, serialized, previous, record_hash))
            self.connection.commit()
            return record_hash
        except Exception:
            self.connection.rollback()
            raise

    def verify(self):
        previous, expected_seq = "0" * 64, 1
        for row in self.connection.execute("SELECT * FROM entries ORDER BY seq"):
            calculated = digest({"key": row["record_key"], "recorded_at": row["recorded_at"],
                                 "payload": json.loads(row["payload"]), "previous_hash": previous})
            if row["seq"] != expected_seq or row["previous_hash"] != previous or row["hash"] != calculated:
                raise JournalError("journal chain verification failed")
            previous, expected_seq = row["hash"], expected_seq + 1
        return {"records": expected_seq - 1, "head_hash": previous}

    def export(self):
        self.verify()
        return [dict(row, payload=json.loads(row["payload"]))
                for row in self.connection.execute("SELECT * FROM entries ORDER BY seq")]
