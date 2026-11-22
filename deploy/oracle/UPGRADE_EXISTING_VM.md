# AXIOM: upgrade the existing Oracle VM

Target: the **existing** Ubuntu 24.04 x86_64 E2.1.Micro in Ashburn AD-3,
instance-20261120-1413. It has **1 OCPU, 1 GB RAM and an existing 4 GB
swapfile**. Its prior FastAPI/systemd endpoint is 127.0.0.1:8000.
This is NOT a fresh ARM deployment. The installer verifies the real VM
shape, available swap, disk and application health again before doing
anything. This historical VM description is not a substitute for SSH
inspection and live health checks.

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
- Requires the current systemd service to be healthy, running as dedicated
  non-root user axiom, with root-only environment configuration and
  AUTO_PAPER=0 / DEMO_MODE=0. Checks the **active swap (at least 2 GB for
  this 1 GB VM)** and disk headroom. Never resizes/provisions anything.
- Uses the same base Python ABI as the existing virtualenv to avoid
  accidentally installing dependencies for a different Python version.
  Installs locked wheels only; an incompatible wheel **blocks** deployment.
- Stages a new isolated virtualenv and runs the **entire pytest suite on the
  actual x86 VM** using a throwaway database, while the previous service
  continues running. On this low-resource VM, this is protected by the swap
  and disk preflights; the old service is not restarted until checks pass.
- Makes a root-only SQLite online backup **copy** and rehearses new app
  startup/schema initialization against that copy. Compares historical
  observations, paper trade, scorecard and contract counts before/after.
- Stops the previous service briefly, then makes an exact *stopped-service*
  SQLite backup under /var/lib/axiom/deploy-backups/ (integrity-checked).
  This protects any records written while code/tests were being staged.
- Updates only an AXIOM systemd release drop-in and starts the new service.
- On failure, first stops the new service, retains a copy of its last DB
  when possible, atomically restores the previous **database and systemd
  release** together, then restarts the prior application version. A
  code-only rollback could fail if the new version had changed the DB schema.
- Verifies the running process is executing the expected code directory and
  localhost /health and /api/state both return HTTP 200.
- Verifies contract_repricing and higher_timeframes outputs and read-only flags.
- Does not overwrite the original environment file. The persistent SQLite
  ledger is only replaced **during failure recovery**, from an exact saved
  pre-upgrade copy; the running service is stopped first, and original
  ownership/mode and historical records are restored.
- Leaves the original /opt/axiom/current and /opt/axiom/venv untouched.
  Backup and release retention uses disk over time: check space before each
  future upgrade, and do not blindly delete the most recent rollback copy.
- A healthy localhost service is separate from an iPhone HTTPS site;
  no DNS, Caddy, public firewall rules or billable cloud resources change.
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