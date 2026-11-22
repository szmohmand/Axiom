# AXIOM: upgrade the existing Oracle VM

Target: existing Ubuntu 24.04 x86_64 E2.1.Micro in Ashburn AD-3,
instance-20261120-1413. Previous local FastAPI/systemd endpoint
127.0.0.1:8000. This is NOT a fresh ARM deployment.

Do NOT run deploy/oracle/bootstrap.sh: it only supports ARM and
refuses existing installs. Do NOT create another VM.

## Run from the terminal on the existing VM

Check that all six GitHub Actions on the exact main commit have passed.
Connect via the VM's private SSH method; never paste SSH keys in chat.

    VERIFIED_SHA='PASTE_EXACT_GREEN_MAIN_40_CHARACTER_SHA'
    stage="$(mktemp -d)"
    git clone --depth 1 --branch main https://github.com/szmohmand/Axiom.git "$stage/source"
    test "$(git -C "$stage/source" rev-parse HEAD)" = "$VERIFIED_SHA" || { echo 'main changed; stop'; exit 1; }
    sudo bash "$stage/source/deploy/oracle/upgrade_existing.sh" "$VERIFIED_SHA"

## What the upgrade script does

- Requires an already-running existing AXIOM service, the original
  installation and its existing root-only configuration.
- Fetches only the exact green-tested main SHA.
- Stages a separate virtualenv; leaves the live version untouched until activation.
- Makes and integrity-checks an online SQLite backup under
  /var/lib/axiom/deploy-backups/ with root-only permissions.
- Updates only an AXIOM systemd release drop-in and restarts the service.
- Restores the prior drop-in and restarts the previous release on failed checks.
- Verifies the running process is executing the expected code directory and
  localhost /health and /api/state both return HTTP 200.
- Verifies contract_repricing and higher_timeframes outputs and read-only flags.
- Never overwrites the original environment file or SQLite ledger.
- Never installs ARM bootstrap, creates cloud resources, opens public ports,
  enables real-money orders or turns on paper auto-entry.

## Independent verification after success

    sudo systemctl is-active axiom
    sudo systemctl status axiom --no-pager
    curl -fsS http://127.0.0.1:8000/health
    curl -fsS http://127.0.0.1:8000/api/state

GitHub checks alone do not prove the Oracle VM is updated.
The upgrade is complete only after the live server passes verification.
A private iPhone HTTPS access path is separate and not created by this command.

Server SSH endpoint, credentials and actual running revision are not available
to the current chat, so remote deployment requires connecting to that existing VM.