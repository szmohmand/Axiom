"""Static and shell-syntax safety checks for EXISTING x86 Oracle upgrade.

The deploy script is never executed against a cloud host in CI. The checks
verify that it cannot be confused with the obsolete ARM bootstrap and that
the verified green commit, existing DB, backup, rollback and live read-only
health verification are required before a release is reported successful.
"""
import subprocess
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"deploy"/"oracle"/"upgrade_existing.sh"


def source():
    return SCRIPT.read_text(encoding="utf-8")


def test_upgrade_script_has_valid_bash_syntax():
    p=subprocess.run(["bash","-n",str(SCRIPT)],capture_output=True,text=True)
    assert p.returncode==0,p.stderr


def test_upgrade_targets_existing_ubuntu_x86_server_not_new_arm_bootstrap():
    s=source()
    assert "uname -m" in s and "x86_64" in s
    assert '[[ -d "$ROOT/current" ]]' not in s or "do not bootstrap" in s.lower()
    assert "systemctl is-active --quiet" in s
    for forbidden in ("apt-get install","useradd ","terraform ","oci compute instance launch",
                      "systemctl enable","bootstrap.sh\n", "AUTO_PAPER=1",
                      "KALSHI_PRIVATE_KEY_PEM=","KALSHI_API_KEY_ID="):
        assert forbidden not in s


def test_exact_green_commit_and_separate_staged_release_required():
    s=source()
    assert '^[0-9a-f]{40}$' in s
    assert 'git -C "$RELEASE" rev-parse HEAD' in s
    assert '"$COMMIT"' in s
    assert 'RELEASE="$ROOT/releases/$COMMIT"' in s
    assert 'VENV="$ROOT/venvs/$COMMIT"' in s
    assert "pip check" in s
    assert "compileall" in s
    assert "DEMO_MODE=1 AUTO_PAPER=0" in s


def test_persistent_sqlite_backup_original_env_and_rollback_are_preserved():
    s=source()
    assert 'ENVFILE=/etc/axiom/axiom.env' in s
    assert "DATA_PATH" in s
    assert "/var/lib/axiom/deploy-backups/" in s
    assert "source.backup(dest" in s
    assert "PRAGMA integrity_check" in s
    assert "ACTIVATED=0" in s and "trap rollback ERR" in s
    assert 'systemctl restart "$SERVICE"' in s
    assert "previous-release.conf" in s
    assert "read-only" in s.lower()
    assert "order_placed" in s
    assert "independent_btc_forecast_changed" in s
    assert "http://127.0.0.1:8000" in s


def test_impossible_sha_fails_before_touching_vm():
    # Root user in CI or unprivileged CI: in either case, this deliberately
    # invalid SHA must stop prior to any clone, env load or service operation.
    p=subprocess.run(["bash",str(SCRIPT),"not-a-commit"],
                     capture_output=True,text=True,timeout=8)
    assert p.returncode!=0
    assert "AXIOM UPGRADE BLOCKED" in p.stderr
