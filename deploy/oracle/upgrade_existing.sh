#!/usr/bin/env bash
# In-place upgrade for existing Oracle Ubuntu x86 AXIOM VM; NEVER run bootstrap.
# Usage: sudo bash deploy/oracle/upgrade_existing.sh <exact-green-main-commit-SHA>
set -Eeuo pipefail
REPO=https://github.com/szmohmand/Axiom.git
ROOT=/opt/axiom
ENVFILE=/etc/axiom/axiom.env
OVERRIDE_DIR=/etc/systemd/system/axiom.service.d
OVERRIDE_FILE="$OVERRIDE_DIR/90-axiom-verified-release.conf"
SERVICE=axiom.service
fail() { printf 'AXIOM UPGRADE BLOCKED: %s\n' "$*" >&2; exit 2; }
msg() { printf 'AXIOM UPGRADE: %s\n' "$*"; }

[[ $EUID -eq 0 ]] || fail 'Run with sudo ON THE EXISTING VM.'
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || fail 'Pass exact green-tested main SHA.'
COMMIT="$1"
[[ $(uname -m) == x86_64 ]] || fail 'This is for the existing x86 VM, not ARM bootstrap.'
[[ -r "$ENVFILE" && -d "$ROOT/current" && -x "$ROOT/venv/bin/python" ]] || fail 'Existing AXIOM installation/env/venv missing. Do not bootstrap.'
[[ -d /var/lib/axiom ]] || fail 'Persistent data directory missing.'
id axiom >/dev/null 2>&1 || fail 'Service user missing.'
systemctl cat "$SERVICE" >/dev/null || fail 'Existing systemd service missing.'
systemctl is-active --quiet "$SERVICE" || fail 'Existing service inactive. Inspect it first.'
command -v git >/dev/null && command -v python3 >/dev/null || fail 'Git/system Python missing.'

# Parse only DATA_PATH. Never source environment or print credentials.
DATA_PATH=$(python3 - "$ENVFILE" <<'PY'
import sys
path='/var/lib/axiom/bot.sqlite3'
for line in open(sys.argv[1],encoding='utf-8'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line:continue
    k,v=line.split('=',1)
    if k.strip()=='DATA_PATH':path=v.strip().strip("'\"")
print(path)
PY
)
[[ "$DATA_PATH" == /var/lib/axiom/* && -f "$DATA_PATH" ]] || fail 'Existing SQLite not found inside persistent data folder. Stop before modifying anything.'

RELEASE="$ROOT/releases/$COMMIT"
VENV="$ROOT/venvs/$COMMIT"
[[ ! -e "$RELEASE" && ! -e "$VENV" ]] || fail 'Exact release already staged; no overwrite.'
mkdir -p "$ROOT/releases" "$ROOT/venvs" "$OVERRIDE_DIR"
msg "Fetching requested exact SHA $COMMIT without altering current running code."
git clone --quiet --depth 1 --branch main "$REPO" "$RELEASE" || fail 'Unable to clone.'
[[ $(git -C "$RELEASE" rev-parse HEAD) == "$COMMIT" ]] || fail 'main changed; reconfirm green-tested commit.'
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check \
    --no-cache-dir --only-binary=:all: -r "$RELEASE/requirements.lock.txt"
"$VENV/bin/python" -m pip check
"$VENV/bin/python" -m compileall -q "$RELEASE/app"
PRECHECK_DB=$(mktemp /tmp/axiom-precheck.XXXXXXXX.sqlite3)
trap 'rm -f "$PRECHECK_DB" "$PRECHECK_DB-shm" "$PRECHECK_DB-wal"' EXIT
(
  cd "$RELEASE"
  DEMO_MODE=1 AUTO_PAPER=0 DATA_PATH="$PRECHECK_DB" \
     "$VENV/bin/python" -c \
     "from app.main import app; assert any(r.path=='/health' for r in app.routes)"
)
rm -f "$PRECHECK_DB" "$PRECHECK_DB-shm" "$PRECHECK_DB-wal"
trap - EXIT

# Transactionally back up the live SQLite database while it is still online.
umask 077
BACKUP_DIR="/var/lib/axiom/deploy-backups/$(date -u +%Y%m%dT%H%M%SZ)-$(printf %.12s "$COMMIT")"
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/ledger.sqlite3"
python3 - "$DATA_PATH" "$BACKUP" <<'PY'
import os,sqlite3,sys
source=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True,timeout=20)
dest=sqlite3.connect(sys.argv[2])
with dest:source.backup(dest,pages=1000,sleep=.1)
if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
    raise RuntimeError('SQLite backup integrity failure')
source.close()
dest.close()
os.chmod(sys.argv[2],0o600)
PY
msg "Verified read-only backup saved at $BACKUP"

HAD_OLD=0
if [[ -e "$OVERRIDE_FILE" ]];then
    cp -p "$OVERRIDE_FILE" "$BACKUP_DIR/previous-release.conf"
    HAD_OLD=1
fi
ACTIVATED=0
rollback() {
    rc=$?
    trap - ERR
    if [[ "$ACTIVATED" -eq 1 ]];then
        if [[ "$HAD_OLD" -eq 1 ]];then
            cp -p "$BACKUP_DIR/previous-release.conf" "$OVERRIDE_FILE"
        else
            rm -f "$OVERRIDE_FILE"
        fi
        systemctl daemon-reload || true
        systemctl restart "$SERVICE" || true
        msg 'Verification failed: previous systemd release restored. Inspect service.'
    fi
    exit "$rc"
}
trap rollback ERR
cat > "$OVERRIDE_FILE" <<EOF
# Pinned AXIOM source release, preserving original service security and env.
[Service]
WorkingDirectory=$RELEASE
ExecStart=
ExecStart=$VENV/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
EOF
chmod 0644 "$OVERRIDE_FILE"
ACTIVATED=1
systemctl daemon-reload
systemctl restart "$SERVICE"

# Confirm this particular code version is serving and read-only flags hold.
RELEASE="$RELEASE" SERVICE="$SERVICE" python3 - <<'PY'
import json,os,subprocess,time,urllib.request
release=os.environ['RELEASE'];service=os.environ['SERVICE']
last=''
for _ in range(35):
    try:
        if subprocess.run(['systemctl','is-active','--quiet',service]).returncode:
            raise RuntimeError('service inactive')
        pid=subprocess.check_output(
            ['systemctl','show','--value','-p','MainPID',service],text=True).strip()
        if not pid.isdigit() or int(pid)<=1:
            raise RuntimeError('no service PID')
        if os.path.realpath('/proc/'+pid+'/cwd')!=release:
            raise RuntimeError('wrong code path in running process')
        def get(path):
            with urllib.request.urlopen('http://127.0.0.1:8000'+path,timeout=4) as resp:
                return resp.status,json.load(resp)
        hs,h=get('/health');ss,s=get('/api/state')
        if hs!=200 or ss!=200 or not h.get('ok'):
            raise RuntimeError('live HTTP health/state degraded')
        if 'contract_repricing' not in s or 'higher_timeframes' not in s:
            raise RuntimeError('latest integrated API fields missing')
        quote=s['contract_repricing'] or {}
        if quote.get('order_placed') is not False or quote.get('independent_btc_forecast_changed') is not False:
            raise RuntimeError('contract-repricing isolation flag missing')
        if (s.get('execution_intelligence') or {}).get('order_placed') is not False:
            raise RuntimeError('execution is not confirmed read-only')
        print('PASS: exact tested AXIOM code is running with healthy HTTP and read-only contract model.')
        break
    except Exception as exc:
        last=type(exc).__name__+': '+str(exc)
        time.sleep(2)
else:
    raise RuntimeError('New AXIOM release did not verify: '+last)
PY
trap - ERR
msg "SUCCESS: Existing VM now runs verified AXIOM $COMMIT. Ledger + original installation retained."
