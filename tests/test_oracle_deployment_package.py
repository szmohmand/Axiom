"""Deployment package invariants; never provision or deploy resources."""
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1] / "deploy" / "oracle"

def test_oracle_installer_syntax_and_manual_activation():
    script = ROOT / "bootstrap.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)
    body = script.read_text()
    lines = [x.strip() for x in body.splitlines() if x.lstrip().startswith("systemctl ")]
    assert lines == ["systemctl daemon-reload"]
    assert "VERIFIED_BASE='a25c960a36a7b5af5a6646b6bf6e0ffa6f2a5aef'" in body
    assert "python -m pytest -q" in body
    assert "DEPLOY_BRANCH='main'" in body
    assert "git merge-base --is-ancestor" in body

def test_read_only_one_worker_and_persistent_database():
    svc = (ROOT / "axiom.service").read_text()
    env = (ROOT / "axiom.env.example").read_text()
    assert "--host 127.0.0.1 --port 8000 --workers 1" in svc
    assert "User=axiom" in svc and "ReadWritePaths=/var/lib/axiom" in svc
    for v in ("DEMO_MODE=0", "AUTO_PAPER=0", "BRTI_LIVE_ENABLED=0",
              "DATA_PATH=/var/lib/axiom/bot.sqlite3", "BOT_ADMIN_TOKEN=\n"):
        assert v in env

def test_https_reverse_proxy_is_private_upstream():
    assert "reverse_proxy 127.0.0.1:8000" in (ROOT / "Caddyfile.example").read_text()
