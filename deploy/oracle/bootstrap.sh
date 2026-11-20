#!/usr/bin/env bash
# Manual preparation only: no server starts, public ports or real orders.
set -Eeuo pipefail
REPO_URL='https://github.com/szmohmand/Axiom.git'
DEPLOY_BRANCH='main'
VERIFIED_BASE='6f4ace73e0627e23824df09e0bf4039b94fe2dc0'
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo' >&2; exit 2; fi
. /etc/os-release
if [[ $ID != ubuntu || $(uname -m) != aarch64 ]]; then
  echo 'Expected Ubuntu ARM64; refusing other host' >&2; exit 2
fi
if [[ -e /opt/axiom/current ]]; then echo 'Existing installation; refusing overwrite' >&2; exit 2; fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git python3 python3-venv python3-pip ca-certificates
if ! id -u axiom >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/axiom --create-home --shell /usr/sbin/nologin axiom
fi
install -d -o axiom -g axiom -m 0750 /var/lib/axiom
install -d -m 0755 /opt/axiom
install -d -m 0700 /etc/axiom
git clone --branch "$DEPLOY_BRANCH" --depth 20 "$REPO_URL" /opt/axiom/current
cd /opt/axiom/current
if ! git cat-file -e "$VERIFIED_BASE^{commit}" 2>/dev/null ||
   ! git merge-base --is-ancestor "$VERIFIED_BASE" HEAD; then
  echo 'Verified integration SHA not reachable; stop' >&2; exit 3
fi
# Only deployment files and static tests may differ from verified source.
if git diff --name-only "$VERIFIED_BASE" HEAD | grep -Ev '^(deploy/oracle/|tests/test_oracle_deployment_package\.py$)'; then
  echo 'Unexpected application changes; refusing to install' >&2; exit 3
fi
python3 -m venv /opt/axiom/venv
/opt/axiom/venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock.txt
export DEMO_MODE=1 AUTO_PAPER=0 BRTI_LIVE_ENABLED=0
export DATA_PATH=/var/lib/axiom/bootstrap-test.sqlite3
/opt/axiom/venv/bin/python -m pytest -q
rm -f /var/lib/axiom/bootstrap-test.sqlite3 /var/lib/axiom/bootstrap-test.sqlite3-shm /var/lib/axiom/bootstrap-test.sqlite3-wal
if [[ ! -e /etc/axiom/axiom.env ]]; then
  install -o root -g root -m 0600 deploy/oracle/axiom.env.example /etc/axiom/axiom.env
fi
install -o root -g root -m 0644 deploy/oracle/axiom.service /etc/systemd/system/axiom.service
chown -R root:root /opt/axiom/current /opt/axiom/venv
systemctl daemon-reload
echo 'Prepared and tested only. AXIOM service is NOT started or enabled.'
