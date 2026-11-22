"""BRTI-first forecasting end-to-end purity and missing-data tests."""
import math
from test_e2e_synthetic import env
from app.brti_candles import (completed_one_minute, completed_five_minute,
                              final_minute_prefix, completed_minute_sigma)
from app.brti_live import BRTITracker
from app.ensemble import engine_pack
from app.settlement_probability import forecast as settlement_forecast
from app.market_structure import timeframes


BASE = 1795046400000  # exact UTC minute


def tick(ts_ms, value):
    return {"type": "cfbenchmarks_value_5hz",
            "msg": {"index_id": "BRTI", "value_usd": str(value),
                    "source_ts_ms": ts_ms, "received_at": ts_ms + 20,
                    "data": "{}"}}


def sample_tracker(minutes=65):
    tracker = BRTITracker(enabled=True)
    tracker.mark(connected=True, subscribed="cfbenchmarks_value_5hz")
    for i in range(minutes * 60 + 10):
        stamp = BASE + i * 1000
        price = 64000 + i * .003 + math.sin(i / 100) * 1.5
        assert tracker.accept(tick(stamp, price), stamp + 40)
    return tracker


def test_real_received_index_samples_build_price_only_candles_and_live_frames():
    t = sample_tracker(130)
    end = BASE + (130 * 60 + 9) * 1000 + 40
    snap = t.snapshot(end)
    assert snap["status"] == "STREAMING"
    assert snap["price_candle_source"] == "cfbenchmarks_brti_authenticated_live"
    assert snap["candle_quality"]["missing_seconds_filled"] == 0
    bars = snap["btc_1m_candles"]
    assert len(bars) >= 62
    assert all(b["source"] == "cfbenchmarks_brti_authenticated_live" for b in bars)
    assert all(b["volume"] is None and b["observed_seconds"] == 60 for b in bars)
    assert bars[-1]["t"] + 60 <= end / 1000
    assert snap["completed_minute_sigma_45"] is not None
    five = snap["btc_5m_candles"]
    assert len(five)>=25, (len(bars),len(five),bars[0]['t'],bars[-1]['t'])
    assert all(bar["volume"] is None for bar in five)
    higher = timeframes(five, end / 1000)
    assert higher["available"] and higher["source"] == "cfbenchmarks_brti_authenticated_live"
    assert {"30m","1h","2h"} <= set(higher["frames"])


def test_missing_index_seconds_are_never_interpolated_or_counted_as_complete():
    samples = {BASE // 1000 + sec: 64000 + .1 * sec for sec in range(180)}
    first = completed_one_minute(samples, BASE / 1000 + 180)
    assert len(first) == 3
    for sec in range(60, 83):
        samples.pop(BASE // 1000 + sec)
    recovered = completed_one_minute(samples, BASE / 1000 + 180)
    assert len(recovered) == 1  # genuine contiguous suffix after a missing minute
    assert completed_five_minute(recovered) == []
    prefix = final_minute_prefix(samples, BASE / 1000 + 120, BASE // 1000 + 100)
    assert prefix["complete_prefix"] is False
    assert prefix["observed_mean_usd"] is None
    assert completed_minute_sigma(recovered) is None


def test_model_uses_authentic_index_and_reports_eighth_vote_separate_from_quotes():
    t=sample_tracker(65)
    now=(BASE + (65 * 60 + 9) * 1000 + 40) / 1000
    snapshot=t.snapshot(round(now * 1000))
    spot=float(snapshot["latest_value_usd"])
    candles=snapshot["btc_1m_candles"]
    market={"ticker":"KXBTC15M-BRTI", "target":spot+1,
            "seconds_left":480, "close_ts":now+480}
    context={"brti":snapshot,
             "timeframes":timeframes(snapshot["btc_5m_candles"], now),
             "microstructure":{}}
    result=engine_pack(spot,market,candles,context=context,now=now)
    assert result["available"]
    assert "axiom_brti_settlement" in result["active_predictive_models"]
    assert all(name not in result["active_predictive_models"]
               for name in ("kalshi_market", "coinbase_market", "binance_market"))
    assert result["method"]=="experimental-equal-weight-mean-consensus"
    changed=engine_pack(spot,{**market,"yes_ask":.99,"no_bid":.01,
                              "market_mid":.99,"volume":1e9},
                        candles,context=context,now=now)
    assert changed["prob_above"] == result["prob_above"]
    boosted=next(x for x in result["engines"] if x["name"]=="axiom_gradient_boosted_btc")
    assert boosted["available"]


def test_settlement_model_final_minute_uses_actual_received_prefix_not_only_last_price():
    close=BASE/1000+900
    market={"ticker":"KXBTC15M-BRTI", "target":64050, "close_ts":close}
    now=close-30
    brti={"status":"STREAMING", "authenticated_stream_verified":True,
          "latest_value_usd":"64010", "source_ts_ms":int(now*1000),
          "axiom_received_at_ms":int(now*1000)+25,
          "completed_minute_sigma_45":.001,
          "settlement_window_stats":{"window_end_ts":close,
              "complete_prefix":True,"observed_seconds":30,
              "expected_seconds":30,"observed_mean_usd":64090}}
    prob=settlement_forecast(market,brti,[],now)
    assert prob["available"] and prob["observed_final_minute_seconds"]==30
    assert abs(prob["estimated_final_mean_usd"]-64050)<.01
    assert abs(prob["prob_above"]-.5)<.01
    brti["settlement_window_stats"]["complete_prefix"]=False
    assert not settlement_forecast(market,brti,[],now)["available"]
    brti["status"]="STALE"
    assert not settlement_forecast(market,brti,[],now)["available"]


def test_live_brti_warmup_keeps_server_operational_but_blocks_predictions_and_paper(env, monkeypatch):
    # Real authenticated reference, but <31 completed BRTI candles since start.
    main,clock,provider,client,_=env
    main.DEMO=False
    clock.now=provider.close-600
    candles=provider.candles()[-12:]
    for b in candles:
        b["source"]="cfbenchmarks_brti_authenticated_live"
        b["volume"]=None
    sample={
        "status":"STREAMING", "authenticated_stream_verified":True,
        "latest_value_usd":"90325.0",
        "source_ts_ms":int(clock.now*1000),
        "axiom_received_at_ms":int(clock.now*1000)+10,
        "btc_1m_candles":candles,"btc_5m_candles":[],
        "candle_quality":{"status":"WARMING_BRTI_LIVE","bars_used":12,
                          "missing_seconds_filled":0},
    }
    monkeypatch.setattr(main.brti_tracker,"snapshot",lambda now_ms=None:sample)
    def forbidden(*args,**kwargs):
        raise AssertionError("Forbidden Coinbase access during live BRTI warmup")
    provider.price=forbidden
    provider.candles=forbidden
    provider.timeframe_candles=forbidden
    out=main.update_once()
    assert out["status"]=="LIVE" and out["ok"] is True
    assert out["price_source"]=="CF_BENCHMARKS_BRTI"
    assert out["forecast_warming"] is True
    assert out["model"]["available"] is False
    assert out["opportunity"]["side"]=="WAIT"
    assert out["execution_intelligence"]["order_placed"] is False
    assert client.get('/health').status_code==200
    state=client.get('/api/state')
    assert state.status_code==200
    assert state.json()["manual_paper_available"] is False
    auth={"Authorization":"Bearer synthetic-local-testing-token"}
    assert client.post('/api/paper',json={"side":"YES"},headers=auth).status_code==409
    assert main.ledger.data()['count']=={'calls':0,'paper':0}


def test_phase2_without_constituent_flow_waits_and_does_not_trade(env, monkeypatch):
    from app.orderbook import normalize_orderbook
    main, clock, provider, client, _ = env
    main.DEMO = False
    main.AUTO_PAPER = True
    clock.now = provider.close - 450
    market = provider.market(clock.now)
    bars = provider.candles()
    for b in bars:
        b["source"] = "cfbenchmarks_brti_authenticated_live"
        b["volume"] = None
    snapshot = {
        "status": "STREAMING", "authenticated_stream_verified": True,
        "latest_value_usd": market["target"] + 325,
        "source_ts_ms": int(clock.now * 1000),
        "axiom_received_at_ms": int(clock.now * 1000),
        "btc_1m_candles": bars, "btc_5m_candles": [],
        "completed_minute_sigma_45": .001,
        "candle_quality": {"status": "FULL_BRTI_LIVE", "bars_used": len(bars)},
    }
    monkeypatch.setattr(main.brti_tracker, "snapshot", lambda now_ms=None: snapshot)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Removed source/ensemble accessed by live path")
    provider.price = forbidden
    provider.candles = forbidden
    provider.timeframe_candles = forbidden
    monkeypatch.setattr(main, "engine_pack", forbidden)
    monkeypatch.setattr(main, "derive_signals", forbidden)
    def real_book(contract, now=None):
        return normalize_orderbook({"orderbook_fp": {
            "yes_dollars": [["0.25", "50"]],
            "no_dollars": [["0.70", "50"]]}}, contract["ticker"], clock.now)
    provider.orderbook = real_book
    updated = main.update_once()
    assert updated["ok"] and updated["status"] == "LIVE"
    assert updated["price_source"] == "CF_BENCHMARKS_BRTI"
    assert updated["model"]["available"]
    assert updated["model"]["method"] == "single-axiom-brain-brti-student-t"
    assert [e["name"] for e in updated["engines"]] == ["axiom_brti_settlement"]
    assert updated["opportunity"]["side"] == "WAIT"
    assert updated["trade_decision"]["action"] == "WAIT"
    assert updated["execution_intelligence"]["order_placed"] is False
    assert main.ledger.data()["count"]["paper"] == 0



def test_phase2_signed_taker_flow_sustained_two_usd_venues():
    from app.axiom_brain import ConstituentFlow
    flow = ConstituentFlow()
    for step in range(45):
        now = 1000 + step
        if step == 0:
            flow.ingest("coinbase", {"type": "snapshot", "product_id": "BTC-USD",
                        "bids": [["100", "10"]], "asks": [["101", "10"]]}, now)
            flow.ingest("kraken", {"channel": "book", "type": "snapshot",
                        "data": [{"symbol": "BTC/USD", "bids": [{"price": 100, "qty": 10}],
                                  "asks": [{"price": 101, "qty": 10}]}]}, now)
        else:
            flow.ingest("coinbase", {"type": "l2update", "product_id": "BTC-USD",
                        "changes": [["buy", "100", str(10+step)]]}, now)
            flow.ingest("kraken", {"channel": "book", "type": "update",
                        "data": [{"symbol": "BTC/USD",
                                  "bids": [{"price": 100, "qty": 10+step}],
                                  "asks": []}]}, now)
        flow.ingest("coinbase", {"type": "match", "product_id": "BTC-USD",
                    "trade_id": step, "side": "sell", "size": "0.2"}, now)
        flow.ingest("kraken", {"channel": "trade", "type": "update",
                    "data": [{"symbol": "BTC/USD", "trade_id": step,
                              "side": "buy", "qty": 0.3}]}, now)
    snap = flow.snapshot(1044)
    assert snap["available"]
    assert snap["confirmed_direction"] == "UP"
    assert snap["cvd_30"] > 0 and snap["cvd_60"] > 0
    assert snap["cvd_180"] >= snap["cvd_60"] > 0  # 45s observed: both include all trades
    assert snap["ofi_30"] > 0 and snap["ofi_60"] > 0
    flow.reset("coinbase")
    assert not flow.snapshot(1044)["available"]


def test_phase2_student_t_is_symmetric_and_heavier_tailed():
    from app.settlement_probability import _student_t_cdf, NU
    assert NU == 4.5
    assert abs(_student_t_cdf(0)-.5) < 1e-12
    assert abs(_student_t_cdf(-2) - (1-_student_t_cdf(2))) < 1e-10
    assert _student_t_cdf(-4) > .0001


def test_phase2_compression_breakout_student_t_and_macro_kill(monkeypatch):
    from app.axiom_brain import decide
    from app.brti_candles import completed_five_minute
    from app.orderbook import normalize_orderbook
    import math
    base = 1800000000  # 03:00 ET, outside macro and TWAP windows
    now = base + 65*60 + 1
    bars = []
    for i in range(65):
        t = base+i*60
        if i < 54:
            price = 100+.35*math.sin(i*.7)
            bar = {"t":t,"open":price-.06,"close":price,
                   "high":price+.10,"low":price-.10}
        elif i < 64:
            bar = {"t":t,"open":100.,"close":100.,
                   "high":100.02,"low":99.98}
        else:
            bar = {"t":t,"open":100.,"close":100.4,
                   "high":100.42,"low":99.99}
        bars.append({**bar,"source":"cfbenchmarks_brti_authenticated_live",
                     "volume":None})
    five = completed_five_minute(bars)
    market = {"ticker":"KXBTC15M-PHASE2","target":100.48,
              "close_ts":now+450,"seconds_left":450}
    brti = {"status":"STREAMING","authenticated_stream_verified":True,
            "latest_value_usd":"100.4","source_ts_ms":int(now*1000),
            "axiom_received_at_ms":int(now*1000),
            "completed_minute_sigma_45":.001,"brti_sigma_5s_3m":.0006}
    book = normalize_orderbook({"orderbook_fp":{
            "yes_dollars":[["0.30","10"]],"no_dollars":[["0.68","10"]]}},
            market["ticker"],now)
    flow = {"available":True,"confirmed_direction":"UP",
            "CVD_norm_90s":.5,"cvd_90s_span":85,
            "trade_count_90s":80,"taker_buy_share_90s":.75,
            "taker_sell_share_90s":.25,
            "depth_depletion":{"coinbase":{
                "bid":{"ratio_to_normal":.7,"below_half_for_15s":False},
                "ask":{"ratio_to_normal":.7,"below_half_for_15s":False}}},
            "delta_venue":None,"delta_venue_pct":None,
            "synthetic_price":None,"OBI_spot":.3,"D_spot":50}
    class Tape:
        def snapshot(self, *_):
            return {"implied_sigma_quartile_24h":.003,
                    "implied_history_ready":True,"mid_jump_20s":0}
    signal = decide(market,brti,bars,five,book,flow,now,tape=Tape())
    assert signal["action"] == "BUY_YES", signal
    assert signal["setup_type"] == "COMPRESSION_BREAKOUT"
    assert signal["entry_price"] == .32
    assert signal["fair_prob_side"] == "YES"
    assert signal["take_profit"] == max(.60,min(.85,signal["fair_prob"]))
    assert signal["invalidation_rule"]["type"] == "BRTI_CLOSE_BACK_INSIDE_RANGE"
    assert signal["kill_switch_triggered"] is False
    assert decide(market,brti,bars,five,book,{**flow,"available":False},now,tape=Tape())["action"] == "WAIT"
    # Cold start never bypasses IV: a real BRTI-derived ceiling substitutes
    # for the unavailable 24h observed Kalshi bottom-quartile threshold.
    from app import axiom_brain
    class ColdTape:
        def snapshot(self, *_):
            return {"implied_sigma_quartile_24h": None,
                    "implied_history_ready": False, "mid_jump_20s": 0}
    monkeypatch.setattr(axiom_brain, "_implied_minute_sigma",
                        lambda *args: .0004)
    allowed = decide(market,brti,bars,five,book,flow,now,tape=ColdTape())
    assert allowed["action"] == "BUY_YES", allowed
    assert allowed["iv_guard"] == "cold_start_ceiling"
    assert 0 < allowed["iv_ceiling_1m"] <= .0012
    assert allowed["details"]["iv_guard"] == "cold_start_ceiling"
    monkeypatch.setattr(axiom_brain, "_implied_minute_sigma",
                        lambda *args: .002)
    blocked = decide(market,brti,bars,five,book,flow,now,tape=ColdTape())
    assert blocked["action"] == "WAIT"
    assert blocked["iv_guard"] == "cold_start_ceiling"
    assert blocked["implied_sigma_1m"] > blocked["iv_ceiling_1m"]


def test_phase2_twap_drift_sweep_fade_and_read_only_time_stop():
    from app.axiom_brain import decide
    from app.brti_candles import completed_five_minute
    from app.orderbook import normalize_orderbook
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from math import sin
    et = ZoneInfo("America/New_York")
    now = datetime(2026,11,23,10,30,5,tzinfo=et).timestamp()
    base = int(now//60)*60 - 65*60
    bars = [{"t":base+i*60,"open":100+.02*sin(i),"high":100.1,
             "low":99.9,"close":100+.02*sin(i),
             "source":"cfbenchmarks_brti_authenticated_live","volume":None}
            for i in range(65)]
    five = completed_five_minute(bars)
    market = {"ticker":"KXBTC15M-TWAP","target":100.,
              "close_ts":now+450,"seconds_left":450}
    brti = {"status":"STREAMING","authenticated_stream_verified":True,
            "latest_value_usd":"100.04","source_ts_ms":int(now*1000),
            "axiom_received_at_ms":int(now*1000),
            "completed_minute_sigma_45":.001}
    book = normalize_orderbook({"orderbook_fp":{
            "yes_dollars":[[".32","10"]],"no_dollars":[[".66","10"]]}},
            market["ticker"],now)
    flow = {"available":True,"CVD_norm_5m":.55,"rho_trade":.35,
            "cvd_5m_span":285,"delta_venue":None,
            "delta_venue_pct":None,"synthetic_price":None}
    out = decide(market,brti,bars,five,book,flow,now)
    assert out["action"] == "BUY_YES",out
    assert out["setup_type"] == "US_SESSION_TWAP_DRIFT"
    assert out["invalidation_rule"]["type"] == "BRTI_STRIKE_BAND_OR_CVD_FLIP"
    # TWAP remains eligible with 36 real BRTI candles while 60m regime
    # buffers are warming; Student-t fair value has its own shorter minimum.
    twap_warm = decide(market,brti,bars[-36:],
                       completed_five_minute(bars[-36:]),book,flow,now)
    assert twap_warm["action"] == "BUY_YES",twap_warm
    assert twap_warm["regime"] == "WARMING"
    # Macro windows suppress a nominally identical otherwise-qualified signal.
    macro_now = datetime(2026,11,23,10,0,0,tzinfo=et).timestamp()
    macro_brti = {**brti,"source_ts_ms":int(macro_now*1000),
                  "axiom_received_at_ms":int(macro_now*1000)}
    macro = decide({**market,"close_ts":macro_now+450},
                   macro_brti,bars,five,book,flow,macro_now)
    assert macro["action"] == "WAIT" and macro["kill_switch_triggered"]
    end = decide({**market,"close_ts":now+120},
                 brti,bars,five,book,{**flow,"CVD_norm_60s":-.3},
                 now,open_side="YES")
    assert end["action"] == "WAIT" and end["kill_switch_triggered"]
    assert end["exit_signal"]["action"] == "SELL_CANDIDATE"
    assert end["exit_signal"]["reason"] == "CVD_SIGN_FLIP"
    assert end["exit_signal"]["paper_execution_performed"] is False

    # Outside the institutional TWAP window, a persistent one-venue
    # depletion after an aggressive quote jump can qualify as a fade.
    after = datetime(2026,11,23,12,0,5,tzinfo=et).timestamp()
    fade_market = {**market,"close_ts":after+450}
    fade_brti = {**brti,"latest_value_usd":"100.",
                 "source_ts_ms":int(after*1000),
                 "axiom_received_at_ms":int(after*1000)}
    fade_book = normalize_orderbook({"orderbook_fp":{
            "yes_dollars":[[".70","10"]],"no_dollars":[[".27","10"]]}},
            market["ticker"],after)
    fade_flow = {**flow,"delta_venue":.12,"delta_venue_pct":.0012,
                 "synthetic_price":100.,"outlier_venue":"coinbase",
                 "venue_midpoints":{"coinbase":100.12,"kraken":100.,
                                    "bitstamp":99.98},
                 "depth_depletion":{"coinbase":{
                     "ask":{"below_half_for_15s":True,"ratio_to_normal":.4}}}}
    class FadeTape:
        def snapshot(self,*_):
            return {"mid_jump_20s":.2}
    fade = decide(fade_market,fade_brti,bars,five,fade_book,
                  fade_flow,after,tape=FadeTape())
    assert fade["action"] == "WAIT"  # old BRTI candles are stale; no fake signal
    shifted = [{**bar,"t":bar["t"]+int(after-now)} for bar in bars]
    fresh = decide(fade_market,fade_brti,shifted,
                   completed_five_minute(shifted),fade_book,
                   fade_flow,after,tape=FadeTape())
    assert fresh["action"] == "BUY_NO",fresh
    assert fresh["setup_type"] == "SINGLE_VENUE_SWEEP_FADE"
    assert fresh["entry_price"] == .30
    assert fresh["take_profit"] == max(.60,min(.85,fresh["fair_prob"]))
    fade_warm = decide(fade_market,fade_brti,shifted[-36:],
                       completed_five_minute(shifted[-36:]),fade_book,
                       fade_flow,after,tape=FadeTape())
    assert fade_warm["action"] == "BUY_NO",fade_warm
    assert fade_warm["regime"] == "WARMING"



def test_phase2_paper_position_lookup_does_not_write_or_change_trade_state(env):
    main, clock, provider, _, _ = env
    market = provider.market(clock.now)
    main.ledger.trade(market, "YES", clock.now, source="PHASE2_READONLY")
    conn = main.ledger.conn
    before = [tuple(row) for row in conn.execute("SELECT * FROM paper_trades")]
    changed = conn.total_changes
    first = main.ledger.open_paper(market["ticker"])
    assert first["side"] == "YES" and first["entry"] == market["yes_ask"]
    first["side"] = "NO"  # Mutating a returned copy cannot alter SQLite.
    assert main.ledger.open_paper(market["ticker"])["side"] == "YES"
    assert main.ledger.open_paper("KXBTC15M-UNKNOWN") is None
    assert conn.total_changes == changed
    assert [tuple(row) for row in conn.execute("SELECT * FROM paper_trades")] == before
