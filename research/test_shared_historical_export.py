"""Read-only historical export regression tests; dependencies on ephemeral runner.

Does not call Kalshi, read real secrets or connect to the internet.
"""
from __future__ import annotations
import csv,gzip,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from research import export_shared_historical as E

class HistoricalExportTests(unittest.TestCase):
    def test_both_live_dollars_and_archived_unsuffixed_candle_schemas(self):
        live={
            "end_period_ts":1794528060,
            "yes_bid":{"open_dollars":"0.4500","high_dollars":"0.4600",
                       "low_dollars":"0.4400","close_dollars":"0.4550"},
            "yes_ask":{"open_dollars":"0.4800","high_dollars":"0.4900",
                       "low_dollars":"0.4700","close_dollars":"0.4850"},
            "price":{"open_dollars":"0.4600","close_dollars":"0.4750",
                     "mean_dollars":"0.4690"},
            "volume_fp":"185.50","open_interest_fp":"92.25",
        }
        archive={
            "end_period_ts":1794528120,
            "yes_bid":{"open":"0.45","close":"0.47"},
            "yes_ask":{"open":"0.49","close":"0.50"},
            "price":{"close":"0.49","mean":"0.48"},
            "volume":"100","open_interest":"30",
        }
        market={"open_time":"2026-11-13T00:00:00Z",
                "close_time":"2026-11-13T00:15:00Z"}
        def fake_json(path,params,auth=None):
            ticker=path.split("/")[-2]
            return {"candlesticks":[archive if ticker.endswith("ARCH") else live]}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            (out/"02_Kalshi_contracts").mkdir()
            with patch.object(E,"OUT",out),patch.object(E,"json_get",fake_json),patch.object(E.time,"sleep",lambda x:None):
                result=E.candle_sources({"KXBTC15M-LIVE":market,"KXBTC15M-ARCH":market})
            self.assertEqual(result["contracts_requested"],2)
            self.assertEqual(result["http_ok"],2)
            self.assertEqual(result["candle_rows"],2)
            self.assertEqual(result["errors_by_ticker"],{})
            with gzip.open(out/"02_Kalshi_contracts"/"yes_bid_ask_trade_1minute_candles.csv.gz","rt") as f:
                rows={r["ticker"]:r for r in csv.DictReader(f)}
            a=rows["KXBTC15M-LIVE"];c=rows["KXBTC15M-ARCH"]
            self.assertEqual(a["yes_bid_close"],"0.4550")
            self.assertEqual(a["yes_ask_close"],"0.4850")
            self.assertEqual(a["price_close"],"0.4750")
            self.assertEqual(a["volume"],"185.50")
            self.assertEqual(a["open_interest"],"92.25")
            self.assertEqual(c["yes_bid_close"],"0.47")
            self.assertEqual(c["yes_ask_close"],"0.50")
            self.assertEqual(c["price_mean"],"0.48")
            self.assertEqual(c["volume"],"100")

    def test_cannot_silently_accept_a_candle_with_no_bid_ask(self):
        m={"open_time":"2026-11-13T00:00:00Z",
           "close_time":"2026-11-13T00:15:00Z"}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);(out/"02_Kalshi_contracts").mkdir()
            with patch.object(E,"OUT",out),patch.object(E,"json_get",lambda *a,**kw:{
                "candlesticks":[{"end_period_ts":1794528060,"yes_bid":{},"yes_ask":{},"price":{}}]
            }),patch.object(E.time,"sleep",lambda x:None):
                result=E.candle_sources({"KXBTC15M-EMPTY":m})
            self.assertEqual(result["candle_rows"],0)
            self.assertIn("KXBTC15M-EMPTY",result["errors_by_ticker"])

    def test_benchmark_response_unwraps_only_historical_points(self):
        pts=list(E.walk_values({"data":{"payload":[
            {"time":1794528000000,"value":"71362.17"},
            {"time":1794528000200,"value":"71357.85"},
        ]}}))
        self.assertEqual(len(pts),2)
        self.assertEqual(float(pts[0]["value"]),71362.17)

if __name__=="__main__":
    unittest.main()
