# AXIOM Nison candlestick first-100 experiment: isolated sidecar

This experiment does NOT update, restart, deploy or merge the running AXIOM
service at `/opt/axiom/current`. No cloud resources or public network ports
are provisioned. The single new process reads its existing localhost HTTP
`/api/state` snapshots. The sidecar itself makes **no external API calls** and
has no credentials or order functions.

## Safety model

- Source: `szmohmand/Axiom`, isolated branch
  `feature/axiom-nison-candle-challenger-2026-11-22`.
- Working tree: `/opt/axiom/candle-study`, distinct from the active
  `/opt/axiom/current`. No merge to main.
- `axiom-candle-study.service` runs as the existing system user `axiom`,
  localhost only. It writes to its own `/var/lib/axiom-candle-study/study.sqlite3`
  and never opens the live `bot.sqlite3` for writing. No auto-paper or real orders.
- It excludes the contract active when the collector first starts (warmup), then
  enrolls the first 100 subsequently encountered KXBTC15M contracts.
- For each enrolled ticker, it attempts observations near the **14m, 10m,
  5m and 1m remaining** checkpoints. It records the existing probability and
  candlestick candidate probability at the **same live timestamp**.
- On no candlestick setup / unavailable valid candle data, the candidate is
  exactly the existing ensemble probability. Such contracts are **retained**
  in the cohort so selection is not biased by attractive candle patterns.
- Each checkpoint is immutable (first eligible observation wins) and never
  backfilled from future bars. Missing/stale snapshots are skipped, not made up.
- The report reads Kalshi's officially settled result from the **existing
  AXIOM ledger in read-only SQLite mode**. Those results are the live bot's
  source grades and have not been separately re-audited against BRTI.
- Compare Brier and logloss at matched checkpoints. Negative
  challenger-minus-baseline Brier is an improvement. Also assess how many of
  the 100 contracts and checkpoint observations are actually graded.
- A 100-contract sample does NOT prove a statistically reliable or profitable
  strategy. Do not enable an ensemble vote or real-money trading on its own.

## Prerequisites

Verify that an Oracle Ubuntu VM and the existing read-only AXIOM service
**actually exist**, and that `systemctl is-active axiom` prints `active`.
If there is no VM or the baseline has an outage, stop. Do not create a new VM,
upgrade an OCI account, overwrite the live installation or replace the service.

The following is a **manual** operation on the existing VM: neither GitHub
Actions nor this file can run Oracle console actions on your behalf.

```bash
sudo git clone --depth 1 --branch feature/axiom-nison-candle-challenger-2026-11-22 https://github.com/szmohmand/Axiom.git /opt/axiom/candle-study
sudo cp /opt/axiom/candle-study/deploy/oracle/axiom-candle-study.service /etc/systemd/system/axiom-candle-study.service
sudo systemctl daemon-reload
sudo systemctl enable --now axiom-candle-study
sudo systemctl status axiom-candle-study --no-pager
```

These commands install **only the isolated candlestick collector** and do
not restart the existing `axiom` service. Verify the source revision with
`git -C /opt/axiom/candle-study rev-parse HEAD` against the latest GitHub
Actions passing commit before enabling the new collector.

## Examine progress

```bash
sudo journalctl -u axiom-candle-study -n 30 --no-pager
cd /opt/axiom/candle-study
sudo -u axiom /usr/bin/python3 -m research.candlestick_shadow_study report
```

This report is local to the server and has no web/UI exposure. It can be run
while the collector is collecting, but full results require 100 enrolled and
100 officially settled contracts. The same script includes the count of missing
checkpoint observations and signal coverage; do not silently substitute
unobserved data.

## Stop study without modifying the live AXIOM bot

```bash
sudo systemctl disable --now axiom-candle-study
```

The study SQLite remains in `/var/lib/axiom-candle-study` for inspection;
do not delete historical results automatically.
