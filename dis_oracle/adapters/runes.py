"""Closed rune selection with a v2.1 manifest and explicit post-reading reveal."""

import hashlib
import json
from pathlib import Path
import secrets
import sqlite3

from ..contracts import ContractError, canonical, digest, now_iso, text


def catalog():
    return json.loads(Path(__file__).with_name("rune_map.json").read_text(encoding="utf-8"))


def manifest_hash(manifest):
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def read_rune(row, rotation, meanings):
    rune = next(r for r in meanings["runes"] if r["rune_id"] == row["rune_id"])
    final = None if rune["index"] == 0 else (row["base_orientation"] + rotation) % 360
    reversed_reading = final == 180 and rune["reversed"] is not None
    return {"slot": row["slot"], "rune_id": row["rune_id"], "name": rune["name"],
            "symbol": rune["symbol"], "base_orientation": row["base_orientation"],
            "user_rotation": rotation, "final_orientation": final,
            "reversed_reading": reversed_reading,
            "meaning": rune["reversed"] if reversed_reading else rune["upright"]}


class RuneSessions:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # Private mutable session state is separate from the exportable journal.
            with path.open("xb"):
                pass
            path.chmod(0o600)
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
          CREATE TABLE IF NOT EXISTS rune_sessions (
            session_id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
            created_at TEXT NOT NULL, manifest TEXT NOT NULL, commitment TEXT NOT NULL,
            catalog TEXT NOT NULL, choices TEXT NOT NULL, card TEXT
          );
          CREATE TRIGGER IF NOT EXISTS rune_manifest_immutable BEFORE UPDATE OF
            session_id, manifest, commitment, catalog, event_id, created_at ON rune_sessions
            BEGIN SELECT RAISE(ABORT, 'rune manifest is immutable'); END;
          CREATE TRIGGER IF NOT EXISTS rune_card_immutable BEFORE UPDATE ON rune_sessions
            WHEN OLD.card IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'completed rune reading is immutable'); END;
          CREATE TRIGGER IF NOT EXISTS rune_choices_append_only BEFORE UPDATE OF choices ON rune_sessions
            WHEN json_array_length(NEW.choices) != json_array_length(OLD.choices) + 1
            BEGIN SELECT RAISE(ABORT, 'choices must append one selection'); END;
          CREATE TRIGGER IF NOT EXISTS rune_session_no_delete BEFORE DELETE ON rune_sessions
            BEGIN SELECT RAISE(ABORT, 'rune session cannot be deleted through this store'); END;
        """)

    def close(self):
        self.connection.close()

    def _load(self, session_id):
        row = self.connection.execute("SELECT * FROM rune_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise ContractError("unknown rune session")
        if manifest_hash(row["manifest"]) != row["commitment"]:
            raise ContractError("rune commitment mismatch; stop the session")
        return row

    @staticmethod
    def _public(row):
        choices = json.loads(row["choices"])
        return {"session_id": row["session_id"], "event_id": row["event_id"],
                "created_at": row["created_at"], "commitment": row["commitment"],
                "closed_slots": list(range(1, 26)) if len(choices) < 3 else [],
                "choices": choices, "state": "READING_FIXED" if row["card"] else "SELECTING",
                "card": json.loads(row["card"]) if row["card"] else None}

    def prepare(self, session_id, event_id):
        text(session_id, "session_id"); text(event_id, "event_id")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute("SELECT event_id FROM rune_sessions WHERE session_id=?", (session_id,)).fetchone()
            if existing:
                if existing["event_id"] != event_id:
                    raise ContractError("session is bound to another event")
            else:
                meanings = catalog()
                rng = secrets.SystemRandom()
                runes = list(meanings["runes"]); rng.shuffle(runes)
                nonce = secrets.token_hex(16)
                manifest = "version=2.1\nnonce=" + nonce
                for slot, rune in enumerate(runes, 1):
                    orientation = "NA" if rune["index"] == 0 else str(rng.choice((0, 180)))
                    manifest += f"\n{slot:02d}|{rune['rune_id']}|{orientation}"
                self.connection.execute("INSERT INTO rune_sessions VALUES (?,?,?,?,?,?,?,?)",
                    (session_id, event_id, now_iso(), manifest, manifest_hash(manifest), canonical(meanings), "[]", None))
            result = self._public(self._load(session_id))
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback(); raise

    def status(self, session_id):
        return self._public(self._load(session_id))

    def select(self, session_id, slot, rotation):
        if type(slot) is not int or not 1 <= slot <= 25 or type(rotation) is not int or rotation not in (0, 180):
            raise ContractError("slot must be 1..25 and rotation 0 or 180")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self._load(session_id)
            choices = json.loads(row["choices"])
            if row["card"] or any(c["slot"] == slot for c in choices):
                raise ContractError("completed session or repeated slot; state unchanged")
            choices.append({"slot": slot, "rotation": rotation})
            card = None
            if len(choices) == 3:
                table = {}
                for line in row["manifest"].splitlines()[2:]:
                    number, rune_id, base = line.split("|")
                    table[int(number)] = {"slot": int(number), "rune_id": rune_id,
                                          "base_orientation": None if base == "NA" else int(base)}
                meanings = json.loads(row["catalog"])
                readings = [read_rune(table[c["slot"]], c["rotation"], meanings) for c in choices]
                inputs = {"event_id": row["event_id"], "session_id": session_id,
                          "commitment": row["commitment"], "choices": choices,
                          "map_version": meanings["version"], "map_hash": digest(meanings)}
                interpretation = " → ".join(f"{i}: {r['name']}: {r['meaning']}" for i, r in zip(("I", "II", "III"), readings))
                card = {"core_id": "rune", "status": "OK", "reason": "",
                        "protocol_version": "rune-closed-v2.1", "inputs": inputs, "input_hash": digest(inputs),
                        "raw_result": {"generated_at": row["created_at"], "reading_fixed_at": now_iso(),
                                       "positions": readings, "commitment": row["commitment"],
                                       "manifest_reveal": "explicit rune-reveal command after reading"},
                        "interpretation": interpretation, "claims": []}
            self.connection.execute("UPDATE rune_sessions SET choices=?,card=? WHERE session_id=?",
                                    (canonical(choices), canonical(card) if card else None, session_id))
            result = self._public(self._load(session_id)); self.connection.commit()
            return result
        except Exception:
            self.connection.rollback(); raise

    def reveal(self, session_id):
        row = self._load(session_id)
        if not row["card"]:
            raise ContractError("finish all three choices and fix the reading before revealing the manifest")
        return {"session_id": session_id, "commitment": row["commitment"],
                "manifest": row["manifest"], "verified": manifest_hash(row["manifest"]) == row["commitment"]}
