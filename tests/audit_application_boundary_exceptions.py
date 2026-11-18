"""Adversarial application boundary testing: isolated; no external APIs/orders."""
from __future__ import annotations
import math
import pathlib
import sys
import tempfile
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
import requests
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from app import depth_intelligence as depth, engine, ensemble, feeds, orderbook as ob
from app import settlement_reference as ref, settlement_research as shadow
from app.storage import Ledger

TICKER="KXBTC15M-SYNTH-15M"
NOW=1794957700.0


def book(t=NOW,yes=None,no=None):
    yes=[["0.42","25"],["0.40","30"]] if yes is None else yes
    no=[["0.44","25"],["0.41","30"]] if no is None else no
    return ob.normalize_orderbook({"orderbook_fp":{"yes_dollars":yes,"no_dollars":no}},TICKER,t)


def market(t=NOW,**kw):
    out={"ticker":TICKER,"close_ts":t+600,"seconds_left":600,
         "target":90000,"market_mid":.5,"yes_bid":.42,"yes_ask":.56,
         "no_bid":.44,"no_ask":.58}
    return {**out,**kw}


def forecast(**kw):
    return {"available":True,"side":"ABOVE","prob_above":.81,**kw}


def candles(last=NOW-60,n=61,constant=False):
    rows=[]
    start=last-(n-1)*60
    for i in range(n):
        v=90000 if constant else 90000+math.sin(i*.67)*30+i*.7
        rows.append({"t":start+i*60,"close":v,"open":v,"high":v+10,
                     "low":v-10,"volume":i+1})
    return rows


def timeiso(t):
    return datetime.fromtimestamp(t,timezone.utc).isoformat()


class Response:
    def __init__(self,obj,status=200):
        self.obj=obj
        self.status_code=status
    def raise_for_status(self):
        if self.status_code>=400:
            r=requests.Response();r.status_code=self.status_code
            raise requests.HTTPError("safely mocked HTTP",response=r)
    def json(self):return self.obj


class AppBoundaryAudit(unittest.TestCase):
    def test_decimal_orderbook_numeric_validation_and_excessive_level_rejection(self):
        for bad in (None,True,False,object(),"not-a-price","NaN","Infinity","-Infinity"):
            with self.assertRaises(ValueError):
                ob._number(bad)
        for bad in (None,{},[{"price":".5"}],[["0.5"]],[["0.5","5"],["0.50","4"]],
                    [["0.5","0"]],[["0","5"]],[["1","5"]],[["0.5","nan"]],
                    [[".5","1"]]*10001):
            with self.assertRaises(ValueError):
                ob._levels(bad,"YES")
        with self.assertRaises(ValueError):
            ob.sweep(book(),"MAYBE","BUY")
        with self.assertRaises(ValueError):
            ob.sweep(book(),"YES","HOLD")
        for bad in (0,-1,float("nan"),float("inf"),100001):
            with self.assertRaises(ValueError):
                ob.sweep(book(),"YES","BUY",bad)

    def test_full_depth_missing_source_wrong_ticker_and_asymmetric_sides(self):
        for ticker,ts,payload in (
            ("WRONG",NOW,{"orderbook_fp":{"yes_dollars":[],"no_dollars":[]}}),
            (TICKER,float("nan"),{"orderbook_fp":{"yes_dollars":[],"no_dollars":[]}}),
            (TICKER,NOW,{"orderbook":{}}),
            (TICKER,NOW,[]),
        ):
            with self.assertRaises(ValueError):
                ob.normalize_orderbook(payload,ticker,ts)
        for yes,no in (([["0.9","10"]],[["0.5","10"]]),
                       ([["0.2","10"],["0.2","20"]],[["0.3","10"]])):
            with self.assertRaises(ValueError):
                book(yes=yes,no=no)
        b=book(yes=[["0.4","10"]],no=[])
        self.assertTrue(b["available"])
        self.assertIsNone(b["best"]["YES"]["ask"])
        self.assertIsNone(b["best"]["NO"]["bid"])
        self.assertFalse(ob.sweep(b,"YES","BUY",100)["complete"])
        self.assertIsNone(ob.sweep(b,"YES","BUY",100)["average_price"])
        self.assertFalse(ob.current_book(b,TICKER,NOW-3))
        self.assertFalse(ob.current_book(b,"OTHER",NOW))

    def test_depth_liquidity_invalid_probability_size_abstention_and_position(self):
        b=book()
        self.assertEqual(depth._fee_estimate({"available_contracts":0},"YES"),0)
        for model in (None,{},{"available":False},forecast(side="WAIT"),
                      forecast(prob_above=None),forecast(prob_above="broken"),
                      forecast(prob_above=float("nan")),forecast(prob_above=1.1)):
            self.assertEqual(depth.analyze_opportunities(model,market(),b,NOW)["status"],"WAIT")
        for size in ("broken",0,-1,float("inf"),100001):
            self.assertEqual(depth.analyze_opportunities(forecast(),market(),b,NOW,size)["status"],"WAIT")
        self.assertEqual(depth.analyze_opportunities(forecast(),market(seconds_left=20),b,NOW)["status"],"WAIT")
        self.assertEqual(depth.analyze_opportunities(forecast(),market(),None,NOW)["status"],"WAIT")
        self.assertEqual(depth.execution_guidance(None,forecast(),market(),None,NOW)["action"],"WAIT")
        self.assertEqual(depth.execution_guidance(None,{},market(),b,NOW)["action"],"WAIT")
        self.assertEqual(depth.execution_guidance(None,forecast(side="WAIT"),market(),b,NOW,
                                                  position={"side":"YES","contracts":1})["action"],"WAIT")
        for pos in ({"side":"YES","contracts":"invalid"},{"side":"WRONG","contracts":2},
                    {"side":"YES","contracts":0},{"side":"YES","contracts":float("nan")}):
            self.assertEqual(depth.execution_guidance(None,forecast(),market(),b,NOW,position=pos)["action"],"WAIT")
        self.assertEqual(depth.execution_guidance(None,forecast(),market(),b,NOW,
                        position={"side":"YES","contracts":100000})["action"],"WAIT")

    def test_market_timestamp_numeric_cents_mid_and_candle_rejection_paths(self):
        self.assertEqual(engine.utc_timestamp(12),12)
        self.assertIsNone(engine.utc_timestamp(None))
        self.assertIsNone(engine.utc_timestamp("not-a-time"))
        self.assertIsNone(engine.numeric(object()))
        self.assertIsNone(engine.numeric(True))
        self.assertIsNone(engine.quote(-1))
        now=NOW
        with self.assertRaises(ValueError):
            engine.market_snapshot({"ticker":"KXETH15M","close_time":timeiso(now+600)},now)
        with self.assertRaises(ValueError):
            engine.market_snapshot({"ticker":TICKER},now)
        snap=engine.market_snapshot({"ticker":TICKER,"close_time":timeiso(now+600),
                 "floor_strike":"bad","yes_ask":61,"no_ask":55},now)
        self.assertEqual(snap["yes_ask"],.61)
        self.assertIsNone(snap["target"])
        snap=engine.market_snapshot({"ticker":TICKER,"close_time":timeiso(now+600),
                "floor_strike":90000,"yes_ask_dollars":".31","no_ask_dollars":".53"},now)
        self.assertEqual(snap["market_price_source"],"participant_order_book")
        for raw in ([["broken"]],[[60,1,2,3,4,1]],[[60,1,2,1.1,2.1,1]],
                    [[60,1,2,1.3,1.1,"nan"]]):
            self.assertEqual(engine.normalize_candles(raw),[])
        self.assertEqual(engine.ema([],9),0.0)

    def test_volatility_invalid_sigma_scales_empty_scalping_and_paper_guard(self):
        self.assertFalse(engine.volatility_forecast(0,90000,600,candles())["available"])
        self.assertFalse(engine.volatility_forecast(90000,90000,600,[])["available"])
        with patch.object(engine.statistics,"stdev",return_value=float("nan")):
            self.assertFalse(engine.volatility_forecast(90000,90000,600,candles())["available"])
        flat=candles(constant=True)
        for c in flat:
            c["low"]=c["close"];c["high"]=c["close"]
        self.assertEqual(engine.scalp_signal(flat,90000)["side"],"WAIT")
        self.assertEqual(engine.opportunity({"available":False},market())["side"],"WAIT")
        self.assertEqual(engine.opportunity({"available":True,"prob_above":.9},market(yes_ask=None,no_ask=None))["side"],"WAIT")
        self.assertEqual(engine.opportunity({"available":True,"prob_above":.5},market(seconds_left=20))["side"],"WAIT")
        for side,result in (("MAYBE","yes"),("YES","invalid")):
            with self.assertRaises(ValueError):
                engine.paper_result(side,.4,result)
        self.assertEqual(ensemble.execution_screen({"available":False},market())["side"],"WAIT")
        self.assertEqual(ensemble.execution_screen({"available":True,"side":"ABOVE","prob_above":.81},
                                                    market(yes_ask=None,no_ask=None))["side"],"WAIT")

    def test_feed_short_contiguous_missing_live_results_and_orderbook_validation(self):
        usable,q=feeds.contiguous_real_candle_suffix(candles(n=7))
        self.assertEqual(q["status"],"INSUFFICIENT")
        self.assertEqual(usable,candles(n=7))
        usable,q=feeds.contiguous_real_candle_suffix(candles(n=35))
        self.assertEqual(q["status"],"SHORT_BUT_CONTIGUOUS")
        p=feeds.LiveProvider()
        with patch.object(p,"get",return_value={"price":"bad"}):
            with self.assertRaises(ValueError):
                p.price()
        with patch.object(p,"get",return_value={"price":"90123.5"}):
            self.assertEqual(p.price(),90123.5)
        with self.assertRaises(ValueError):
            p.orderbook(None)
        with self.assertRaises(ValueError):
            p.orderbook({"ticker":"KXBTC15M-/bad"})
        with self.assertRaises(ValueError):
            p.orderbook({"ticker":"KXBTC15M-bad?x"})
        class S:
            def get(self,*a,**kw):return Response({"orderbook_fp":{"yes_dollars":[[".4","3"]],"no_dollars":[[".4","3"]]}})
        p.session=S()
        with patch.object(feeds.time,"time",return_value=NOW):
            got=p.orderbook({"ticker":TICKER},NOW)
        self.assertTrue(got["available"])
        self.assertEqual(got["received_at"],NOW)
        fresh=p.market

    def test_market_retry_network_failure_is_safe_and_bad_payload_is_ignored(self):
        p=feeds.LiveProvider()
        now=1794938405.0 # within real 900-second boundary
        calls=[]
        def empty_then_timeout(url,params):
            calls.append((url,params))
            if len(calls)==1:
                return {"markets":[{"ticker":"KXETH-INVALID"}]}
            raise requests.Timeout("synthetic timeout")
        with patch.object(p,"get",side_effect=empty_then_timeout),patch.object(
            feeds.time,"time",return_value=now),patch.object(feeds.time,"sleep",return_value=None):
            self.assertIsNone(p.market(now))
        self.assertEqual(len(calls),2)
        # Retry must not run on historic replay or outside a fresh rollover.
        p.get=lambda *args,**kwargs:{"markets":[]}
        with patch.object(feeds.time,"time",return_value=now+3600):
            self.assertIsNone(p.market(now))
        with patch.object(feeds.time,"time",return_value=now):
            self.assertIsNone(p.market(now+210))
        with patch.object(p,"get",return_value={"markets":[
                {"ticker":"KXBTC15M-OLD","close_time":timeiso(now-1)},
                {"ticker":TICKER,"close_time":timeiso(now+540),"floor_strike":"90000"}]}):
            out=p.market(now+110)
        self.assertEqual(out["ticker"],TICKER)

    def test_provider_settlement_strict_ticker_status_and_historical_http_errors(self):
        p=feeds.LiveProvider()
        with self.assertRaises(ValueError):
            p.settlement("KXBTC15M-/bad")
        with self.assertRaises(ValueError):
            p.settlement("other")
        with patch.object(p,"get",side_effect=[
                {"market":{"status":"closed","result":"yes"}},
                {"market":{"status":"settled","result":"yes"}}]):
            self.assertEqual(p.settlement(TICKER),"yes")
        with patch.object(p,"get",side_effect=[
                {"market":{"status":"open","result":"yes"}},
                {"market":{"status":"settled","result":"yes"}}]) as call:
            self.assertIsNone(p.settlement(TICKER))
            self.assertEqual(call.call_count,1)
        resp=requests.Response();resp.status_code=404
        e=requests.HTTPError("not found",response=resp)
        with patch.object(p,"get",side_effect=[e,{"market":{"status":"finalized","result":"no"}}]):
            self.assertEqual(p.settlement(TICKER),"no")
        resp.status_code=503
        with patch.object(p,"get",side_effect=requests.HTTPError("failure",response=resp)):
            with self.assertRaises(requests.HTTPError):
                p.settlement(TICKER)

    def test_demo_provider_settlement_and_missing_quote_depth_are_synthetic_only(self):
        d=feeds.DemoProvider()
        ticker="KXBTC15M-DEMO-1994000"
        end=(1994000+1)*900
        self.assertIsNone(d.settlement("KXBTC15M-MISSING"))
        with patch.object(feeds.time,"time",return_value=end+1):
            self.assertIsNone(d.settlement(ticker))
        with patch.object(feeds.time,"time",return_value=end+6):
            self.assertIn(d.settlement(ticker),("yes","no"))
        b=d.orderbook({"ticker":ticker,"yes_bid":None,"no_bid":None},NOW)
        self.assertEqual(b["source"],"synthetic_demo_orderbook")
        self.assertFalse(b["available"])

    def test_official_reference_time_money_and_missing_ticks_fail_closed(self):
        for val in (None,True,5,"2026-11-17T18:00:00",
                    "2026-11-17T18:00:00.123456Z"):
            with self.assertRaises(ValueError):
                ref._time(val)
        for val in (None,False,"garbage","NaN","Infinity",1,1000000):
            with self.assertRaises(ValueError):
                ref._money(val)
        term={"ticker":TICKER,"status":"settled","result":"yes",
              "open_time":"bad","close_time":"2026-11-17T18:00:00Z",
              "floor_strike":90000,"expiration_value":90000}
        self.assertEqual(ref.reconcile_contract(term,[])["status"],"INCOMPLETE")
        self.assertEqual(ref.reconcile_contract(None,[])["status"],"INCOMPLETE")
        self.assertEqual(ref.reconcile_contract({**term,"status":"open"},[])["status"],"PENDING")
        self.assertEqual(ref.reconcile_contract({**term,"result":""},[])["status"],"PENDING")
        self.assertEqual(ref.reconcile_contract({**term,"ticker":"OTHER"},[])["status"],"INCOMPLETE")

    def test_shadow_rejects_structural_and_out_of_order_input_without_proxy_claims(self):
        m={"target":90000,"seconds_left":600}
        self.assertFalse(shadow.shadow_forecast_from_candles([],None,NOW)["available"])
        for data,mar in (
            (candles(),{"seconds_left":"bad","target":90000}),
            (None,m),("bad",m),
            ([None],m),([{"t":NOW}],m),
            ([{"t":float("nan"),"close":90100}],m),
            ([{"t":NOW+100,"close":90000}],m),
            (candles(n=7),m),
            (candles(n=31)[:-1]+[candles(n=31)[-2]],m),
        ):
            self.assertFalse(shadow.shadow_forecast_from_candles(data,mar,NOW)["available"])
        zero=candles(constant=True)
        self.assertFalse(shadow.shadow_forecast_from_candles(zero,m,NOW)["available"])
        old=candles(last=NOW-1000)
        self.assertFalse(shadow.shadow_forecast_from_candles(old,m,NOW)["available"])

    def test_storage_nested_atomic_invalid_trade_unresolved_and_empty_watch(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Ledger(str(pathlib.Path(tmp)/"state.sqlite3"))
            try:
                with db.atomic_cycle():
                    with self.assertRaises(RuntimeError):
                        with db.atomic_cycle():
                            pass
                self.assertEqual(db.unresolved(max_rows=0),[])
                self.assertIsNone(db.watch_info("not-existing"))
                with self.assertRaises(ValueError):
                    db.grade(TICKER,"unknown",NOW)
                for side,m in (("MAYBE",market()),("YES",market(seconds_left=1)),
                               ("YES",market(yes_ask=None))):
                    with self.assertRaises(ValueError):
                        db.trade(m,side,NOW)
                m=market()
                model={"available":True,"side":"BELOW","prob_above":.06}
                self.assertIsNone(db.first_call(m,model,90000,NOW))
                self.assertEqual(db.watch_info(TICKER)["side"],"BELOW")
                self.assertIsNotNone(db.first_call(m,model,90000,NOW+12))
            finally:
                db.conn.close()


if __name__=="__main__":
    unittest.main(verbosity=2)
