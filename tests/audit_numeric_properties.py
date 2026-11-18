"""Deterministic adversarial numerical and property-invariant acceptance.

First run against frozen checkpoint is intentionally red for invalid
nonfinite/subsecond inputs. The expected final behavior is fail-closed:
NO probabilities, entry instructions, or trade returns invented.
"""
from __future__ import annotations
import contextlib
import io
import math
from pathlib import Path
import random
import runpy
import sys
import unittest
from unittest.mock import patch
from decimal import Decimal
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import engine,orderbook,settlement_research as shadow
from app.settlement_reference import reconcile_contract
from phase0 import check_regression_history
from research import verify_official_brti_live

NOW=1794938400
TICKER="KXBTC15M-AUDIT-NUMERIC"
def candles():
    out=[]
    for i in range(61):
        price=90000+math.sin(i*.73)*70+i*.3
        out.append({"t":NOW-61*60+i*60,"close":price,
                    "high":price+3,"low":price-3,"open":price})
    return out


class AdversarialNumberAndPropertyTests(unittest.TestCase):
    def test_nonfinite_model_inputs_fail_closed_without_false_signal(self):
        cs=candles()
        for args in ((float("nan"),90000,600),
                     (float("inf"),90000,600),
                     (90000,float("nan"),600),
                     (90000,float("inf"),600),
                     (90000,90000,float("nan")),
                     (90000,90000,float("inf"))):
            result=engine.volatility_forecast(*args,cs)
            self.assertFalse(result["available"],args)
            self.assertEqual(result["side"],"WAIT")

    def test_positive_subsecond_expiration_never_throws_or_produces_false_proxy(self):
        params={"target":90000,"seconds_left":5e-324}
        result=shadow.shadow_forecast_from_candles(candles(),params,NOW)
        self.assertFalse(result["available"])
        self.assertFalse(result["can_trigger_paper_or_orders"])

    def test_boolean_depth_receipt_cannot_masquerade_as_timestamp(self):
        payload={"orderbook_fp":{"yes_dollars":[["0.4","50"]],
                                 "no_dollars":[["0.4","50"]]}}
        with self.assertRaises(ValueError):
            orderbook.normalize_orderbook(payload,TICKER,True)
        book=orderbook.normalize_orderbook(payload,TICKER,1.5)
        book["received_at"]=True
        self.assertFalse(orderbook.current_book(book,TICKER,1.5))

    def test_malformed_official_tick_row_never_gets_a_verified_winner(self):
        contract={"ticker":TICKER,"status":"settled","result":"yes",
            "open_time":"2026-11-17T17:45:00Z",
            "close_time":"2026-11-17T18:00:00Z",
            "floor_strike":"90000","expiration_value":"90100"}
        result=reconcile_contract(contract,[None])
        self.assertEqual(result["status"],"INCOMPLETE")
        self.assertFalse(result["winner_verified"])

    def test_signer_rejects_supported_pem_format_but_wrong_key_family(self):
        from cryptography.hazmat.primitives.asymmetric import x25519
        from cryptography.hazmat.primitives import serialization
        key=x25519.X25519PrivateKey.generate()
        pem=key.private_bytes(serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode()
        with self.assertRaisesRegex(ValueError,"Only Kalshi RSA/Ed25519"):
            verify_official_brti_live._signed_headers("test",pem,
                              verify_official_brti_live.HISTORY_PATH)

    def test_regression_checker_command_line_failure_is_visible_and_nonzero(self):
        real_read=Path.read_text
        def fake_read(path,*a,**kw):
            if path.name=="REGRESSION_HISTORY.json":
                return '{"entries":[]}'
            return real_read(path,*a,**kw)
        with patch.object(Path,"read_text",new=fake_read),patch.object(
                 sys,"argv",["check_regression_history.py"]),contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as ex:
                runpy.run_path(str(Path(check_regression_history.__file__)),run_name="__main__")
        self.assertEqual(ex.exception.code,1)
        self.assertIn("FAIL:",out.getvalue())

    def test_seeded_one_thousand_orderbooks_have_no_negative_or_fabricated_sweep(self):
        r=random.Random(20261117)
        for _ in range(1000):
            yes_n=r.randint(0,5); no_n=r.randint(0,5)
            py=round(r.uniform(.05,.50),2); pn=round(r.uniform(.05,.45),2)
            yes=[[str(round(py-i*.01,2)),str(r.randint(1,100))] for i in range(yes_n)
                 if py-i*.01>0]
            no=[[str(round(pn-i*.01,2)),str(r.randint(1,100))] for i in range(no_n)
                 if pn-i*.01>0]
            b=orderbook.normalize_orderbook({"orderbook_fp":{"yes_dollars":yes,
                                                   "no_dollars":no}},TICKER,NOW)
            self.assertFalse(b["individual_orders_visible"])
            for side in ("YES","NO"):
                for action in ("BUY","SELL"):
                    needed=r.randint(1,500)
                    v=orderbook.sweep(b,side,action,needed)
                    self.assertTrue(v["simulated"])
                    self.assertLessEqual(v["available_contracts"],needed)
                    if v["complete"]:
                        self.assertEqual(v["available_contracts"],needed)
                    else:
                        self.assertLess(v["available_contracts"],needed)
                    self.assertFalse(v.get("actual_fill",False))
                spread=b["best"][side]["spread"]
                self.assertTrue(spread is None or spread>=0)

    def test_property_1000_model_inputs_reject_bad_data_without_unverified_trade_claim(self):
        r=random.Random(77182026)
        for i in range(1000):
            px=r.choice([float("nan"),float("inf"),-1.,0.,50000.,90000.,100000.])
            target=r.choice([float("nan"),float("inf"),0.,70000.,90000.,100001.])
            remaining=r.choice([-60,0,1,60,300,900,float("inf"),float("nan")])
            res=engine.volatility_forecast(px,target,remaining,candles())
            if not all(isinstance(n,(int,float)) and math.isfinite(n) and n>0 for n in (px,target,remaining)):
                self.assertFalse(res["available"],(i,px,target,remaining))
            self.assertFalse(res.get("verified_profit",False))


if __name__=="__main__":
    unittest.main(verbosity=2)
