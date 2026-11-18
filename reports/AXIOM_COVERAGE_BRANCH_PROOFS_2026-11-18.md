# AXIOM — Statement and branch coverage disposition

**Scope:** `app/`, `phase0/`, `research/`, and `research_sources/`; Python 3.13 and Coverage.py 7.10.7 with `--branch`. This audit compares with frozen, passing source commit `6c3523452519ec3de1626c8bfa221bdd58f68e0e`. No production source, secret, real order, or deployment change is authorized or needed for this coverage exercise.

**Measurement from frozen baseline:** 1,781 executable statements, 9 not exercised; 654 branches, including 16 partial branch arcs; overall measured coverage **98.97330595482546%**. The measurement's total includes both statements and branch opportunities, so unexecuted statements alone do not explain its percentage.

## Individual disposition of every previously uncovered location

| File / uncovered location | Status | Evidence / test or proof |
|---|---|---|
| `app/engine.py:129->exit` | **Unreachable under validated control flow** | `len(closes)>=16` at line 127; each consecutive pair yields exactly one return, therefore `len(returns)>=15` and line 129 cannot be true. Retain guard; property assertions in `test_mathematical_invariants_that_make_redundant_guards_unreachable`. |
| `app/main.py:433->exit` | **Reachable; targeted** | Empty `ADMIN_TOKEN` must raise HTTP 403 without reaching ledger; `test_disabled_manual_paper_endpoint_rejects_without_writing_any_order`. |
| `app/orderbook.py:99` | **Unreachable after normalization** | Line 87 rejects `best_yes_bid+best_no_bid>1`. YES ask is `1-best_no_bid`; spread is `1-best_no_bid-best_yes_bid`, and likewise for NO. If one side absent, spread is `None`. Preserve redundant safety check; exhaustive cent-grid invariant. |
| `app/orderbook.py:158` | **Unreachable with valid normalized levels and positive request** | Each size is strictly positive; `0<requested<=100000`; `take=min(size,requested-filled)>0` while `filled<requested`; equality immediately breaks loop at line 164. The guard remains to reject inconsistent future refactors. |
| `app/settlement_research.py:88` | **Unreachable with prevalidated history** | At least 31 completed candles required before window selection; `window=last 61`; `len(returns)=len(window)-1>=30`. Retain guard; quantified invariant test. |
| `app/settlement_research.py:94` | **Reachable; targeted** | Exceptionally small but finite strike can overflow `close/strike` to infinity, making `z` nonfinite. Assert `UNAVAILABLE/WAIT`, not a false forecast; `test_research_shadow_extreme_finite_strike_abstains_on_nonfinite_z`. |
| `app/storage.py:113->exit` | **Reachable; targeted** | One seeded watch exists and is returned, then removed when first call locks; `test_sqlite_watch_and_snapshot_branches_with_multiple_officially_graded_rows`. A remaining CPython return-with-context-manager arc can be an instrumentation artifact; verify with fresh coverage output. |
| `app/storage.py:178->176` | **Reachable; targeted** | Multiple models, including allowed, disabled and no-probability engines, repeat the real snapshot loop; same SQLite test. |
| `app/storage.py:180->182` | **Reachable; targeted** | Unavailable ensemble must not create a snapshot; same SQLite test. |
| `app/storage.py:211->199` | **Reachable; targeted** | At least two officially graded rows; compare participant midpoints with and without available quotes; same SQLite test. |
| `phase0/verify_transfer.py:37->30` | **Reachable; targeted** | Missing frozen ZIP with `require_archives=False` only; stronger requirement still rejects missing archive; `test_provenance_optional_missing_archive_and_matching_external_archive`. |
| `phase0/verify_transfer.py:78->80` | **Reachable; targeted** | External legacy archive exactly matches signed manifest SHA-256; same test. |
| `research/reconcile_imported_fills.py:24-25` | **Reachable; targeted** | Malformed decimal strings for imported quantity, price and fees must be explicitly `INVALID_INPUT`, no verified profitability; `test_imported_record_decimal_parse_and_timestamp_type_fail_closed`. |
| `research/reconcile_imported_fills.py:33` | **Reachable; targeted** | Missing or numeric rather than UTC-offset datetime must fail closed; same test. |
| `research/verify_brti_backlog.py:73` | **Reachable; targeted** | More eligible settled markets than selected bound; inspector must stop after `limit=2` despite five candidates; `test_bounded_brti_history_inspector_stops_at_requested_limit`. Index reconciliation mocked only for this bounded-iteration unit case; separate earlier tests verify real reconstruction logic. |
| `research/verify_official_brti_live.py:66->exit` | **Reachable; targeted** | Nonlist, nondict values must yield no index ticks; `test_official_brti_walker_disregards_scalars_and_unrecognized_records`. |
| `research/verify_official_brti_live.py:110` | **Unreachable with current bounded interval enumeration** | Two 60-second reference windows each contribute only two endpoint timestamps, so there are no more than four UTC hour buckets in `hours`; `len(hours)>4` cannot occur. Retain the guard against future source changes; invariant test. |

**Rules for interpreting the outcome:** these are source-grounded program invariants, not absolute proof that every possible future refactor will preserve them. No `# pragma: no cover`, `# pragma: no branch`, artificial coverage exclusion, discarded test, or changed trading behavior is used. Some missing Python generator, loop, and return arcs may be instrumentation-specific; do not claim they are logically impossible unless supported by the program invariant. Only the actual subsequent CI logs may establish measured improvement. Full replay, provider acceptance, historical BRTI publication and authenticated net returns remain separate engineering/economic evidence categories.

**Verification gate:** run original 172 passing pytest cases plus this test file, all isolated adversarial checks, compilation, archive/regression tests, and the live read-only public provider smoke on the **same audit SHA**, with runtime warnings escalated to test failures. Preserve the verified baseline; do not merge or deploy.
