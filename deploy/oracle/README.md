# AXIOM Oracle deployment handoff — PREPARATION ONLY

## Source and status
Oracle prep ships with AXIOM's unified application implementation.
The verified integrated source checkpoint is 16e37f0660068a304c3e44980aef942c1b2cd3a6.
Its release candidate passed all six GitHub gates: complete offline regression
and full synthetic lifecycle, public Kalshi/Coinbase, genuine worker/full-depth,
authenticated BRTI 1Hz/5Hz, strict measured branch coverage and real Chromium
mobile/desktop acceptance. These are code/CI checks, NOT an Oracle deployment.
No real-money order routes were added; public market reads and manual
execution guidance remain read-only.

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

       git clone --depth 20 --branch main https://github.com/szmohmand/Axiom.git /tmp/axiom-deploy
       sudo bash /tmp/axiom-deploy/deploy/oracle/bootstrap.sh

   The bootstrap checks that this tested source checkpoint is an ancestor
   of the deployed code and that only approved installer files differ,
   installs pinned requirements and runs full offline regression,
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
implemented, automatic paper entries are off. The authenticated BRTI stream is not itself a directional
voting engine. The new BTC target-dynamics model can use its current index as
the distance reference when fresh; legacy engines still use Coinbase. A healthy app does NOT establish trading
profitability, genuine exchange strike-publication timestamps, guaranteed
24/7 Oracle availability or fully validated real-world settlement accuracy.

NO billable resource, service, DNS domain, VM or deployment is created by
this repository preparation. No unrelated repository is touched.

## Intra-contract resale lane
The integrated read-only worker tracks consecutive same-contract Kalshi full-depth
snapshots and actual elapsed observation intervals (never fabricates five-second
price paths). It reports midpoint/underlying changes, net price-level depth
changes, imbalance and rejection proxies. The separate movement-based watch
can flag YES or NO regardless of eventual contract result, but does not
predict a future exit quote or execute orders. A matching paper position gets
an instantaneous depth/illustrative-fee resale review; these are not actual
fills or profit. No perpetual funding endpoint is used.
The Oracle service environment requests a five-second poll interval; real
network latency may prevent exact five-second observations.

The pinned integrated source now includes verified read-only intracontract
resale, depth-level change, actual quote-timing history, paper exit review,
and a five-second requested polling interval. The installer must not deploy
an older candidate or modify live trading permissions.

## Binance spot lead and signed BTC trade flow (read-only)
The production lifespan starts ONE public-only Binance background worker:
BTCUSDT spot aggregate-trade WebSocket (exchange event and local receipt time).
It exposes genuine signed taker flow, CVD and unusually large trade prints.
No futures funding worker or mark/index funding endpoint is started.
The public spot worker needs no trading account or API key and cannot place
orders. Geographic blocking or stale timestamps results in UNAVAILABLE,
not a fabricated trade or lead signal. Only source-ordered Binance moves
followed by an actual Kalshi book receipt can create a quote-delay WATCH;
current full depth and after-fee hypothetical pricing inform an illustrative
BUY_CANDIDATE. This is NOT a validated execution edge; Binance BTCUSDT
is not the BRTI settlement benchmark.

## Binance read-only worker
For live operation, keep BINANCE_INTELLIGENCE_ENABLED=1. The Binance BTCUSDT
public spot WebSocket must be reachable from Oracle. A Binance move and Kalshi
quote need valid event/receipt ordering before the lag lane can alert.
No futures funding data is collected. If the Oracle region cannot reach
Binance, the spot-flow feature is UNAVAILABLE.
