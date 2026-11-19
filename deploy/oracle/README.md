# AXIOM Oracle deployment handoff — PREPARATION ONLY

## Source and status
This isolated branch adds only deployment files and static tests to fully
integrated candidate c20242bf66ee63ec555b67119d4f92d395f0f74a
(Draft PR #20). The prior GitHub offline, live-provider, authenticated
1Hz/5Hz BRTI, real FastAPI workers, coverage and browser checks passed at
that SHA. This branch does NOT modify application code, main, PR #20 or
existing running systems.

Oracle Always Free ARM A1.Flex VM requests failed for capacity in all three
Ashburn availability domains (also with smaller memory/CPU). The VCN
axiom-vcn and public subnet exist. NO VM, live server, domain or HTTPS
website has been deployed or verified.

## After Oracle actually allocates a VM
1. Confirm Ubuntu 24.04 Minimal ARM64, A1.Flex Always Free capacity and
   persistent boot-volume allocation. Do not upgrade the account.
2. Restrict the VCN wizard default SSH ingress 22 (0.0.0.0/0) to your
   administration IP or private tunnel. Permit 80/443 publicly for HTTPS
   only when needed. NEVER expose port 8000 or the SQLite database.
3. Connect to the VM via its private SSH key (do not send the key in chat).
   On Ubuntu:

       git clone --depth 20 --branch deploy/axiom-oracle-preparation-2026-11-19 https://github.com/szmohmand/Axiom.git /tmp/axiom-deploy
       sudo bash /tmp/axiom-deploy/deploy/oracle/bootstrap.sh

   The bootstrap verifies that original tested application files were
   untouched, installs pinned requirements, runs full offline regression,
   and installs systemd configuration. It does NOT start or enable AXIOM.
   The lockfile was last verified with Python 3.13, whereas Ubuntu 24.04
   ARM may use Python 3.12: dependency compatibility must be tested on
   real ARM hardware. Failed installs must NOT silently use unpinned deps.
4. Inspect /etc/axiom/axiom.env (root-only mode 0600). It defaults to
   DEMO_MODE=0, AUTO_PAPER=0, BRTI_LIVE_ENABLED=0, empty admin token,
   DATA_PATH=/var/lib/axiom/bot.sqlite3. After explicit permission:

       sudo systemctl enable --now axiom
       sudo systemctl status axiom --no-pager
       sudo /opt/axiom/venv/bin/python /opt/axiom/current/deploy/oracle/verify.py
       sudo journalctl -u axiom -n 70 --no-pager

   HTTP 503 = degraded, not verified running health.
5. For read-only live BRTI, privately provide KALSHI_API_KEY_ID and
   KALSHI_PRIVATE_KEY_PEM in the root-only server environment. Quote PEM
   with literal backslash-n between lines; the existing signer expands it.
   Enable BRTI_LIVE_ENABLED=1 and restart only after reviewing credentials.
   Verify BOTH BRTI channels and genuine source/receipt timestamps.
   GitHub Actions secrets do not automatically copy to Oracle.
6. Obtain a domain and set its DNS A record to the VM public IP. Configure
   Caddy using Caddyfile.example (only after verifying DNS and 80/443).
   Verify the REAL public iPhone HTTPS page and /health,/api/state routes.

## Architecture and limits
AXIOM binds to localhost port 8000 with a single Uvicorn process. Its own
threads handle public Kalshi, Coinbase, settlement and optional signed BRTI.
The SQLite DB persists across reboots but NOT boot-volume deletion;
off-host encrypted backups still need configuration. Public read-only GET
data can be viewed by anyone with the HTTPS URL; manual simulated entries
and admin exports remain disabled with an empty token. NO real orders are
implemented, automatic paper entries are off. Live BRTI does not vote in
existing forecast probability. A healthy app does NOT establish trading
profitability, genuine exchange strike-publication timestamps, guaranteed
24/7 Oracle availability or fully validated real-world settlement accuracy.

NO billable resource, service, DNS domain, VM or deployment is created by
this repository preparation. No unrelated repository is touched.
