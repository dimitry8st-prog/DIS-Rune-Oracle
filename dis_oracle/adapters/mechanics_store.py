"""Dedicated append-only session database; does not migrate engine journals.

Each idempotent command and its full card snapshot are committed atomically.
BEGIN IMMEDIATE serializes concurrent writers before any random draw.
The hash chain detects corruption, not an administrator rewriting the database.
"""

import json
from pathlib import Path
import sqlite3

from ..contracts import ContractError, canonical, digest, now_iso, text, validate_cards
from ..journal import JournalError


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractError(f"{name} must be an integer in {low}..{high}; bool is not an integer input")


def mode_check(mode, source):
    if mode == "historical":
        raise ContractError(f"BLOCKED_SOURCE: {source}; historical mode is unavailable")
    if mode not in ("manual", "digital"):
        raise ContractError("mode must explicitly be manual or digital")


def make_card(core, inputs, raw):
    state = raw["final_state"]
    raw.update(procedure_status="PENDING" if state == "pending" else "OK",
               interpretation_status="ABSTAIN", text_corpus="UNAVAILABLE")
    reason = ("PROCEDURE_PENDING" if state == "pending" else
              "CONFIRMATION_NOT_RECEIVED" if state == "no_confirmation" else "TEXT_CORPUS_NOT_FIXED")
    card = {"core_id": core, "status": "ABSTAIN", "reason": reason,
            "protocol_version": f"{core}-numeric-mechanics-v1",
            "inputs": inputs, "input_hash": digest(inputs), "raw_result": raw,
            "interpretation": "Numeric mechanics only; no source-verified interpretation or forecast assigned.",
            "claims": []}
    validate_cards([card], {})
    return card


class SessionStore:
    core_id = None

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb"):
                pass
            path.chmod(0o600)
            created = True
        except FileExistsError:
            created = False
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        try:
            if not created:
                table = self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='mechanical_steps'").fetchone()
                if not table:
                    raise JournalError("use a new mechanics database; existing unrelated files/journals are not migrated")
            else:
                self.connection.executescript("""
                    CREATE TABLE mechanical_steps (
                        core_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        step INTEGER NOT NULL,
                        request_id TEXT NOT NULL,
                        request TEXT NOT NULL,
                        card TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        hash TEXT NOT NULL,
                        PRIMARY KEY(core_id, session_id, request_id),
                        UNIQUE(core_id, session_id, step)
                    );
                    CREATE TRIGGER mechanical_no_update BEFORE UPDATE ON mechanical_steps
                      BEGIN SELECT RAISE(ABORT, 'mechanics records are append-only'); END;
                    CREATE TRIGGER mechanical_no_delete BEFORE DELETE ON mechanical_steps
                      BEGIN SELECT RAISE(ABORT, 'mechanics records are append-only'); END;
                """)
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _history(self, session_id, event_id):
        rows = self.connection.execute(
            "SELECT * FROM mechanical_steps WHERE core_id=? AND session_id=? ORDER BY step",
            (self.core_id, session_id)).fetchall()
        previous = "0" * 64
        for step, row in enumerate(rows):
            record = {key: row[key] for key in row.keys() if key != "hash"}
            if row["step"] != step or row["previous_hash"] != previous or digest(record) != row["hash"]:
                raise JournalError("mechanical session hash chain verification failed")
            if row["event_id"] != event_id:
                raise ContractError("session_id is already bound to a different event_id")
            validate_cards([json.loads(row["card"])], {})
            previous = row["hash"]
        return rows

    def _execute(self, session_id, event_id, request_id, request, build):
        text(session_id, "session_id"); text(event_id, "event_id"); text(request_id, "request_id")
        serialized = canonical(request)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            rows = self._history(session_id, event_id)
            old = next((row for row in rows if row["request_id"] == request_id), None)
            if old:
                if old["request"] != serialized:
                    raise ContractError("request inputs changed; recorded session/command cannot be replaced")
                card = json.loads(old["card"])
            else:
                latest = json.loads(rows[-1]["card"]) if rows else None
                card = build(latest)
                validate_cards([card], {})
                record = {"core_id": self.core_id, "session_id": session_id, "event_id": event_id,
                          "step": len(rows), "request_id": request_id, "request": serialized,
                          "card": canonical(card), "recorded_at": now_iso(),
                          "previous_hash": rows[-1]["hash"] if rows else "0" * 64}
                record["hash"] = digest(record)
                self.connection.execute(
                    "INSERT INTO mechanical_steps VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(record.values()))
            self.connection.commit()
            return card
        except Exception:
            self.connection.rollback()
            raise

    def status(self, session_id, event_id):
        text(session_id, "session_id"); text(event_id, "event_id")
        rows = self._history(session_id, event_id)
        if not rows:
            raise ContractError("unknown mechanical session")
        return json.loads(rows[-1]["card"])

    @staticmethod
    def _continuation_id(request_id):
        text(request_id, "request_id")
        if request_id == "start":
            raise ContractError("request_id 'start' is reserved for session creation")
