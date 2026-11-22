"""Boundary-driven Phase 1-3 constituent, market-tape and transport tests."""
import asyncio
import json
import math
import sys
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import axiom_brain as brain
from app.orderbook import normalize_orderbook


NOW = 1_800_000_000.


def book(t=NOW, bid=".55", no=".40", ticker="KXBTC15M-COVER"):
    return normalize_orderbook({"orderbook_fp": {
        "yes_dollars": [[bid, "3"]], "no_dollars": [[no, "3"]]}}, ticker, t)


def contract(t=NOW):
    return {"ticker": "KXBTC15M-COVER", "target": 99., "close_ts": t+420}


def _seed(flow, venue, t=NOW, bid=100., ask=101., size=10):
    flow._book(venue, {bid: size}, {ask: size}, t, snapshot=True)


def _trades(flow, venues=("coinbase", "kraken"), direction="buy", start=NOW-50):
    for venue in venues:
        _seed(flow, venue, NOW-1)
        for i in range(51):
            flow._trade(venue, ("cover", i), direction, .4, start+i)
            flow._book(venue, {100.: 10+i/20}, {101.: 10}, start+i,
                       snapshot=False)


def test_converters_pressure_tape_and_structure_boundaries():
    assert brain._positive("nan") is None
    assert brain._positive(object()) is None
    assert brain._positive(-3) is None
    assert brain._positive(3) == 3
    assert brain._levels(None) == {}
    assert brain._levels([None, ["bad", 3], [100, 0], [100, "2"], [101]]) == {100.:2.}
    assert brain._levels([{"price":"100","qty":"2"}, {"price":"bogus","qty":"3"}],
                         kraken=True) == {100.:2.}
    assert brain._near_depth({"bids": {}, "asks":{101:3}}) == (None,None,None)
    assert brain._near_depth({"bids":{101:2}, "asks":{101:3}}) == (None,None,None)
    middle,b,a=brain._near_depth({"bids":{100:2,99:4}, "asks":{100.1:3,101:4}})
    assert middle==100.05 and b==2 and a==3
    x={"bids":{100.:10},"asks":{101.:10}}
    y={"bids":{100.:15,99.:4},"asks":{101.:9}}
    net,gross=brain._pressure(x,y)
    assert net>0 and gross>=net
    assert brain._trade_autocorr([]) is None
    assert brain._trade_autocorr([(i,1.,i) for i in range(32)]) is None
    assert brain._trade_autocorr([(i,1 if i%2 else -1,i) for i in range(80)]) < -.8
    trend=[(i,1 if (i//9)%2 else -1,i) for i in range(100)]
    assert brain._trade_autocorr(trend) > .3
    assert brain._depth_thinning([],NOW,"bid") == (None,False)
    samples=deque([(NOW-125+i,10.,10.) for i in range(96)] +
                  [(NOW-15+i,2.,2.) for i in range(16)])
    r,thin=brain._depth_thinning(samples,NOW,"bid")
    assert round(r,3)==.2 and thin
    assert brain._depth_thinning(samples,NOW,"ask")[1]
    samples[-1]=(NOW,8.,8.)
    assert brain._depth_thinning(samples,NOW,"bid")[1] is False
    zeros=deque([(NOW-125+i,0.,0.) for i in range(96)] +
                [(NOW-15+i,0.,0.) for i in range(16)])
    assert brain._depth_thinning(zeros,NOW,"bid")==(None,False)
    assert brain._depth_thinning(deque([(NOW-100+i,10.,10.) for i in range(70)] +
                                      [(NOW-15+i,2.,2.) for i in range(7)]), NOW, "bid")[0] is None
    assert brain._et_windows(1_800_000_000.) in ((False,False),(False,True),(True,False),(True,True))


def test_constituent_book_resets_delta_trade_replay_and_bounded_ids():
    flow=brain.ConstituentFlow()
    flow.ingest("invalid", {}, NOW)
    flow.ingest("coinbase", None, NOW)
    flow.ingest("coinbase", {"type":"snapshot","product_id":"wrong"}, NOW)
    flow.ingest("coinbase",{"type":"l2update","product_id":"BTC-USD",
             "changes":[["buy",100,5]]},NOW)
    assert flow.books["coinbase"] is None
    flow.ingest("coinbase",{"type":"snapshot","product_id":"BTC-USD",
             "bids":[["100","4"],["bad","6"]],"asks":[["101","5"]]},NOW-10)
    assert flow.books["coinbase"] is not None
    flow.ingest("coinbase", {"type":"l2update","product_id":"BTC-USD",
             "changes":[["buy","100","6"],["buy","99","2"],
                        ["sell","101","0"],["sell","102","4"],["bad"],
                        ["buy","oops","nan"],["junk","100","3"]]},NOW-5)
    assert 101. not in flow.books["coinbase"]["asks"]
    assert 102. in flow.books["coinbase"]["asks"]
    assert flow.ofi["coinbase"]
    flow.ingest("coinbase",{"type":"match","product_id":"BTC-USD",
             "trade_id":2,"side":"sell","size":".25"},NOW)
    flow.ingest("coinbase",{"type":"last_match","product_id":"BTC-USD",
             "trade_id":2,"side":"sell","size":".25"},NOW)
    assert len(flow.trades["coinbase"])==1 and flow.trades["coinbase"][0][1]>.0
    flow._trade("coinbase",1,"wrong",3,NOW)
    flow._trade("coinbase",1,"buy","bad",NOW)
    assert len(flow.trades["coinbase"])==1
    for i in range(4002):
        flow._trade("coinbase", 100+i, "sell",.1,NOW)
    assert len(flow.trade_ids["coinbase"])<=4000
    flow._book("coinbase",{100:2},{99:2},NOW,snapshot=True)
    assert flow.books["coinbase"] is None
    flow._book("coinbase",{}, {},NOW,snapshot=True)
    assert flow.books["coinbase"] is None
    flow._book("coinbase",{100-i*.01:2 for i in range(230)},
               {101+i*.01:2 for i in range(230)},NOW,snapshot=True)
    assert len(flow.books["coinbase"]["bids"])==200
    flow._book("coinbase",{100:5},{101:6},NOW,snapshot=True)
    count=len(flow.depth_samples["coinbase"])
    flow._book("coinbase",{100:6},{101:7},NOW,snapshot=True)
    assert len(flow.depth_samples["coinbase"])==count
    flow.reset("coinbase")
    assert flow.books["coinbase"] is None and not flow.trades["coinbase"]


def test_kraken_bitstamp_normalization_and_three_venue_dispersion():
    flow=brain.ConstituentFlow()
    flow.ingest("kraken", {"channel":"book","type":"snapshot","data":[
        {"symbol":"ETH/USD","bids":[],"asks":[]},
        {"symbol":"BTC/USD","bids":[{"price":"100","qty":"4"},
                                    {"price":"bad","qty":"5"},
                                    {"price":"99","qty":"bad"}],
         "asks":[{"price":"101","qty":"4"}]}]},NOW-1)
    flow.ingest("kraken", {"channel":"book","type":"update","data":[
        {"symbol":"BTC/USD","bids":[{"price":"100","qty":"6"}],
         "asks":[{"price":"101","qty":"5"}]}]},NOW)
    flow.ingest("kraken", {"channel":"trade","data":[
        {"symbol":"BTC/USD","price":"100","qty":".3",
         "side":"buy","timestamp":"x"}]},NOW)
    flow.ingest("bitstamp", {"channel":"order_book_btcusd","event":"data",
              "data":{"bids":[["100.2","4"]],"asks":[["101.2","4"]]}},NOW)
    flow.ingest("bitstamp", {"channel":"live_trades_btcusd","event":"trade",
              "data":{"id":1,"type":1,"amount":".3"}},NOW)
    flow.ingest("bitstamp", {"channel":"live_trades_btcusd","event":"trade",
              "data":{"id":2,"type":0,"amount_str":".5"}},NOW)
    flow.ingest("bitstamp", {"channel":"live_trades_btcusd","event":"trade",
              "data":{"id":3,"type":13,"amount":".3"}},NOW)
    assert len(flow.trades["bitstamp"])==2
    flow.ingest("bitstamp", {"channel":"wrong","event":"data","data":"bad"},NOW)
    _seed(flow,"coinbase",NOW,105.,106.)
    flow._trade("coinbase",9,"sell",.2,NOW)
    snapshot=flow.snapshot(NOW)
    assert len(snapshot["venues"])==3
    assert snapshot["outlier_venue"]=="coinbase"
    assert snapshot["delta_venue"]>0
    assert snapshot["source_price_role"]=="dispersion_diagnostic_only"
    flow.reset("kraken")
    assert "kraken" not in flow.snapshot(NOW)["venue_midpoints"]
    assert flow.snapshot(NOW+100)["venues"]==[]


def test_signed_flow_ready_and_opposing_direction():
    up=brain.ConstituentFlow()
    _trades(up,direction="buy")
    assert up.snapshot(NOW)["available"] is True
    assert up.snapshot(NOW)["confirmed_direction"]=="UP"
    down=brain.ConstituentFlow()
    _trades(down,direction="sell")
    snap=down.snapshot(NOW)
    assert snap["available"] and snap["confirmed_direction"] is None or snap["confirmed_direction"]=="DOWN"
    assert snap["CVD_norm_60s"] < 0


def test_bars_implied_sigma_tape_volume_gate_and_breakouts():
    assert not brain._bars_usable(None,NOW,2,60)
    assert not brain._bars_usable([],NOW,2,60)
    def candles(n=65):
        start=int(NOW//60)*60-n*60
        return [{"t":start+i*60,"open":100.,"high":100.02,
                 "low":99.98,"close":100.,
                 "source":brain.BRTI_SOURCE,"volume":None} for i in range(n)]
    bars=candles()
    assert brain._bars_usable(bars,NOW,31,60)
    assert not brain._bars_usable(bars[:-5],NOW,31,60)
    assert not brain._bars_usable([*bars[:-1],{"t":bars[-1]["t"],
             "source":brain.BRTI_SOURCE,"volume":None,"open":"bad"}],NOW,31,60)
    altered=[dict(x) for x in bars]
    altered[-2]["t"]+=1
    assert not brain._bars_usable(altered,NOW,31,60)
    assert not brain._bars_usable("bad",NOW,31,60)
    assert brain._regime(bars,[{"close":100.} for _ in range(6)]) in ("SQUEEZE","TRENDING","CHOP")
    bars[-1].update({"open":100., "close":100.4,"high":100.42})
    assert brain._brti_breakout(bars,"UP") is not None
    bars[-1].update({"open":100., "close":99.6,"low":99.58})
    assert brain._brti_breakout(bars,"DOWN") is not None
    assert brain._brti_breakout(bars,"NONE") is None
    m=contract()
    b=book()
    assert brain._implied_minute_sigma(m,b,100.,NOW) is not None
    assert brain._implied_minute_sigma(m,b,99.,NOW) is None
    assert brain._implied_minute_sigma({**m,"target":None},b,100.,NOW) is None
    assert brain._implied_minute_sigma({**m,"close_ts":NOW+50},b,100.,NOW) is None
    assert brain._implied_minute_sigma(m,book(bid=".42",no=".42"),100.,NOW) is None
    assert brain._implied_minute_sigma(m,book(bid=".20",no=".40"),100.,NOW) is None
    assert brain._implied_minute_sigma(m,{"best":{"YES":{"bid":None}}},100.,NOW) is None
    tape=brain.MarketTape()
    tape.observe(None,b,100.,NOW)
    tape.observe(m,{},100.,NOW)
    tape.observe(m,book(bid=".3",no=".30"),100.,NOW)
    tape.observe(m,b,100.,NOW-10)
    tape.observe(m,book(t=NOW),100.,NOW)
    tape.observe(m,book(t=NOW+5,bid=".57"),100.,NOW+5)
    state=tape.snapshot(m,NOW+5)
    assert state["mid_jump_20s"] is not None
    assert state["implied_samples_24h"]<=2
    tape.mid_history=deque([(NOW,m["ticker"],.4),(NOW,m["ticker"],.5)])
    assert tape.snapshot(m,NOW)["mid_jump_20s"] is None
    tape.implied_24h=deque((NOW-23*3600-100+i*837, .0005+i*.000001) for i in range(100))
    assert tape.snapshot(m,NOW)["implied_history_ready"]
    assert tape.snapshot(m,NOW)["implied_sigma_quartile_24h"] is not None
    tape.implied_24h=deque([(NOW-90000,.001),(NOW-100,.002)])
    tape.observe(m,book(t=NOW+65),100.,NOW+65)
    assert all(x[0]>=NOW+65-86400 for x in tape.implied_24h)


def test_readonly_signal_respects_side_price_and_flow():
    b=book()
    assert brain._exit_signal(None,b,{},100) is None
    assert brain._exit_signal("YES",b,{},151) is None
    assert brain._exit_signal("YES",b,{},100) is None
    shallow=book(bid=".3")
    assert brain._exit_signal("YES",shallow,{},120)["reason"]=="TIME_STOP"
    assert brain._exit_signal("YES",shallow,{"CVD_norm_60s":-.3},120)["reason"]=="CVD_SIGN_FLIP"
    assert brain._exit_signal("NO",shallow,{},120)["reason"]=="TIME_STOP"
    assert brain._exit_signal("NO",book(no=".3"),{"CVD_norm_60s":.4},120)["reason"]=="CVD_SIGN_FLIP"


def test_mock_public_ws_sessions_reconnect_and_nonblocking_threads(monkeypatch,caplog):
    class FakeSocket:
        def __init__(self, url):
            self.url=url
            self.sent=[]
            self.got=0
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        async def send(self,msg):
            self.sent.append(json.loads(msg))
        async def recv(self):
            self.got+=1
            if self.got>1:
                await asyncio.sleep(.01)
                raise asyncio.TimeoutError
            if "advanced-trade" in self.url:
                return json.dumps({"channel":"l2_data","events":[
                    {"type":"snapshot","product_id":"BTC-USD","updates":[
                     {"side":"bid","price_level":"100","new_quantity":"2"},
                     {"side":"offer","price_level":"101","new_quantity":"3"}]}]})
            return json.dumps({"type":"match","product_id":"BTC-USD",
                               "trade_id":123,"side":"sell","size":"1"})
    sockets=[]
    connection_options=[]
    def connect(url,**kwargs):
        socket=FakeSocket(url)
        sockets.append(socket)
        connection_options.append(kwargs)
        return socket
    monkeypatch.setitem(sys.modules,"websockets",SimpleNamespace(connect=connect))
    class St:
        def __init__(self):
            self.waits=[]
            self.stopped=False
        def is_set(self):
            return self.stopped
        def wait(self,s):
            self.waits.append(s)
            self.stopped=True
            return True
    stop=St()
    flow=brain.ConstituentFlow()
    for venue, sends in [("coinbase",2),("kraken",2),("bitstamp",2)]:
        previous=len(sockets)
        with pytest.raises(TimeoutError, match=venue):
            asyncio.run(brain._session(flow,venue,stop))
        assert sum(len(socket.sent) for socket in sockets[previous:])==sends
        assert all(option["max_size"] == 16 * 1024 * 1024
                   for option in connection_options[previous:])
        assert flow.worker_status[venue] == "SUBSCRIPTION_SENT"
        if venue == "coinbase":
            assert len(sockets)-previous == 2
            advanced=next(x for x in sockets[previous:] if "advanced-trade" in x.url)
            exchange=next(x for x in sockets[previous:] if "ws-feed.exchange" in x.url)
            assert advanced.sent[0] == {"type":"subscribe","product_ids":["BTC-USD"],
                                        "channel":"level2"}
            assert exchange.sent[0] == {"type":"subscribe","product_ids":["BTC-USD"],
                                        "channels":["matches"]}
            assert flow.books["coinbase"]["bids"] == {100.:2.}
            assert flow.books["coinbase"]["asks"] == {101.:3.}
            assert flow.trades["coinbase"][0][1] > 0
    def finished(coro):
        coro.close()
    monkeypatch.setattr(brain.asyncio,"run",finished)
    brain._venue_worker(flow,"coinbase",stop)
    assert stop.waits[-1]==2
    def fail(coro):
        coro.close()
        raise OSError("disconnected")
    monkeypatch.setattr(brain.asyncio,"run",fail)
    stop.stopped=False
    brain._venue_worker(flow,"kraken",stop)
    assert stop.waits[-1]==4
    error = flow.diagnostics()["kraken"]
    assert error["connection_status"] == "BACKOFF"
    assert "OSError: disconnected" in error["last_error"]
    assert "venue=kraken" in caplog.text
    made=[]
    class FakeThread:
        def __init__(self,**kwargs):
            made.append(kwargs)
        def start(self):
            return None
    monkeypatch.setattr(brain.threading,"Thread",FakeThread)
    threads=brain.start_flow_workers(flow,stop)
    assert len(threads)==3
    assert all(x["daemon"] is True for x in made)


def test_remaining_flow_validation_downward_pressure_and_regime():
    flow=brain.ConstituentFlow()
    flow._trade("coinbase",None,"buy",1,NOW)
    assert len(flow.trades["coinbase"])==1
    flow.ingest("coinbase",{"product_id":"BTC-USD","type":"heartbeat"},NOW)
    flow.ingest("coinbase",{"product_id":"BTC-USD","type":"l2update",
                "changes":[["buy","100","nan"],["buy","-1","2"]]},NOW)
    flow.ingest("kraken",{"channel":"book","type":"snapshot","data":[{
                "symbol":"BTC/USD",
                "bids":[["100",3],{"price":"100","qty":3}],
                "asks":[["101",3],{"price":"101","qty":3}]}]},NOW)
    flow.ingest("kraken",{"channel":"heartbeat","data":[{"symbol":"BTC/USD"}]},NOW)
    flow.ingest("bitstamp",{"channel":"heartbeat","event":"data","data":{}},NOW)
    flow._book("coinbase",{100.:3},{101.:3},NOW,snapshot=True)
    flow.books["coinbase"]={"bids":{102.:2},"asks":{101.:2}}
    flow.book_at["coinbase"]=NOW
    assert "coinbase" not in flow.snapshot(NOW)["venue_midpoints"]
    down=brain.ConstituentFlow()
    for venue in ("coinbase","kraken"):
        _seed(down,venue,NOW-51)
        for i in range(51):
            at=NOW-50+i
            down._book(venue,{100.:10-i*.025},{101.:10+i*.025},
                       at,snapshot=False)
            down._trade(venue,("down",i),"sell",.2,at)
    snap=down.snapshot(NOW)
    assert snap["available"] and snap["confirmed_direction"]=="DOWN",snap
    closes=[100+i*.12 for i in range(65)]
    bars=[{"close":p,"high":p+.05,"low":p-.05} for p in closes]
    five=[{"close":100+i} for i in range(6)]
    assert brain._regime(bars,five)=="TRENDING"
    from zoneinfo import ZoneInfo
    from datetime import datetime
    saturday=datetime(2026,11,21,12,0,tzinfo=ZoneInfo("America/New_York")).timestamp()
    assert brain._et_windows(saturday)==(False,False)
    tape=brain.MarketTape()
    invalid={"available":True,"ticker":contract()["ticker"],
             "received_at":NOW,
             "best":{"YES":{"bid":None,"ask":None}}}
    tape.observe(contract(),invalid,100.,NOW)
    assert not tape.mid_history



def test_venue_diagnostics_track_reconnect_staleness_and_recovery():
    flow = brain.ConstituentFlow()
    initial = flow.diagnostics(NOW)
    assert list(initial) == ["coinbase", "kraken", "bitstamp"]
    assert initial["coinbase"]["connection_status"] == "STARTING"
    assert initial["coinbase"]["last_valid_book_age_seconds"] is None
    assert initial["coinbase"]["last_trade_age_seconds"] is None
    assert initial["coinbase"]["health_error"] is None

    flow.connection_event("coinbase", "CONNECTING", now=NOW-40)
    assert flow.diagnostics(NOW)["coinbase"]["health_error"] is None
    flow.connection_event("coinbase", "SUBSCRIPTION_SENT", now=NOW-35)
    status = flow.diagnostics(NOW)["coinbase"]
    assert status["health_error"] == "No recent valid order book"
    assert not status["book_ready"] and not status["trade_ready"]

    flow._book("coinbase", {100.: 5.}, {101.: 4.}, NOW-1, snapshot=True)
    status = flow.diagnostics(NOW)["coinbase"]
    assert status["book_ready"] and not status["trade_ready"]
    assert status["health_error"] == "No recent accepted trades"
    assert status["last_valid_book_age_seconds"] == 1
    flow._trade("coinbase", 1, "buy", .2, NOW-1)
    status = flow.diagnostics(NOW)["coinbase"]
    assert status["ready"] and status["health_error"] is None
    assert status["last_trade_age_seconds"] == 1

    # The last valid timestamps survive the reconnect book/trade reset.
    flow.reset("coinbase")
    status = flow.diagnostics(NOW)
    assert status["coinbase"]["last_valid_book_at"] == NOW-1
    assert status["coinbase"]["last_trade_at"] == NOW-1
    assert not status["coinbase"]["ready"]

    flow.connection_event("coinbase", "BACKOFF",
                          error=RuntimeError("WebSocket close 1009 MESSAGE_TOO_BIG"),
                          now=NOW)
    status = flow.diagnostics(NOW)["coinbase"]
    assert status["connection_status"] == "BACKOFF"
    assert status["last_error_at"] == NOW
    assert "1009 MESSAGE_TOO_BIG" in status["health_error"]

    flow.connection_event("coinbase", "CONNECTING", now=NOW+1)
    flow.connection_event("coinbase", "SUBSCRIPTION_SENT", now=NOW+2)
    assert flow.diagnostics(NOW+3)["coinbase"]["health_error"] is None
    flow._book("coinbase", {100.: 5.}, {101.: 4.}, NOW+3, snapshot=True)
    flow._trade("coinbase", 2, "sell", .3, NOW+3)
    status = flow.diagnostics(NOW+4)["coinbase"]
    assert status["ready"] and status["health_error"] is None
    assert status["last_error"] is not None  # Historical error retained.
    assert status["last_valid_book_age_seconds"] == 1
    assert status["last_trade_age_seconds"] == 1

    # The current book/trades can become stale even while the socket stays up.
    status = flow.diagnostics(NOW+80)["coinbase"]
    assert status["health_error"] == "No recent valid order book"
    assert status["last_valid_book_age_seconds"] == 77


def test_coinbase_advanced_l2_data_snapshot_update_validation_and_trade_separation():
    flow = brain.ConstituentFlow()
    row = lambda side, price, qty: {
        "side": side, "price_level": price, "new_quantity": qty}
    flow.ingest("coinbase", {"channel": "l2_data", "events": [
        None, {"type": "snapshot", "product_id": "ETH-USD", "updates": []},
        {"type": "heartbeat", "product_id": "BTC-USD", "updates": []},
        {"type": "snapshot", "product_id": "BTC-USD", "updates": [
            "not-an-update", row("bid", "100", "3"), row("bid", "99", "4"),
            row("offer", "101", "5"), row("offer", "102", "6"),
            row("offer", "103", "0"), row("bid", "bad", "1"),
            row("bid", "98", "bad"), row("offer", "104", "-1"),
            row("bid", "96", "nan"), row("other", "95", "1"),
            {"side": "bid", "price_level": 92, "new_quantity": None},
        ]}]}, NOW)
    assert flow.books["coinbase"]["bids"] == {100.: 3., 99.: 4.}
    assert flow.books["coinbase"]["asks"] == {101.: 5., 102.: 6.}
    assert flow.diagnostics(NOW)["coinbase"]["book_ready"]
    assert not flow.diagnostics(NOW)["coinbase"]["trade_ready"]

    flow.ingest("coinbase", {"channel": "l2_data", "events": [{
        "type": "update", "product_id": "BTC-USD", "updates": [
            row("bid", "99", "0"), row("bid", "100", "7"),
            row("offer", "101", "0"), row("offer", "102", "8"),
            row("offer", "103", "1")]}]}, NOW+1)
    assert flow.books["coinbase"]["bids"] == {100.: 7.}
    assert flow.books["coinbase"]["asks"] == {102.: 8., 103.: 1.}
    assert flow.ofi["coinbase"]
    flow.ingest("coinbase", {"channel": "l2_data", "events": [{
        "type": "update", "product_id": "BTC-USD", "updates": [
            row("bad", "100", "8")]}]}, NOW+2)
    flow.ingest("coinbase", {"type": "match", "product_id": "BTC-USD",
                "trade_id": 123, "side": "sell", "size": ".4"}, NOW+2)
    diagnostic = flow.diagnostics(NOW+2)["coinbase"]
    assert diagnostic["book_ready"] and diagnostic["trade_ready"]
    assert "coinbase" in flow.snapshot(NOW+2)["venues"]
    assert flow.trades["coinbase"][-1][1] > 0


@pytest.mark.parametrize("message", [
    {"type": "error", "message": "Failed to subscribe",
     "reason": "level2 requires authentication"},
    {"channel": "error", "message": "Invalid Advanced Trade subscription"},
])
def test_coinbase_public_websocket_subscription_error_is_not_silent(monkeypatch, message):
    class Socket:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def send(self, msg):
            assert json.loads(msg)["channel"] == "level2"
        async def recv(self):
            return json.dumps(message)
    monkeypatch.setitem(sys.modules, "websockets",
                        SimpleNamespace(connect=lambda *_a, **_k: Socket()))
    flow = brain.ConstituentFlow()
    stop = SimpleNamespace(is_set=lambda: False)
    with pytest.raises(RuntimeError, match="Coinbase subscription rejected"):
        asyncio.run(brain._coinbase_feed(flow, stop, order_book=True))
    assert flow.books["coinbase"] is None
