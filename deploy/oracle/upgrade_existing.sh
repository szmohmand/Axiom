#!/usr/bin/env bash
# Existing Oracle Ubuntu x86_64 AXIOM VM only. Do NOT run the ARM bootstrap.
# Usage: sudo bash deploy/oracle/upgrade_existing.sh <all-green-main-40-char-SHA>
set -Eeuo pipefail
umask 022
ROOT=/opt/axiom
ENVFILE=/etc/axiom/axiom.env
SERVICE=axiom.service
REPO=https://github.com/szmohmand/Axiom.git
OVERRIDE_DIR=/etc/systemd/system/axiom.service.d
OVERRIDE_FILE="$OVERRIDE_DIR/90-axiom-verified-release.conf"
fail() { printf 'AXIOM UPGRADE BLOCKED: %s\n' "$*" >&2; exit 2; }
msg() { printf 'AXIOM UPGRADE: %s\n' "$*"; }

[[ $EUID -eq 0 ]] || fail 'Use sudo on the EXISTING VM, never an uninitialized instance.'
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || fail 'Pass exact green-tested main commit SHA.'
COMMIT=$1
[[ $(uname -m) == x86_64 ]] || fail 'Ubuntu x86_64 E2.1.Micro required: never run ARM/bootstrap here.'
[[ -r "$ENVFILE" && -d "$ROOT/current" && -x "$ROOT/venv/bin/python" ]] ||
    fail 'Expected current installation/env/venv missing; do not bootstrap or overwrite.'
[[ -d /var/lib/axiom ]] || fail 'Persistent AXIOM data directory missing.'
id axiom >/dev/null 2>&1 || fail 'Dedicated axiom service user is missing.'
systemctl cat "$SERVICE" >/dev/null || fail 'Existing AXIOM service missing.'
systemctl is-active --quiet "$SERVICE" || fail 'Existing service not active; diagnose it first.'
[[ $(systemctl show --value -p User "$SERVICE") == axiom ]] ||
    fail 'Service must run as existing unprivileged axiom user.'
command -v git >/dev/null && command -v python3 >/dev/null ||
    fail 'Git and system Python must already be installed.'

# Read config without sourcing it or exposing the Kalshi private credentials.
DATA_PATH=$(python3 - "$ENVFILE" <<'PY'
import os,stat,sys
p=sys.argv[1];st=os.stat(p)
if st.st_uid!=0 or stat.S_IMODE(st.st_mode)&0o077:
    raise SystemExit('Root-only AXIOM env permissions are not secure.')
values={}
for line in open(p,encoding='utf8'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line:continue
    k,v=line.split('=',1)
    if k.strip() in ('DATA_PATH','AUTO_PAPER','DEMO_MODE'):
        values[k.strip()]=v.strip().strip("'\"")
if values.get('AUTO_PAPER','1')!='0':
    raise SystemExit('AUTO_PAPER must be explicitly disabled in the EXISTING environment.')
if values.get('DEMO_MODE','1')!='0':
    raise SystemExit('DEMO_MODE must be explicitly configured as live, not synthetic.')
print(values.get('DATA_PATH','/var/lib/axiom/bot.sqlite3'))
PY
) || fail 'Existing env config is incompatible/unsafe; no changes made.'
[[ "$DATA_PATH" == /var/lib/axiom/* && -f "$DATA_PATH" && ! -L "$DATA_PATH" ]] ||
    fail 'Persistent SQLite ledger must be a regular file inside /var/lib/axiom.'
[[ -z $(find /var/lib/axiom -maxdepth 1 -name 'not-used-placeholder-axiom' -print) ]] ||
    fail 'Unexpected filesystem state.'

# VM is only 1 GB RAM; require the previously configured swap and disk headroom.
# This is a preflight blocker, not a cloud scaling or billable provisioning step.
python3 - "$ROOT" "$DATA_PATH" <<'PY'
import os,shutil,sys
root,db=sys.argv[1:3]
info={}
for line in open('/proc/meminfo'):
    k,_,v=line.partition(':')
    if k in ('MemTotal','SwapTotal'):
        info[k]=int(v.strip().split()[0])*1024
if info.get('MemTotal',0)<1_600_000_000 and info.get('SwapTotal',0)<2_000_000_000:
    raise SystemExit('Low-RAM x86 VM needs >=2GB of active swap before upgrading.')
dbsize=os.stat(db).st_size
rootfree=shutil.disk_usage(root).free
dbfree=shutil.disk_usage(os.path.dirname(db)).free
if rootfree<1_500_000_000:
    raise SystemExit('Need >=1.5GB free for isolated checkout and Python venv.')
if dbfree<max(750_000_000,dbsize*3+250_000_000):
    raise SystemExit('Insufficient disk headroom for two SQLite backups and a rollback.')
PY

# Baseline must already be healthy, or source-change and provider-outage issues
# cannot be distinguished. Read localhost only; never expose port 8000.
python3 - <<'PY'
import json,urllib.request
for path in ('/health','/api/state'):
    with urllib.request.urlopen('http://127.0.0.1:8000'+path,timeout=10) as r:
        body=json.load(r)
        if r.status!=200:raise SystemExit('Existing AXIOM baseline HTTP degraded')
        if path=='/health' and not body.get('ok'):
            raise SystemExit('Existing AXIOM baseline unhealthy')
PY

RELEASE="$ROOT/releases/$COMMIT"
VENV="$ROOT/venvs/$COMMIT"
[[ ! -e "$RELEASE" && ! -e "$VENV" ]] ||
    fail 'Exact release already staged; review it instead of overwriting.'
mkdir -p "$ROOT/releases" "$ROOT/venvs"
msg "Staging exact tested SHA $COMMIT alongside the untouched running code."
git clone --quiet --depth 1 --branch main "$REPO" "$RELEASE"
[[ $(git -C "$RELEASE" rev-parse HEAD) == "$COMMIT" ]] ||
    fail 'main advanced past the green-tested SHA: abort.'

# Match the installed Python ABI (the repo lock was tested under Python 3.13,
# while Ubuntu 24.04 commonly uses 3.12). Wheel-only installs fail safely.
"$ROOT/venv/bin/python" -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-cache-dir \
    --only-binary=:all: -r "$RELEASE/requirements.lock.txt"
"$VENV/bin/python" -m pip check
"$VENV/bin/python" -m compileall -q "$RELEASE/app"
[[ -r "$RELEASE/app/main.py" && -x "$VENV/bin/uvicorn" ]] ||
    fail 'Staged app/venv not readable or uvicorn missing.'

umask 077
BACKUP_DIR="/var/lib/axiom/deploy-backups/$(date -u +%Y%m%dT%H%M%SZ)-$(printf %.12s "$COMMIT")"
mkdir -p -m 0700 "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/pre-upgrade.sqlite3"
PRECHECK="$BACKUP_DIR/preflight-copy.sqlite3"

# Run the COMPLETE regression suite on THIS VM and THIS Python ABI, rather
# than assuming a green GitHub Linux/Python 3.13 run guarantees Ubuntu 3.12.
# Tests use a throwaway DB: they never connect to the production ledger.
msg 'Running complete regression suite in an isolated staging environment.'
# On a single-core VM, deprioritize CPU-heavy tests so the current systemd
# worker keeps precedence; all tests are also isolated from the live ledger.
(
    cd "$RELEASE"
    nice -n 15 env DEMO_MODE=1 AUTO_PAPER=0 BRTI_LIVE_ENABLED=0 \
      DATA_PATH="$BACKUP_DIR/stage-tests.sqlite3" \
      "$VENV/bin/python" -m pytest -q
)
rm -f "$BACKUP_DIR/stage-tests.sqlite3" \
      "$BACKUP_DIR/stage-tests.sqlite3-wal" \
      "$BACKUP_DIR/stage-tests.sqlite3-shm"

# Online backup while the old service still runs, for a no-downtime migration
# rehearsal against a real (copied) schema. This cannot modify production DB.
sqlite_backup() {
    python3 "$RELEASE/deploy/oracle/upgrade_sqlite.py" backup "$1" "$2"
}
sqlite_backup "$DATA_PATH" "$PRECHECK"
# Monitor the actual archived history during schema migration rehearsal.
# New tables/columns may be added, but established record counts must stay.
history_counts() {
    python3 - "$1" <<'PY'
import json,sqlite3,sys
conn=sqlite3.connect(sys.argv[1])
counts={}
for table in ('observations','paper_trades','engine_snapshots','contracts'):
    has=conn.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',
                     ('table',table)).fetchone()
    if has:
        counts[table]=conn.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]
print(json.dumps(counts,sort_keys=True))
conn.close()
PY
}
COUNTS_BEFORE=$(history_counts "$PRECHECK")
(
    cd "$RELEASE"
    DEMO_MODE=1 AUTO_PAPER=0 BRTI_LIVE_ENABLED=0 DATA_PATH="$PRECHECK" \
        "$VENV/bin/python" -c \
        "from app.main import app; assert any(r.path=='/health' for r in app.routes); assert any(r.path=='/api/state' for r in app.routes)"
)
python3 - "$PRECHECK" <<'PY'
import sqlite3,sys
db=sqlite3.connect(sys.argv[1])
if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
    raise SystemExit('Staged migration rehearsal corrupted the copied database')
db.close()
PY
COUNTS_AFTER=$(history_counts "$PRECHECK")
[[ "$COUNTS_BEFORE" == "$COUNTS_AFTER" ]] ||
    fail 'Schema rehearsal changed historical observations/trades/grades on a copy; no production changes made.'
rm -f "$PRECHECK" "$PRECHECK-wal" "$PRECHECK-shm"

# Keep exact previous override; if no override existed, the original service
# points to /opt/axiom/current and /opt/axiom/venv, which remain untouched.
mkdir -p "$OVERRIDE_DIR"
HAD_OLD=0
if [[ -f "$OVERRIDE_FILE" ]];then
    cp -p "$OVERRIDE_FILE" "$BACKUP_DIR/previous-release.conf"
    HAD_OLD=1
fi
STOPPED=0
SWITCHED=0

# On failure, FIRST stop the new service, archive its DB (if possible), restore
# the exact pre-upgrade SQLite snapshot including ownership, and then restart
# previous code. Code-only rollback is not safe after schema changes.
rollback() {
    rc=$1
    ((rc!=0)) || rc=1
    trap - ERR INT TERM HUP
    if [[ "$STOPPED" -eq 1 ]];then
        msg 'Upgrade failed. Attempting recovery of previous service + database.'
        if systemctl stop "$SERVICE";then
            if [[ "$SWITCHED" -eq 1 && -f "$BACKUP" ]];then
                # Preserve any brief new-version observations for later
                # inspection instead of silently discarding the failed DB.
                sqlite_backup "$DATA_PATH" "$BACKUP_DIR/failed-release.sqlite3" ||
                    msg 'Could not snapshot new release DB; restoring pre-upgrade DB.'
                python3 "$RELEASE/deploy/oracle/upgrade_sqlite.py" restore "$BACKUP" "$DATA_PATH"
            fi
        else
            msg 'Could not stop failed service; DO NOT overwrite in-use SQLite. Manual recovery required.'
            exit "$rc"
        fi
        if [[ "$HAD_OLD" -eq 1 ]];then
            cp -p "$BACKUP_DIR/previous-release.conf" "$OVERRIDE_FILE"
        else
            rm -f "$OVERRIDE_FILE"
        fi
        systemctl daemon-reload || true
        systemctl restart "$SERVICE" || true
        if systemctl is-active --quiet "$SERVICE";then
            msg 'Previous service restarted, original database restored if changed.'
        else
            msg 'Previous service did not restart: inspect systemd and backup; do not retry blindly.'
        fi
    fi
    msg "Backup and recovery evidence retained: $BACKUP_DIR"
    exit "$rc"
}
trap 'rollback $?' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM
trap 'rollback 129' HUP

# A final consistent backup is taken AFTER stopping the previous service,
# so a rollback does not lose writes that happened during dependency staging.
STOPPED=1
systemctl stop "$SERVICE"
sqlite_backup "$DATA_PATH" "$BACKUP"
msg "Final stopped-service SQLite backup passed integrity check: $BACKUP"

cat > "$OVERRIDE_FILE" <<EOF
# Verified AXIOM release; existing service user, security and env unchanged.
[Service]
WorkingDirectory=$RELEASE
ExecStart=
ExecStart=$VENV/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
EOF
chmod 0644 "$OVERRIDE_FILE"
SWITCHED=1
systemctl daemon-reload
systemctl start "$SERVICE"

# Must verify THE ACTUAL Oracle process, not a green GitHub log or an import.
RELEASE="$RELEASE" SERVICE="$SERVICE" python3 - <<'PY'
import json,os,subprocess,time,urllib.request
expected=os.environ['RELEASE'];service=os.environ['SERVICE']
last='No response yet'
for _ in range(35):
    try:
        if subprocess.run(['systemctl','is-active','--quiet',service]).returncode:
            raise RuntimeError('service is not active')
        pid=subprocess.check_output(['systemctl','show','--value','-p','MainPID',
                                     service],text=True).strip()
        if not pid.isdigit() or int(pid)<=1:
            raise RuntimeError('missing service PID')
        if os.path.realpath('/proc/'+pid+'/cwd')!=expected:
            raise RuntimeError('systemd process is not running pinned release')
        def read(path):
            with urllib.request.urlopen('http://127.0.0.1:8000'+path,
                                        timeout=4) as resp:
                return resp.status,json.load(resp)
        hc,h=read('/health')
        sc,s=read('/api/state')
        if hc!=200 or sc!=200 or not h.get('ok'):
            raise RuntimeError('live API is degraded')
        if 'contract_repricing' not in s or 'higher_timeframes' not in s:
            raise RuntimeError('integrated BTC/contract-pricing API fields missing')
        if s.get('paper_auto_enabled') is not False:
            raise RuntimeError('paper auto-entry was not disabled')
        q=s['contract_repricing'] or {}
        if q.get('order_placed') is not False or q.get('independent_btc_forecast_changed') is not False:
            raise RuntimeError('Kalshi quote model is not verified read-only/isolated')
        if (s.get('execution_intelligence') or {}).get('order_placed') is not False:
            raise RuntimeError('execution is not read-only')
        print('PASS: running tested AXIOM release, healthy read-only local API and separate Kalshi pricing model.')
        break
    except Exception as exc:
        last=type(exc).__name__+': '+str(exc)
        time.sleep(2)
else:
    raise RuntimeError('Oracle verification failed: '+last)
PY

trap - ERR INT TERM HUP
msg "SUCCESS: existing x86 Oracle AXIOM runs tested release $COMMIT."
msg "Original app/venv, env and pre-upgrade SQLite backup are retained."
