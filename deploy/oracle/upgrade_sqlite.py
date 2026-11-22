"""SQLite checkpoint / rollback primitives for AXIOM's existing Oracle x86 VM.

Only stdlib. Deployment script calls backup() while the old service runs for
the migration rehearsal, and again AFTER stopping it for exact rollback.

restore() must only be invoked AFTER ALL AXIOM SQLite writers have stopped.
It atomically replaces the main DB with the pre-upgrade snapshot and clears
stale WAL/SHM sidecars. The caller first archives the failed version's DB.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


def _check(path: str) -> None:
    with sqlite3.connect("file:" + quote(str(Path(path).resolve()), safe="/") + "?mode=ro", uri=True) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError("SQLite integrity_check failed")


def backup(src_path: str, dest_path: str) -> None:
    """Consistent snapshot across WAL changes; never overwrite another backup."""
    src, dest = Path(src_path), Path(dest_path)
    if not src.is_file() or src.is_symlink():
        raise ValueError("Missing or unsafe source SQLite file")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("Refusing to replace existing SQLite backup")
    if not dest.parent.is_dir():
        raise FileNotFoundError("Backup directory must already exist")
    src_uri = "file:" + quote(str(src.resolve()), safe="/") + "?mode=ro"
    source = sqlite3.connect(src_uri, uri=True, timeout=20)
    target = sqlite3.connect(str(dest))
    try:
        with target:
            source.backup(target, pages=1000, sleep=0.1)
        result = target.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError("Snapshot SQLite integrity check failed")
    except Exception:
        target.close()
        source.close()
        dest.unlink(missing_ok=True)
        raise
    finally:
        try:
            target.close()
        except Exception:
            pass
        try:
            source.close()
        except Exception:
            pass
    os.chmod(dest, 0o600)
    _check(str(dest))


def restore(backup_path: str, live_path: str) -> None:
    """Atomic restoration; caller has stopped service and other DB writers."""
    snapshot, live = Path(backup_path), Path(live_path)
    if not snapshot.is_file() or snapshot.is_symlink():
        raise ValueError("Valid pre-upgrade snapshot required")
    if not live.is_file() or live.is_symlink():
        raise ValueError("Existing regular live database required")
    _check(str(snapshot))
    meta = live.stat()
    descriptor, tmpname = tempfile.mkstemp(prefix=".axiom-restore-", dir=str(live.parent))
    tmp = Path(tmpname)
    try:
        with os.fdopen(descriptor, "wb") as out, snapshot.open("rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        if os.geteuid() == 0:
            os.chown(tmp, meta.st_uid, meta.st_gid)
        elif (meta.st_uid, meta.st_gid) != (os.geteuid(), os.getegid()):
            raise PermissionError("Cannot safely preserve live DB ownership")
        os.chmod(tmp, stat.S_IMODE(meta.st_mode))
        os.replace(tmp, live)
        # Only after the service has stopped: these belong to the failed
        # schema/version and cannot be replayed on the restored main file.
        for postfix in ("-wal", "-shm"):
            sidecar = Path(str(live) + postfix)
            if sidecar.is_symlink():
                raise ValueError("Refusing to remove unexpected SQLite sidecar symlink")
            sidecar.unlink(missing_ok=True)
        fd = os.open(live.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)
    _check(str(live))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3 or args[0] not in ("backup", "restore", "verify"):
        print("Usage: upgrade_sqlite.py backup|restore|verify SOURCE DEST", file=sys.stderr)
        return 2
    action, src, dest = args
    if action == "backup":
        backup(src, dest)
    elif action == "restore":
        restore(src, dest)
    else:
        _check(src)
        _check(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
