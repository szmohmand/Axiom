# AXIOM v2 test report — November 15, 2026

- 19 local automated tests passed via `python -m pytest -q`.
- Source inputs inspected using the GitHub connected public repository reader; no writes to the user's GitHub.
- Integration: three experimental model estimates, one Kalshi baseline, median ensemble, opportunity screen, official-outcome snapshot scorekeeping.
- Automated and manual paper trading remain simulated only.
- Public Kalshi/Coinbase live-read smoke test: **not performed**; the container cannot reach external network services.
- Cloud production deployment: **not performed**.
- Statistical forecast validation: **not established**; the scorecards begin empty and must collect future outcomes.

See `README.md` and `THIRD_PARTY_NOTICES.md` for provenance and limits.
