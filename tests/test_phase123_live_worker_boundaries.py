"""Isolated Phase 3 live worker state, ledger and warmup failure boundaries."""
from types import SimpleNamespace

import pytest

from app.orderbook import normalize_orderbook
from test_e2e_synthetic import env


def _stream(clock, provider, **replacements):
    data={"status":"STREAMING","authenticated_stream_verified":True,
          "latest_value_usd":"90325.",
          "source_ts_ms":int(clock.now*1000),
          "axiom_received_at_ms":int(clock.now*1000),
          "btc_1m_candles":provider.candles()[-36:],
          "btc_5m_candles":[],
          "brti_sigma_5s_3m":None,
          "candle_quality":{"status":"WARMING_BRTI_LIVE","bars_used":0}}
    return {**data,**replacements}


def _book(m,now):
    return normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[[".33","20"]],"no_dollars":[[".65","20"]]}},
        m["ticker"],now)


def _decision(action="WAIT",**changes):
    side="YES" if action=="BUY_YES" else "NO" if action=="BUY_NO" else None
    base={"action":action,"side":side,
          "setup_type":"US_SESSION_TWAP_DRIFT" if side else "NONE",
          "fair_prob":.92 if side else None,
          "prob_above":.92,"prob_below":.08,
          "forecast_available":True,"model_method":"test_authenticated_brti_t",
          "reason":"mock authenticated BRTI valuation",
          "entry_price":.35 if side else None,
          "take_profit":.75 if side else None,
          "invalidation_rule":{"type":"BRTI_STRIKE_BAND_OR_CVD_FLIP",
                                "strike":90000.,"max_deviation_bps":12} if side else None,
          "kill_switch_triggered":False,"order_placed":False,"read_only":True,
          "exit_signal":None}
    return {**base,**changes}


@pytest.fixture
def live(env,monkeypatch):
    main,clock,provider,client,_=env
    main.DEMO=False
    main.AUTO_PAPER=False
    clock.now=provider.close-450
    monkeypatch.setattr(main.brti_tracker,"snapshot",
                        lambda now_ms=None:_stream(clock,provider))
    monkeypatch.setattr(main.flow_tracker,"snapshot",lambda now:{
        "available":False,"venues":[],"CVD_norm_60s":0.,
        "cvd_60_span":0,"cvd_90s_span":0,"cvd_5m_span":0})
    provider.orderbook=lambda market,now=None:_book(market,clock.now)
    monkeypatch.setattr(main,"axiom_decide",lambda *_a,**_k:_decision())
    return main,clock,provider,client


def test_live_api_stream_startup_and_unavailable_market(live,monkeypatch):
    main,clock,provider,client=live
    first=main.update_once()
    assert first["status"]=="LIVE"
    assert first["warmup"]["status"]=="WARMING"
    assert first["model"]["available"]
    assert first["trade_decision"]["order_placed"] is False
    assert first["paper_exit"] is None
    assert client.get("/api/state").json()["ledger_available"] is True
    monkeypatch.setattr(provider,"market",lambda *_:None)
    bad=main.update_once()
    assert bad["status"]=="DEGRADED" and "kalshi" in bad["errors"]
    assert bad["trade_decision"]["action"]=="WAIT"


def test_bad_stream_and_book_unavailability_fail_closed(live,monkeypatch):
    main,clock,provider,_=live
    monkeypatch.setattr(main.brti_tracker,"snapshot",
                        lambda now_ms=None:_stream(clock,provider,status="STALE"))
    bad=main.update_once()
    assert bad["status"]=="DEGRADED"
    assert "brti_stream" in bad["errors"]
    monkeypatch.setattr(main.brti_tracker,"snapshot",
                        lambda now_ms=None:_stream(clock,provider,latest_value_usd="nan"))
    bad=main.update_once()
    assert "brti_stream" in bad["errors"]
    attempts={"n":0}
    def raise_invalid(**_kw):
        attempts["n"]+=1
        if attempts["n"]==1:
            raise ValueError("bad BRTI snapshot")
        return _stream(clock,provider)
    monkeypatch.setattr(main.brti_tracker,"snapshot",raise_invalid)
    bad=main.update_once()
    assert "brti_stream" in bad["errors"]
    monkeypatch.setattr(main.brti_tracker,"snapshot",
                        lambda now_ms=None:_stream(clock,provider))
    def raise_market(*_a):
        raise ConnectionError("kalshi offline")
    monkeypatch.setattr(provider,"market",raise_market)
    bad=main.update_once()
    assert "kalshi" in bad["errors"]


def test_book_error_does_not_invent_liquidity_or_orders(live,monkeypatch):
    main,clock,provider,_=live
    def no_book(*_args,**_kwargs):
        raise TimeoutError("public depth unavailable")
    provider.orderbook=no_book
    state=main.update_once()
    assert state["orderbook"]["available"] is False
    assert state["execution_intelligence"]["order_placed"] is False
    assert main.ledger.data()["count"]["paper"]==0


def test_forecast_exception_and_paper_read_failure_do_not_crash(live,monkeypatch):
    main,clock,provider,_=live
    def fail_decision(*_args,**_kwargs):
        raise ValueError("invalid transient model")
    monkeypatch.setattr(main,"axiom_decide",fail_decision)
    bad=main.update_once()
    assert "forecast" in bad["errors"]
    monkeypatch.setattr(main,"axiom_decide",lambda *_a,**_k:_decision())
    def fail_position(*_):
        raise RuntimeError("ledger unavailable")
    monkeypatch.setattr(main.ledger,"open_paper",fail_position)
    bad=main.update_once()
    assert "ledger_write" in bad["errors"]


def test_one_contract_paper_auto_entry_and_early_close_during_warmup(live,monkeypatch):
    main,clock,provider,_=live
    main.AUTO_PAPER=True
    monkeypatch.setattr(main,"axiom_decide",lambda *_a,**_k:_decision("BUY_YES"))
    opened=main.update_once()
    assert opened["trade_decision"]["order_placed"] is False
    row=main.ledger.open_paper(provider.ticker)
    assert row is not None
    assert row["take_profit"]==.75
    assert row["invalidation_rule"]["type"]=="BRTI_STRIKE_BAND_OR_CVD_FLIP"
    assert main.ledger.data()["count"]["paper"]==1
    clock.now+=5
    provider.orderbook=lambda market,now=None: normalize_orderbook(
        {"orderbook_fp":{"yes_dollars":[[".80","10"]],
                         "no_dollars":[[".15","10"]]}},market["ticker"],clock.now)
    closed=main.update_once()
    assert closed["paper_exit"]["exit_reason"]=="TAKE_PROFIT"
    assert closed["paper_exit"]["exit_price"]==.8
    assert closed["trade_decision"]["action"]=="WAIT"
    assert main.ledger.data()["count"]["paper"]==1
    assert main.ledger.open_paper(provider.ticker) is None


def test_ledger_write_failure_keeps_live_entry_disabled(live,monkeypatch):
    main,clock,provider,_=live
    monkeypatch.setattr(main,"axiom_decide",lambda *_a,**_k:_decision("BUY_YES"))
    def fail(*_args,**_kwargs):
        raise OSError("disk write failed")
    monkeypatch.setattr(main.ledger,"observed",fail)
    bad=main.update_once()
    assert "ledger_write" in bad["errors"]
    assert bad["trade_decision"]["action"]=="WAIT"
    assert main.ledger.data()["count"]["paper"]==0


def test_stale_state_and_worker_status_are_not_reported_healthy(live,monkeypatch):
    main,clock,provider,client=live
    first=main.update_once()
    with main.state_lock:
        main.state["last_attempt"]=clock.now-1000
        view=main._view_locked(clock.now)
    assert not view["ok"]
    assert "worker_stale" in view["errors"]
    assert view["trade_decision"]["action"]=="WAIT"
    with main.state_lock:
        main.state["errors"]["worker"]="worker disconnected"
        main._refresh_status_locked()
        assert main.state["status"]=="ERROR"
        main.state["errors"].pop("worker")
