# AXIOM Phase 0 — reusable code inventory (source-preserving)

Every copied file has a SHA-256 in `transfer_manifest.json`. Only the **v2 ZIP** is the source of the new baseline; v1 is archived as provenance, not merged.

| Source file(s) | Existing functionality | Reuse status | Dependencies | Important qualification |
|---|---|---|---|---|
| `app/engine.py` | AXIOM volatility forecast and separate spot scalp lens | TRANSFERRED IDENTICAL | Python stdlib | Uncalibrated/proxy-based |
| `app/ensemble.py` | Three experimental engines, consensus and opportunity screening | TRANSFERRED IDENTICAL | Python stdlib + `app.engine` | Two external method adaptations; not full upstream bots |
| `app/feeds.py` | Kalshi public markets and Coinbase spot/candle adapters; demo data | TRANSFERRED IDENTICAL | `requests` | Coinbase is not CF BRTI ground truth |
| `app/main.py` | HTTP routes, scheduler, paper workflows | TRANSFERRED IDENTICAL | FastAPI, requests, local modules | No live order placement; demo configured for tests |
| `app/storage.py` | SQLite ledger, immutable engine snapshots, official-result scoring | TRANSFERRED IDENTICAL | sqlite3 stdlib | Paper outcomes are synthetic in demo mode |
| `app/static/index.html` | Mobile-oriented research dashboard | TRANSFERRED IDENTICAL | browser; local app routes | Not a live-verified trading interface |
| `tests/test_app.py`, `test_engine.py`, `test_ledger.py`, `test_ensemble_v2.py` | Source-provided offline tests (19 total) | 18 other assertions/source tests original; `test_app.py` amended to pin demo clock | pytest, FastAPI | Original test SHA retained in manifest; no live/API test |
| `research_sources/full_catalog.json`, `full_catalog.csv` | Research candidate reference catalog | TRANSFERRED IDENTICAL | file readers | Catalog entries not imported into runtime |
| `research_sources/collect_sources.py` | Optional source-snapshot collector | TRANSFERRED IDENTICAL | stdlib `zipfile`, requests (see imports) | Not run by CI or AXIOM startup |
| `README.md`, `THIRD_PARTY_NOTICES.md`, `LICENSE`, `TEST_REPORT.md`, `requirements.txt`, `.env.example` | Documentation and dependency provenance | TRANSFERRED IDENTICAL | none | `.env.example` has placeholder only; no secret values |
| `.gitignore` | Original v2 ignores were weaker for credential/data hygiene | INTENTIONALLY REPLACED | none | Original hash preserved in legacy ZIP |
| `render.yaml`, `Procfile`, `run_demo.sh` | Legacy execution and deployment recipes | **NOT MIGRATED** | Hosted Python/Persistent disk | No live/cloud infra in Phase 0 |
| Secrets, private keys, `.env`, SQLite ledgers, CI tokens | Not in source transfer | **NEVER MIGRATE** | n/a | Must be provisioned separately in future approved deployments |

## Newly reviewed external candidates — references only

The earlier research reviewed publicly accessible projects including `sarthak-p/Kalshi-BTC-Dashboard` (order-flow), `kzenith2019/kalshi-btc-bot` (volatility), `reedjacobp/kalshi-trading-bot` (slippage), `masonlancellotti/crypto-contract-backtesting-system` (holdout testing), `Charlesganu2004/kalshi-15m-backtester` (fee-aware simulation), and `SiddhaBasu/kalshi-bot` (probability model/whale scanner). **No executable files from those repositories are copied into this Phase 0 transfer.** Their license statuses vary; no assumption of unrestricted redistribution is made.

## Dependency and secret findings

- Python requirements in source: `fastapi>=0.115,<1`, `uvicorn>=0.30,<1`, `requests>=2.31,<3`; tests require pytest.
- Source imports include `fastapi`, `pydantic`, `requests`, `pytest`, plus Python standard-library modules.
- Data: public Kalshi endpoints, Coinbase public feeds, SQLite; optional GitHub public-source collection.
- No source-controlled `.env` values, private key files, or credential-bearing databases copied.
- Pattern-based static scan found no candidates in the transferred text files. Static scanning is not a mathematical guarantee, and raw archives are preserved rather than silently modified.
- Locked dependency versions for Python 3.13 are in `requirements.lock.txt`; these pins were derived from the available runtime, not independently resolved against PyPI in this offline environment.
