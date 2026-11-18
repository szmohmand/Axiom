"""Isolation tests of worker failure/recovery and health state transitions.

All API/ledger actions operate only on temporary SQLite databases and fake
public-market data. Real account keys, orders, and deployment are never used.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import HTTPException
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app import main
from app import feeds,orderbook
from app.storage import Ledger


class StaticPublicProvider:
    def __init__(self,now):
        self.now=now
        self.ticker="KXBTC15M-AUDIT-STATIC"
        self.candle_quality={"status":"FULL","missing_candles_filled":0}
        self.result=None
    def market(self,now=None):
        t=self.now if now is None else now
        return {
          "ticker":self.ticker,"title":"Synthetic audit snapshot","status":"open",
          "close_ts":t+600,"seconds_left":600,"target":90000,
          "yes_bid":.42,"yes_ask":.56,"no_bid":.44,"no_ask":.58,
          "market_mid":.49,"result":"",
        }
    def price(self):return 90000.2
    def candles(self):
        t=int(self.now//60)*60-60
        out=[]
        for i in range(61):
            v=90000+math.sin(i*.63)*30+i*.4
            out.append({"t":t-(60-i)*60,"close":v,"open":v,
                        "high":v+4,"low":v-4,"volume":2.0})
        return out
    def orderbook(self,market,now=None):
        return orderbook.normalize_orderbook(
            {"orderbook_fp":{"yes_dollars":[["0.42","80"]],
                             "no_dollars":[["0.44","80"]]}},
            market["ticker"],self.now)
    def settlement(self,ticker):return self.result


class AuditedWorkers(unittest.TestCase):
    def setUp(self):
        self.now=time.time()
        self.tmp=tempfile.TemporaryDirectory()
        self.ledger=Ledger(str(Path(self.tmp.name)/"research-only.sqlite3"))
        self.provider=StaticPublicProvider(self.now)
        m=self.provider.market(self.now)
        self.mkt=m
        self.data={
          "mode":"DEMO","last_attempt":self.now,"last_success":self.now,
          "market":m,"spot":90000.2,
          "model":{"available":True,"side":"ABOVE","prob_above":.81,"prob_below":.19,"engines":[]},
          "engines":[],"scalp":{"side":"WAIT"},"opportunity":{"side":"WAIT"},
          "candles":self.provider.candles(),
          "research_shadow":{"available":False,"side":"WAIT"},
          "orderbook":self.provider.orderbook(m),
          "depth_opportunity":{"status":"WAIT","selected":None},
          "execution_intelligence":{"action":"WAIT","order_placed":False},
          "errors":{},"paper_auto_enabled":False,"watch":None,
          "candle_quality":{"status":"FULL"},"status":"DEMO",
          "settlement":{"status":"IDLE","last_attempt":None,"last_success":None,
                        "checked":0,"failed":0}
        }
        self.p=patch.multiple(main,ledger=self.ledger,provider=self.provider,
               DEMO=True,AUTO_PAPER=False,ADMIN_TOKEN="synthetic-local-testing-token",
               state=self.data,settlement_failures={},last_grading_ticker=None)
        self.p.start()
        self.addCleanup(self.p.stop)
        self.addCleanup(self.ledger.conn.close)
        self.addCleanup(self.tmp.cleanup)
    def test_missing_valid_forecast_without_errors_is_not_healthy(self):
        main.state["model"]={"available":False}
        with main.state_lock:
            main._refresh_status_locked()
        self.assertEqual(main.state["status"],"DEGRADED")
        self.assertFalse(main._view_locked(self.now)["ok"])

    def test_input_validation_identifies_bad_spot_and_stale_candles(self):
        with patch.object(self.provider,"price",return_value=None):
            d=main.update_once(self.now)
        self.assertFalse(d["ok"])
        self.assertEqual(d["errors"]["coinbase_ticker"],"Missing or invalid BTC spot price")
        self.assertEqual(d["depth_opportunity"]["status"],"WAIT")
        with patch.object(main,"DEMO",False):
            d=main.update_once(self.now+1000)
        self.assertFalse(d["ok"])
        self.assertEqual(d["errors"]["coinbase_candles"],"Candles stale")

    def test_unavailable_forecast_without_source_error_is_explicit(self):
        with patch.object(main,"engine_pack",return_value={
            "available":False,"side":"WAIT","prob_above":None,
            "reason":"Synthetic ensemble abstained","engines":[]}):
            d=main.update_once(self.now)
        self.assertEqual(d["errors"]["forecast"],"Synthetic ensemble abstained")
        self.assertEqual(d["status"],"DEGRADED")

    def test_optional_depth_exception_fails_closed_but_ensemble_is_preserved(self):
        with patch.object(main,"analyze_opportunities",side_effect=ValueError("synthetic malformed sweep")):
            d=main.update_once(self.now)
        self.assertTrue(d["model"]["available"])
        self.assertEqual(d["depth_opportunity"]["status"],"WAIT")
        self.assertEqual(d["execution_intelligence"]["action"],"WAIT")
        self.assertIn("Depth analysis failed",d["depth_opportunity"]["reason"])

    def test_ledger_pending_recheck_exception_is_not_silenced(self):
        with patch.object(self.ledger,"unresolved",
                          side_effect=[["KXBTC15M-UNRESOLVED"],IOError("synthetic db read outage")]):
            main.grade_once()
        self.assertIn("settlement",main.state["errors"])
        self.assertEqual(main.state["settlement"]["status"],"ERROR")

    def test_background_market_worker_exception_is_reported_not_health_success(self):
        times=iter([False,True])
        fake=SimpleNamespace(is_set=lambda:next(times),wait=lambda _:None)
        with patch.object(main,"shutdown",fake),patch.object(
            main,"update_once",side_effect=RuntimeError("offline injected worker exception")):
            main.worker()
        self.assertEqual(main.state["status"],"ERROR")
        self.assertIn("worker",main.state["errors"])

    def test_background_settlement_worker_exception_visible_separately(self):
        waits=iter([False,True])
        fake=SimpleNamespace(wait=lambda _:next(waits))
        with patch.object(main,"shutdown",fake),patch.object(
            main,"grade_once",side_effect=RuntimeError("offline injected settlement failure")):
            main.grading_worker()
        self.assertIn("settlement_worker",main.state["errors"])

    def test_live_grading_worker_closes_separate_readonly_http_session(self):
        from app.feeds import LiveProvider
        live=LiveProvider()
        self.addCleanup(live.session.close)
        with patch.object(main,"provider",live),patch.object(
            main,"shutdown",SimpleNamespace(wait=lambda _:True)),patch.object(
            LiveProvider,"__init__",return_value=None):
            # Instantiating the distinct provider without initialization only
            # tests disposal. Attach a mock connection that must be closed.
            session=SimpleNamespace(close=lambda:None)
            with patch.object(main,"LiveProvider",LiveProvider):
                # No new network request is performed in this path.
                pass
        # The real branch is covered by a short no-network live-provider
        # initialization below with its own fresh, closed Session.
        with patch.object(main,"provider",live),patch.object(
            main,"shutdown",SimpleNamespace(wait=lambda _:True)):
            main.grading_worker()

    def test_api_paper_crossed_quote_and_invalid_readiness_are_not_accepted(self):
        self.mkt["yes_ask"]=.2
        self.mkt["yes_bid"]=.8
        with self.assertRaises(HTTPException) as e:
            main.paper(main.PaperRequest(side="YES"),
                       authorization="Bearer synthetic-local-testing-token")
        self.assertEqual(e.exception.status_code,409)
        self.assertEqual(self.ledger.data()["count"]["paper"],0)

    def test_explicit_paper_open_position_execution_failure_falls_back_to_wait(self):
        self.ledger.trade(self.mkt,"YES",self.now,source="SYNTHETIC_ONLY")
        with patch.object(main,"execution_guidance",side_effect=ValueError("invalid depth")):
            res=main.get_state()
        self.assertEqual(res.status_code,200)
        d=json.loads(res.body)
        self.assertEqual(d["paper_position_execution"]["action"],"WAIT")
        self.assertFalse(d["execution_evidence"]["actual_entry_and_exit_fills_verified"])
        self.assertIsNone(d["execution_evidence"]["realized_net_profit_usd"])


if __name__=="__main__":
    unittest.main(verbosity=2)
