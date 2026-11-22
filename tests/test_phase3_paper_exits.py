"""Phase 3: paper exits, settlement accounting and restart warmup."""
import math
import sqlite3

from app.axiom_brain import ConstituentFlow
from app.brti_live import BRTITracker
from app.orderbook import normalize_orderbook
from app.paper_exits import evaluate_exit
from app.storage import Ledger
from test_e2e_synthetic import env


def contract(ticker="KXBTC15M-P3", ask=.32, close=1600.):
    return {"ticker": ticker, "seconds_left": 400, "close_ts":close,
            "yes_ask":ask, "no_ask":.72}


def book_for(ticker, yes_bid, no_bid, now):
    return normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[[str(yes_bid),"10"]],
        "no_dollars":[[str(no_bid),"10"]]}},ticker,now)


def reference(now, spot=64000.):
    return {"status":"STREAMING","authenticated_stream_verified":True,
            "latest_value_usd":str(spot),"source_ts_ms":int(now*1000),
            "axiom_received_at_ms":int(now*1000)}


def test_phase3_take_profit_exit_is_exactly_once_net_and_settlement_safe(tmp_path):
    path=tmp_path/"paper.sqlite3"
    led=Ledger(str(path))
    market=contract()
    rule={"type":"BRTI_CLOSE_BACK_INSIDE_RANGE","direction":"UP",
          "level_usd":63900}
    led.trade(market,"YES",1000,source="AUTO_PAPER",
              take_profit=.60,invalidation_rule=rule)
    position=led.open_paper(market["ticker"])
    assert position["invalidation_rule"]==rule
    bidbook=book_for(market["ticker"],.64,.30,1200)
    instruction=evaluate_exit(position,market,reference(1200),[],
                               bidbook,{},1200)
    assert instruction["exit_reason"]=="TAKE_PROFIT"
    result=led.close_paper(market["ticker"],instruction["exit_price"],
                           instruction["exit_reason"],1200)
    assert result["status"]=="EXITED"
    assert result["exit_price"]==.64
    assert result["gross_pnl"]==.32
    assert result["net_pnl"]==round(.32-led.paper_fee(.32)-led.paper_fee(.64),6)
    assert led.open_paper(market["ticker"]) is None
    assert led.close_paper(market["ticker"],.70,"TAKE_PROFIT",1205) is None
    led.conn.close()
    reopened=Ledger(str(path))
    row=reopened.data()["trades"][0]
    assert row["status"]=="EXITED" and row["exited_at"]==1200
    assert row["exit_reason"]=="TAKE_PROFIT"
    assert row["net_pnl"]==result["net_pnl"]
    assert reopened.data()["stats"]["realized_net_paper_pnl"]==round(result["net_pnl"],4)
    reopened.grade(market["ticker"],"yes",1700)
    updated=reopened.data()["trades"][0]
    assert updated["result"]=="yes" and updated["graded"]==1700
    assert updated["net_pnl"]==result["net_pnl"]
    assert updated["exit_price"]==.64 and updated["exited_at"]==1200
    assert updated["status"]=="EXITED"
    assert reopened.unresolved(1)==[]
    reopened.conn.close()


def test_phase3_invalidation_time_stop_cvd_and_bid_depth():
    market=contract(close=1600)
    p={"ticker":market["ticker"],"side":"YES","created":1000,
       "take_profit":.85,
       "invalidation_rule":{"type":"BRTI_CLOSE_BACK_INSIDE_RANGE",
                            "level_usd":63990.,"direction":"UP"}}
    b=book_for(market["ticker"],.40,.50,1250)
    # Fresh completed BRTI candle closed below the entered breakout level.
    bars=[{"t":1140,"close":63980.,"source":"cfbenchmarks_brti_authenticated_live",
           "volume":None}]
    stop=evaluate_exit(p,market,reference(1250,63980.),bars,b,{},1250)
    assert stop["exit_reason"]=="BRTI_INVALIDATION"
    p["invalidation_rule"]=None
    p["take_profit"]=None
    cvd={"available":True,"CVD_norm_60s":-.3,"cvd_60_span":55}
    flip=evaluate_exit(p,market,reference(1250),[],b,cvd,1250)
    assert flip["exit_reason"]=="CVD_SIGN_FLIP"
    assert evaluate_exit(p,market,reference(1250),[],b,
                         {**cvd,"cvd_60_span":10},1250) is None
    assert evaluate_exit(p,market,reference(1250),[],b,
                         {**cvd,"available":False},1250) is None
    time_stop=evaluate_exit(p,market,{},[],b,{},1480)
    assert time_stop is None  # Stale Kalshi depth never executes.
    current=book_for(market["ticker"],.40,.50,1480)
    assert evaluate_exit(p,market,{},[],current,{},1480)["exit_reason"]=="TIME_STOP"
    assert evaluate_exit(p,market,{},[],current,{},1600) is None
    # No same-side bids -> impossible modeled sale; preserve position.
    empty=normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[],"no_dollars":[[".50","5"]]}},
        market["ticker"],1480)
    assert evaluate_exit(p,market,{},[],empty,{},1480) is None


def test_phase3_legacy_schema_migration_and_official_settlement(tmp_path):
    path=tmp_path/"legacy.sqlite3"
    con=sqlite3.connect(path)
    con.execute("""CREATE TABLE paper_trades(
       id INTEGER PRIMARY KEY AUTOINCREMENT,ticker TEXT NOT NULL UNIQUE,
       side TEXT NOT NULL,entry REAL NOT NULL,created REAL NOT NULL,
       seconds_left INTEGER NOT NULL,model_prob REAL,source TEXT NOT NULL,
       status TEXT NOT NULL DEFAULT 'OPEN',result TEXT,pnl REAL,graded REAL)""")
    con.execute("INSERT INTO paper_trades (ticker,side,entry,created,seconds_left,"
                "source) VALUES (?,?,?,?,?,?)",("KXBTC15M-OLD","NO",.30,1000,400,"LEGACY"))
    con.commit();con.close()
    led=Ledger(str(path))
    assert led.open_paper("KXBTC15M-OLD")["take_profit"] is None
    led.grade("KXBTC15M-OLD","yes",1605)
    row=led.data()["trades"][0]
    assert row["status"]=="SETTLED"
    assert row["exit_reason"]=="OFFICIAL_SETTLEMENT"
    assert row["exit_price"]==0.
    assert row["exited_at"]==1605
    assert row["pnl"]==-.30
    assert row["net_pnl"]==round(-.30-led.paper_fee(.30),6)
    led.grade("KXBTC15M-OLD","yes",1610)
    assert led.data()["trades"][0]["exited_at"]==1605
    led.conn.close()


def test_phase3_live_auto_paper_exit_through_worker_during_flow_warmup(env, monkeypatch):
    main, clock, provider, _, _ = env
    main.DEMO=False
    main.AUTO_PAPER=True
    clock.now=provider.close-450
    def snapshot(now_ms=None):
        return {"status":"STREAMING","authenticated_stream_verified":True,
                "source_ts_ms":int(clock.now*1000),
                "axiom_received_at_ms":int(clock.now*1000),
                "latest_value_usd":"90325.",
                "btc_1m_candles":provider.candles()[-12:],
                "btc_5m_candles":[],
                "candle_quality":{"status":"WARMING_BRTI_LIVE",
                                  "bars_used":12},
                "brti_sigma_5s_3m":None}
    monkeypatch.setattr(main.brti_tracker,"snapshot",snapshot)
    monkeypatch.setattr(main.flow_tracker,"snapshot",lambda now:{
        "available":False,"venues":[],"cvd_60_span":0,
        "cvd_90s_span":0,"cvd_5m_span":0})
    def bidbook(market, now=None):
        return book_for(market["ticker"],.30,.68,clock.now)
    provider.orderbook=bidbook
    def deny(*args, **kwargs):
        raise AssertionError("No exchange price or candlestick source in live path")
    provider.price=deny
    provider.timeframe_candles=deny
    first=main.update_once()
    assert first["status"]=="LIVE" and first["ok"] is True
    assert first["warmup"]["status"]=="WARMING"
    assert first["warmup"]["brti_fair_ready"] is False
    assert first["warmup"]["flow_60s_ready"] is False
    assert first["trade_decision"]["action"]=="WAIT"
    # A previously opened position must still exit despite incomplete
    # BRTI/constituent rolling buffers and missing fair-value warmup.
    m=provider.market(clock.now)
    main.ledger.trade({**m,"yes_ask":.32},"YES",clock.now,
                      take_profit=.60,source="AUTO_PAPER")
    clock.now+=5
    provider.orderbook=lambda market,now=None:book_for(market["ticker"],.66,.30,clock.now)
    second=main.update_once()
    assert second["status"]=="LIVE" and second["ok"] is True
    assert second["paper_exit"]["exit_reason"]=="TAKE_PROFIT"
    assert second["paper_exit"]["exit_price"]==.66
    assert main.ledger.data()["trades"][0]["status"]=="EXITED"
    assert main.ledger.data()["count"]["paper"]==1
    assert second["trade_decision"]["action"]=="WAIT"


def test_phase3_constituent_disconnect_resets_only_affected_venue():
    flow=ConstituentFlow()
    assert flow.snapshot(1000)["available"] is False
    flow.ingest("coinbase",{"type":"snapshot","product_id":"BTC-USD",
                            "bids":[["100","10"]],"asks":[["101","10"]]},1000)
    flow.ingest("kraken",{"channel":"book","type":"snapshot",
                          "data":[{"symbol":"BTC/USD","bids":[{"price":100,"qty":10}],
                                   "asks":[{"price":101,"qty":10}]}]},1000)
    flow.ingest("coinbase",{"type":"match","product_id":"BTC-USD",
                            "trade_id":1,"side":"sell","size":".4"},1000)
    flow.ingest("kraken",{"channel":"trade","data":[{"symbol":"BTC/USD",
                    "trade_id":1,"side":"buy","qty":.4}]},1000)
    flow.reset("coinbase")
    assert flow.snapshot(1000)["venues"]==["kraken"]
    flow.ingest("coinbase",{"type":"snapshot","product_id":"BTC-USD",
                            "bids":[["100","10"]],"asks":[["101","10"]]},1001)
    flow.ingest("coinbase",{"type":"match","product_id":"BTC-USD",
                            "trade_id":1,"side":"sell","size":".4"},1001)
    snap=flow.snapshot(1001)
    assert set(snap["venues"])=={"coinbase","kraken"}
    assert snap["available"] is False  # rolling buffers must rebuild
    tracker=BRTITracker(enabled=True)
    tracker.mark(connected=True,subscribed="cfbenchmarks_value_5hz")
    pending=tracker.snapshot(1001000)
    assert pending["status"]=="UNAVAILABLE"
    assert pending["brti_sigma_5s_3m"] is None
