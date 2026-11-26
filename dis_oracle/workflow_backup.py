"""Verified local workflow snapshots and non-overwriting restoration."""
from contextlib import ExitStack, closing, contextmanager, suppress
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile

from research_stats.core import load_json
from .adapters.runes import manifest_hash
from .contracts import canonical, digest, validate_cards
from .journal import Journal


MANIFEST = "backup-manifest.json"
VERSION = "oracle-workflow-backup-v1"
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def safe_path(path):
    path = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"symbolic links are unsupported: {path}")
    return path


def _inventory(root):
    safe_path(root)
    if not root.is_dir():
        raise ValueError(f"expected a directory: {root}")
    directories, files = [], []
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            directories.append(path)
        elif stat.S_ISREG(mode):
            files.append(path)
        else:
            raise ValueError(f"unsupported file or symbolic link in workflow backup: {path}")
    return directories, files


def _read_database(path, *, snapshot=False):
    safe_path(path)
    suffix = "?mode=ro&immutable=1" if snapshot else "?mode=ro"
    connection = sqlite3.connect(path.as_uri() + suffix, uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    return closing(connection)


def _sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_sqlite(source, target):
    if not source.is_file():
        raise ValueError(f"SQLite source is missing: {source}")
    for suffix in SIDECAR_SUFFIXES:
        safe_path(str(source) + suffix)
    with _read_database(source) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    target.chmod(0o600)
    _sync(target)


@contextmanager
def _hold_workflow(source, verify_workflow):
    if not source.is_file():
        raise ValueError("backup source database does not exist")
    for suffix in SIDECAR_SUFFIXES:
        safe_path(str(source) + suffix)
    uri = source.as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, isolation_level=None, timeout=30)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        try:
            verify_workflow(db)
            yield
        finally:
            db.rollback()


def _copy_bytes(source, target):
    safe_path(source)
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as src, target.open("xb") as dst:
        before = os.fstat(src.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"expected a regular file: {source}")
        shutil.copyfileobj(src, dst)
        after = os.fstat(src.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError(f"file changed during copy: {source}")
    target.chmod(0o600)
    _sync(target)


def _is_sqlite(path):
    if path.suffix.lower() in SQLITE_SUFFIXES:
        return True
    with path.open("rb") as source:
        return source.read(16) == b"SQLite format 3\x00"


@contextmanager
def _hold_cycles(roots):
    with ExitStack() as stack:
        locks = [p for root in roots if root.exists() for p in _inventory(root)[1]
                 if p.name == "cycle.lock"]
        if locks:
            import fcntl
            for lock in sorted(locks):
                stream = stack.enter_context(lock.open("rb"))
                fcntl.flock(stream, fcntl.LOCK_EX)
        yield set(locks)


def _snapshot_tree(source, target, locks):
    directories, files = _inventory(source)
    for directory in (source, *directories):
        (target / directory.relative_to(source)).mkdir(mode=0o700)
    sqlite_sources = {path for path in files if _is_sqlite(path)}
    sqlite_sidecars = {Path(str(path) + suffix) for path in sqlite_sources for suffix in SIDECAR_SUFFIXES}
    for path in files:
        if path.name == "cycle.lock":
            if path not in locks:
                raise ValueError(f"cycle appeared during backup: {path}")
            continue
        if path in sqlite_sidecars:
            continue
        copied = target / path.relative_to(source)
        if path in sqlite_sources:
            _copy_sqlite(path, copied)
        else:
            _copy_bytes(path, copied)


def _private_runes(db):
    for row in db.execute("SELECT * FROM rune_sessions"):
        choices = json.loads(row["choices"])
        count = len(choices)
        if (manifest_hash(row["manifest"]) != row["commitment"]
                or count > 3 or len({c["slot"] for c in choices}) != count
                or bool(row["card"]) != (count == 3)):
            raise ValueError("invalid rune session commitment or choices")
        if row["card"]:
            catalog, card = json.loads(row["catalog"]), json.loads(row["card"])
            validate_cards([card], {})
            expected = {"event_id": row["event_id"], "session_id": row["session_id"],
                        "commitment": row["commitment"], "choices": choices,
                        "map_version": catalog["version"], "map_hash": digest(catalog)}
            if card["inputs"] != expected or card["core_id"] != "rune":
                raise ValueError("rune reading is not bound to its private session")


def _private_mechanics(db):
    histories = {}
    for row in db.execute("SELECT * FROM mechanical_steps ORDER BY core_id, session_id, step"):
        key = row["core_id"], row["session_id"]
        step, previous, event_id = histories.get(key, (0, "0" * 64, row["event_id"]))
        body = dict(row)
        current_hash = body.pop("hash")
        if (row["step"], row["previous_hash"], row["event_id"], digest(body)) != (
                step, previous, event_id, current_hash):
            raise ValueError("mechanical session hash chain verification failed")
        validate_cards([json.loads(row["card"])], {})
        histories[key] = step + 1, current_hash, event_id


def _verify_database(db):
    if [row[0] for row in db.execute("PRAGMA integrity_check")] != ["ok"]:
        raise ValueError("SQLite integrity check failed")
    return {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def _verify_cycle_reference(db, forecast, symbolic):
    run = symbolic["cycle_run_id"]
    reference = symbolic["cycle_chain"]
    row = db.execute("SELECT payload, seq FROM entries WHERE record_key=?",
                     ("cycle:" + digest(run) + ":original",)).fetchone()
    prefix = db.execute("SELECT hash FROM entries WHERE seq=?", (reference["records"],)).fetchone()
    if row is None or prefix is None or prefix["hash"] != reference["head_hash"] or row["seq"] > reference["records"]:
        raise ValueError(f"missing or mismatched symbolic cycle reference: {run}")
    original = json.loads(row["payload"])
    expected_event = f'{forecast["game"]}-{forecast["draw"]}'
    frozen = original["frozen"]
    if (digest(original) != symbolic["original_report_hash"] or frozen["run_id"] != run
            or frozen["event"]["event_id"] != expected_event
            or frozen["event"]["axes"][0]["deadline"] != forecast["target_at"]):
        raise ValueError(f"original symbolic report does not match workflow forecast: {run}")


def _verify_private_files(db, root):
    rows = db.execute("SELECT record_key,payload FROM entries WHERE record_key LIKE 'cycle:%:collected'")
    for row in rows:
        run_hash = row["record_key"].split(":")[1]
        if len(run_hash) != 64 or any(c not in "0123456789abcdef" for c in run_hash):
            raise ValueError("invalid cycle run key")
        for card in json.loads(row["payload"])["cards"]:
            core = card["core_id"]
            if core not in ("rune", "mo", "qiuqian"):
                continue
            path = root / "private" / run_hash / (core + ".sqlite3")
            if not path.is_file():
                raise ValueError(f"missing private {core} state for symbolic cycle: {run_hash}")
            session = card["inputs"]["session_id"]
            event = card["inputs"]["event_id"]
            with _read_database(path, snapshot=True) as private:
                if core == "rune":
                    snapshots = private.execute("SELECT card FROM rune_sessions WHERE session_id=? AND event_id=?",
                                                (session, event))
                else:
                    snapshots = private.execute("SELECT card FROM mechanical_steps WHERE core_id=? AND session_id=? AND event_id=?",
                                                (core, session, event))
                if not any(item[0] and json.loads(item[0]) == card for item in snapshots):
                    raise ValueError(f"private {core} session does not match the collected symbolic card: {run_hash}")


def _file_metadata(path):
    with path.open("rb") as stream:
        return {"sha256": hashlib.file_digest(stream, "sha256").hexdigest(), "size": path.stat().st_size}


def _inspect_bundle(root, database, verify_workflow):
    if database != Path(database).name or database in ("", ".", "..", MANIFEST, "standalone_runs"):
        raise ValueError("backup database name must be a single safe filename")
    directories, paths = _inventory(root)
    allowed = {database, database + ".cycles", "standalone_runs", MANIFEST}
    if any(path.relative_to(root).parts[0] not in allowed for path in (*directories, *paths)):
        raise ValueError("unexpected file in workflow backup")
    if any((root / name) in paths for name in (database + ".cycles", "standalone_runs")):
        raise ValueError("symbolic backup roots must be directories")
    main = root / database
    if main not in paths:
        raise ValueError("missing workflow SQLite in backup")
    cycle = root / (database + ".cycles") / "cycle-v03.sqlite3"
    files, journal_chains = {}, {}
    with _read_database(main, snapshot=True) as db:
        _verify_database(db)
        workflow_chain = verify_workflow(db)
        forecasts = [json.loads(row[0]) for row in db.execute("SELECT payload FROM workflow_events WHERE kind='forecast'")]
    references = [(forecast, symbolic) for forecast in forecasts
                  if (symbolic := forecast["methods"].get("lottery-rune-hash-v2", {})).get("cycle_run_id") is not None]
    if references and cycle not in paths:
        raise ValueError("workflow forecasts reference a missing symbolic SQLite journal")
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST:
            continue
        files[relative] = _file_metadata(path)
        if path == main or not _is_sqlite(path):
            continue
        with _read_database(path, snapshot=True) as db:
            tables = _verify_database(db)
            if path == cycle and "entries" not in tables:
                raise ValueError("cycle SQLite journal has no entries table")
            if "entries" in tables:
                journal_chains[relative] = Journal.verify_connection(db)
                if path == cycle:
                    _verify_private_files(db, path.parent)
            if path == cycle:
                for forecast, symbolic in references:
                    _verify_cycle_reference(db, forecast, symbolic)
            if "rune_sessions" in tables:
                _private_runes(db)
            if "mechanical_steps" in tables:
                _private_mechanics(db)
    return {"schema_version": VERSION, "database": database,
            "directories": [path.relative_to(root).as_posix() for path in directories],
            "files": files, "workflow_chain": workflow_chain, "journal_chains": journal_chains}


def _destination(path, *, empty_ok=False):
    dest = safe_path(path)
    if dest.exists() and not (empty_ok and dest.is_dir() and not any(dest.iterdir())):
        raise ValueError(f"destination must be new{' or empty' if empty_ok else ''}: {dest}")
    return dest


def _publish_directory(stage, destination, *, empty_ok=False):
    directories, _files = _inventory(stage)
    for directory in (*reversed(directories), stage):
        _sync(directory)
    reserved = False
    try:
        if not empty_ok or not destination.exists():
            destination.mkdir(mode=0o700)
            reserved = True
        stage.rename(destination)
    except BaseException:
        if reserved:
            with suppress(OSError):
                destination.rmdir()
        raise
    _sync(destination.parent)


def _snapshot_directory(destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=".workflow-snapshot-", dir=destination.parent)


def _summary(state, scope, directory, manifest):
    return {"state": state, "scope": scope, "database": str(directory / manifest["database"]),
            "manifest_hash": digest(manifest), "workflow_chain": manifest["workflow_chain"],
            "journal_chains": manifest["journal_chains"], "file_count": len(manifest["files"])}


def backup(source, destination, verify_workflow, *, bundle=False):
    source = safe_path(source)
    destination = _destination(destination)
    full = bundle or destination.suffix.lower() not in SQLITE_SUFFIXES
    roots = [safe_path(str(source) + ".cycles"), safe_path(source.parent / "standalone_runs")] if full else []
    if any(destination.is_relative_to(root) for root in roots):
        raise ValueError("backup destination must be outside the workflow's symbolic data")
    with _snapshot_directory(destination) as temporary:
        stage = Path(temporary) / "payload"
        stage.mkdir(mode=0o700)
        main = stage / source.name
        with _hold_workflow(source, verify_workflow):
            if full:
                with _hold_cycles(roots) as locks:
                    _copy_sqlite(source, main)
                    for root in roots:
                        if root.exists():
                            _snapshot_tree(root, stage / root.name, locks)
            else:
                _copy_sqlite(source, main)
        if not full:
            with _read_database(main, snapshot=True) as db:
                _verify_database(db)
                result = verify_workflow(db)
            os.link(main, destination)
            _sync(destination.parent)
            return result
        manifest = _inspect_bundle(stage, source.name, verify_workflow)
        (stage / MANIFEST).write_text(canonical(manifest) + "\n", encoding="utf-8")
        (stage / MANIFEST).chmod(0o600)
        _sync(stage / MANIFEST)
        _publish_directory(stage, destination)
    return _summary("BACKED_UP", "COMPLETE", destination, manifest)


def restore(source, destination, verify_workflow):
    source = safe_path(source)
    destination = _destination(destination, empty_ok=True)
    if destination.is_relative_to(source):
        raise ValueError("restore destination must be outside the backup source")
    with _snapshot_directory(destination) as temporary:
        stage = Path(temporary) / "payload"
        stage.mkdir(mode=0o700)
        if source.is_file():
            main = stage / source.name
            _copy_sqlite(source, main)
            with _read_database(main, snapshot=True) as db:
                _verify_database(db)
                chain = verify_workflow(db)
            result = {"state": "RESTORED", "scope": "DATABASE_ONLY", "database": str(destination / source.name),
                      "workflow_chain": chain, "journal_chains": {}}
        else:
            directories, files = _inventory(source)
            for directory in directories:
                (stage / directory.relative_to(source)).mkdir(mode=0o700)
            for path in files:
                _copy_bytes(path, stage / path.relative_to(source))
            manifest = load_json((stage / MANIFEST).read_text(encoding="utf-8"))
            actual = _inspect_bundle(stage, manifest["database"], verify_workflow)
            if manifest != actual:
                raise ValueError("backup manifest, file digests or journal chains do not match")
            (stage / MANIFEST).unlink()
            result = _summary("RESTORED", "COMPLETE", destination, manifest)
        _publish_directory(stage, destination, empty_ok=True)
    return result
