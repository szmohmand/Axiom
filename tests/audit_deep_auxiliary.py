"""Additional isolated exception-path audit: NO network, credentials or order calls.

Only invoked in audit branch's independent CI job; no production files change.
"""
from __future__ import annotations
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.execution_evidence import examine_liquidity
from app.settlement_reference import reconcile_contract
from phase0 import check_regression_history, verify_transfer
from research import verify_official_brti_live as b
from research_sources import collect_sources as c


class FakeResponse:
    def __init__(self, obj, *, size=4):
        self.obj = obj
        self.content = b" " * size
        self.status_code = 200
    def raise_for_status(self):
        return None
    def json(self):
        return self.obj


class DummySession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class AdditionalProofs(unittest.TestCase):
    def test_ed25519_and_rsa_signing_verify_using_ephemeral_generated_keys(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding
        for private in (ed25519.Ed25519PrivateKey.generate(),
                        rsa.generate_private_key(public_exponent=65537, key_size=2048)):
            pem = private.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()
            with patch("time.time", return_value=1794957700.5):
                h = b._signed_headers("test-id", pem, b.HISTORY_PATH)
            self.assertEqual(h["KALSHI-ACCESS-KEY"], "test-id")
            data = (h["KALSHI-ACCESS-TIMESTAMP"]+"GET"+b.HISTORY_PATH).encode()
            signature = base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"], validate=True)
            if isinstance(private, ed25519.Ed25519PrivateKey):
                private.public_key().verify(signature, data)
            else:
                private.public_key().verify(signature, data,
                    padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                salt_length=hashes.SHA256().digest_size),
                    hashes.SHA256())
        with self.assertRaises((ValueError,TypeError)):
            b._signed_headers("id", "not-a-real-PEM-key", b.HISTORY_PATH)

    def test_official_http_fetch_rejects_unknown_url_query_huge_or_non_json_response(self):
        s=DummySession([FakeResponse({"valid":True})])
        self.assertEqual(b._get(s,b.API+"/markets")["valid"],True)
        self.assertEqual(s.calls[0][1]["timeout"],(8,25))
        for url in ("https://example.com/not-kalshi",b.API+"/markets?api_key=oops",b.API):
            with self.assertRaises(ValueError):
                b._get(s,url)
        with patch.object(b,"MAX_BYTES",5):
            with self.assertRaises(ValueError):
                b._get(DummySession([FakeResponse({},size=7)]),b.API+"/markets")
        with self.assertRaises(ValueError):
            b._get(DummySession([FakeResponse(["not an object"])]),b.API+"/markets")

    def test_official_reference_walker_handles_nested_data_and_strict_utc(self):
        payload={"payload":{"data":[{"time":1000,"value":"90000"},{"time":1200,"value":"90001"}]}}
        self.assertEqual(list(b._walk_values(payload)),payload["payload"]["data"])
        self.assertEqual(list(b._walk_values({"history":[]})),[])
        with self.assertRaises(ValueError):
            b._seconds("2026-11-17T18:00:00")
        self.assertEqual(b._seconds("2026-11-17T18:00:00Z"),1794938400)

    def test_official_hour_request_uses_separate_utc_boundaries_and_only_signed_get(self):
        from datetime import datetime, timezone
        open_="2026-11-17T17:50:00Z"
        close="2026-11-17T18:05:00Z"
        market={"open_time":open_,"close_time":close}
        req=[]
        def fake_get(session,url,params=None,headers=None):
            req.append((url,params,headers))
            return {"payload":{"values":[{"time":1000,"value":90000}]}}
        with patch.object(b,"_get",side_effect=fake_get), patch.object(
            b,"_signed_headers",return_value={"synthetic":"non-secret"}):
            ticks,hours=b._load_hours(object(),"synthetic-id","synthetic-key",market)
        self.assertEqual(len(ticks),2)
        self.assertEqual(len(hours),2)
        self.assertTrue(all(url==b.HISTORY for url,_,_ in req))
        self.assertTrue(all(p["id"]=="BRTI" and p["timespan"]=="HOUR" for _,p,_ in req))
        self.assertTrue(all(h=={"synthetic":"non-secret"} for _,_,h in req))
        self.assertTrue(any("17:00" in t for t in hours))
        self.assertTrue(any("18:00" in t for t in hours))

    def test_missing_contract_and_malformed_ticks_fail_closed(self):
        self.assertFalse(reconcile_contract(None,[])["winner_verified"])
        terms={"ticker":"KXBTC15M-TEST","status":"settled","result":"yes",
               "open_time":"2026-11-17T17:45:00Z","close_time":"2026-11-17T18:00:00Z",
               "floor_strike":"90000","expiration_value":"90100"}
        for ticks in (None,{"not":"a list"},[{"time":True,"value":"90000"}],
                      [{"time":1000,"value":float("nan")}],[{"bad":"row"}]):
            result=reconcile_contract(terms,ticks)
            self.assertEqual(result["status"],"INCOMPLETE")
            self.assertFalse(result["winner_verified"])

    def test_malformed_liquidity_depth_does_not_look_like_real_execution(self):
        book={"available":True,"ticker":"KXBTC15M-TEST","received_at":1000,
              "asks":{"YES":[{"price":1.5,"size":10}],"NO":[]},
              "bids":{"YES":[],"NO":[]}}
        status=examine_liquidity(book,{"ticker":"KXBTC15M-TEST"},1002)
        self.assertEqual(status["book_replay_status"],"INVALID_BOOK")
        self.assertIsNone(status["realized_net_profit_usd"])
        self.assertEqual(status["authenticated_fill_records"],0)

    def test_auxiliary_collector_handles_nonpublic_files_and_offline_zip_without_execution(self):
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,"w") as z:
            z.writestr("example-main/requirements.txt","requests==2.32.5\n")
            z.writestr("example-main/README.md","Do not execute downloaded code\n")
        raw=archive.getvalue()
        self.assertEqual(c.safe_name(" ../dangerous/name?? "),".._dangerous_name")
        self.assertTrue("Python" in c.zip_type(raw)[0])
        nonpublic=c.collect({"name":"Private","availability":"private","url":"https://example.com"})
        self.assertEqual(nonpublic["status"],"not-public-original-source")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            output=root/"output"
            (output/"repositories").mkdir(parents=True)
            catalog=[{"name":"Example","availability":"public_source","repository":"example/repo",
                      "url":"https://github.com/example/repo"},
                     {"name":"Missing repo","availability":"public_source"},
                     {"name":"Closed","availability":"closed_source"}]
            (root/"full_catalog.json").write_text(json.dumps(catalog))
            (root/"full_catalog.csv").write_text("name\nExample\n")
            with patch.object(c,"ROOT",root),patch.object(c,"OUTPUT",output),patch.object(c,"fetch",return_value=raw):
                result=c.main()
            self.assertEqual(result,output/"ALL_PUBLIC_KALSHI_BOT_SOURCE.zip")
            self.assertTrue(result.exists())
            rows=json.loads((output/"collection_report.json").read_text())
            self.assertEqual({x["name"]:x["status"] for x in rows},
                             {"Example":"downloaded","Missing repo":"missing_repo_id",
                              "Closed":"not-public-original-source"})
            with zipfile.ZipFile(result) as z:
                self.assertIn("original_repositories/Example.zip",z.namelist())
                self.assertIn("meta/collection_report.json",z.namelist())

    def test_regression_inventory_checker_detects_missing_and_duplicate_entries(self):
        self.assertEqual(check_regression_history.check(),[])
        with tempfile.TemporaryDirectory() as tmp:
            history=Path(tmp)/"regressions.json"
            history.write_text('{"entries":[]}')
            with patch.object(check_regression_history,"HISTORY",history):
                self.assertIn("Regression history is empty",check_regression_history.check())
            history.write_text(json.dumps({"entries":[
              {"id":"H01","finding":"unit","fixed_commit":"sha",
               "tests":["tests/test_engine.py::test_probabilities_coherent"]},
              {"id":"H01","finding":"unit","fixed_commit":"sha",
               "tests":["tests/not_real.py::test_unknown"]}]}))
            with patch.object(check_regression_history,"HISTORY",history):
                errors=check_regression_history.check()
                self.assertTrue(any("Duplicate" in x for x in errors))
                self.assertTrue(any("removed" in x for x in errors))

    def test_original_archived_sources_remain_intact(self):
        repo=Path(__file__).resolve().parents[1]
        self.assertEqual(verify_transfer.verify(repo, require_archives=True),[])


if __name__=="__main__":
    unittest.main(verbosity=2)
