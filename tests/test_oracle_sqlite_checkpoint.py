"""End-to-end SQLite backup/restore checks using actual WAL and schema changes.

These tests exercise the *same helper* the Oracle in-place upgrade runs,
rather than merely asserting that a shell script contains backup-related text.
"""
import os
import sqlite3
import stat

import pytest

from deploy.oracle import upgrade_sqlite as dbupgrade


def create(path):
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE observations(id INTEGER PRIMARY KEY, btc REAL)")
        db.execute("CREATE TABLE paper_trades(id INTEGER PRIMARY KEY, pnl REAL)")
        db.executemany("INSERT INTO observations(btc) VALUES(?)", [(63000,), (63020,)])
        db.execute("INSERT INTO paper_trades(pnl) VALUES(12.5)")
    return path


def facts(path):
    with sqlite3.connect(path) as db:
        return (
            db.execute("PRAGMA integrity_check").fetchone()[0],
            db.execute("SELECT btc FROM observations ORDER BY id").fetchall(),
            db.execute("SELECT pnl FROM paper_trades").fetchall(),
            db.execute("PRAGMA table_info(observations)").fetchall(),
        )


def test_real_wal_database_backup_and_migration_rollback(tmp_path):
    live=create(tmp_path/"bot.sqlite3")
    before=facts(live)
    backup=tmp_path/"pre-upgrade.sqlite3"
    dbupgrade.backup(str(live),str(backup))
    assert facts(backup)==before
    assert stat.S_IMODE(backup.stat().st_mode)==0o600

    # Simulate future app adding a schema column and new observations.
    with sqlite3.connect(live) as db:
        db.execute("ALTER TABLE observations ADD COLUMN future_feature REAL")
        db.execute("INSERT INTO observations(btc,future_feature) VALUES(64000,2.1)")
        db.execute("UPDATE paper_trades SET pnl=0")
    assert facts(live)!=before

    dbupgrade.restore(str(backup),str(live))
    assert facts(live)==before
    assert not (tmp_path/"bot.sqlite3-wal").exists()
    assert not (tmp_path/"bot.sqlite3-shm").exists()


def test_backup_never_overwrites_a_previous_checkpoint(tmp_path):
    live=create(tmp_path/"bot.sqlite3")
    backup=tmp_path/"pre-upgrade.sqlite3"
    dbupgrade.backup(str(live),str(backup))
    before=backup.read_bytes()
    with pytest.raises(FileExistsError):
        dbupgrade.backup(str(live),str(backup))
    assert backup.read_bytes()==before


def test_corrupted_backup_cannot_replace_healthy_live_database(tmp_path):
    live=create(tmp_path/"bot.sqlite3")
    before=facts(live)
    corrupt=tmp_path/"bad-backup.sqlite3"
    corrupt.write_bytes(b"This is not a SQLite database.")
    with pytest.raises((sqlite3.DatabaseError,RuntimeError)):
        dbupgrade.restore(str(corrupt),str(live))
    assert facts(live)==before


def test_symlinks_are_never_used_for_source_or_rollback(tmp_path):
    live=create(tmp_path/"bot.sqlite3")
    alias=tmp_path/"alias.sqlite3"
    alias.symlink_to(live)
    with pytest.raises(ValueError,match="unsafe"):
        dbupgrade.backup(str(alias),str(tmp_path/"backup.sqlite3"))
    backup=tmp_path/"pre-upgrade.sqlite3"
    dbupgrade.backup(str(live),str(backup))
    with pytest.raises(ValueError,match="regular"):
        dbupgrade.restore(str(backup),str(alias))


def test_cli_and_ownership_and_permissions(tmp_path):
    live=create(tmp_path/"bot.sqlite3")
    backup=tmp_path/"pre-upgrade.sqlite3"
    uid,gid=live.stat().st_uid,live.stat().st_gid
    os.chmod(live,0o640)
    assert dbupgrade.main(["backup",str(live),str(backup)])==0
    with sqlite3.connect(live) as db:
        db.execute("INSERT INTO observations(btc) VALUES(65555)")
    assert dbupgrade.main(["restore",str(backup),str(live)])==0
    assert dbupgrade.main(["verify",str(backup),str(live)])==0
    assert dbupgrade.main(["invalid"])==2
    assert (live.stat().st_uid,live.stat().st_gid)==(uid,gid)
    assert stat.S_IMODE(live.stat().st_mode)==0o640
    assert facts(live)[1]==[(63000.,),(63020.,)]
