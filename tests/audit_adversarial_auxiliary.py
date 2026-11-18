"""Independent, offline adversarial audits for verification and provenance utilities.

No live requests, real credentials, real order placement or private exports.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phase0 import verify_transfer as vt
from phase0 import check_regression_history as cr
from research import verify_official_brti_live as b
from research_sources import collect_sources as c

TERMS={"ticker":"KXBTC15M-26NOV171800-00",
       "open_time":"2026-11-17T17:45:00Z","close_time":"2026-11-17T18:00:00Z",
       "floor_strike":"90000","expiration_value":"90100","status":"settled","result":"yes"}
NOW=1794950000

def ticks(m=TERMS):
    rows=[]
    for key,val in (("open_time","90000"),("close_time","90100")):
        end=b._seconds(m[key])
        rows.extend({"time":sec*1000,"value":val} for sec in range(end-60,end))
    return rows

class Session:
    def __init__(self):
        self.headers={}
        self.urls=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False

class VerifyExceptionalPaths(unittest.TestCase):
    def test_source_transfer_detects_tampering_missing_archive_missing_file_and_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            arc=root/"phase0/source_archives"
            arc.mkdir(parents=True)
            (root/"app").mkdir()
            original=b"print('frozen')\n"
            (root/"app/example.py").write_bytes(original)
            z=arc/"frozen.zip"
            def makezip(data=original):
                with zipfile.ZipFile(z,"w") as f:f.writestr("AXIOM_v2/app/example.py",data)
            makezip()
            sha=lambda data:hashlib.sha256(data).hexdigest()
            manifest={"transfer_base":"frozen.zip",
                      "source_artifacts":[{"type":"legacy_zip","filename":"frozen.zip","sha256":sha(z.read_bytes())}],
                      "transferred_files":[{"path":"app/example.py","sha256":sha(original),"original_sha256":sha(original)}]}
            (root/"phase0/transfer_manifest.json").write_text(json.dumps(manifest))
            with patch.object(vt.subprocess,"check_output",return_value=b""):
                self.assertEqual(vt.verify(root,require_archives=True),[])
                (root/".env").write_text("fake-test-not-a-secret")
                self.assertTrue(any("credential artifact" in e for e in vt.verify(root,require_archives=True)))
                (root/".env").unlink()
                with patch.object(vt.subprocess,"check_output",return_value=b"config/key.pem\x00"):
                    self.assertTrue(any("sensitive tracked path" in e for e in vt.verify(root,require_archives=True)))
                (root/"app/example.py").unlink()
                self.assertTrue(any("missing current source file" in e for e in vt.verify(root,require_archives=True)))
                (root/"app/example.py").write_bytes(original)
                makezip(b"print('tampered')\n")
                issues=vt.verify(root,require_archives=True)
                self.assertTrue(any("archive hash mismatch" in e for e in issues))
                self.assertTrue(any("source manifest mismatch" in e for e in issues))
                z.write_bytes(b"not-a-zip")
                self.assertTrue(any("source ZIP is invalid" in e for e in vt.verify(root,require_archives=True)))
                z.unlink()
                self.assertTrue(any("missing frozen ZIP" in e for e in vt.verify(root,require_archives=True)))
                makezip()
                # Explicitly declared source archive is recognized; an arbitrary
                # different byte stream cannot pass as the original ZIP.
                self.assertEqual(vt.verify(root,require_archives=True),[])

    def test_source_transfer_detects_wrong_optional_legacy_zip_hash(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            bad=Path(d)/"legacy.zip"
            bad.write_bytes(b"synthetic bad ZIP")
            issues=vt.verify(root,legacy_zip=bad,require_archives=True)
            self.assertTrue(any("legacy ZIP hash mismatch" in e for e in issues))

    def test_regression_checker_detects_all_safety_classes_without_touching_repo(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"tests").mkdir()
            (root/"tests/test_valid.py").write_text("def test_alive(): pass\n")
            h=root/"history.json"
            cases=[
              {"id":"A","finding":"one","fixed_commit":"abc","tests":["tests/test_valid.py::test_alive"]},
              {"id":"B","finding":"two","fixed_commit":"abc","tests":["tests/test_valid.py::test_removed"]},
              {"id":"C","finding":"three","fixed_commit":"abc","tests":["tests/absent.py::test_no"]},
              {"id":"D","finding":"four","fixed_commit":"abc","tests":["../outside.py::test_bad"]},
              {"id":"E","finding":"five","fixed_commit":"abc","tests":["tests/test_valid.py::other"]},
              {"id":"F","finding":"six","fixed_commit":"abc","tests":["no-delimiter"]},
              {"id":"G","finding":"seven","fixed_commit":"abc","tests":[]},
              {"id":"G","finding":"","fixed_commit":"","tests":["tests/test_valid.py::test_alive"]},
            ]
            h.write_text(json.dumps({"entries":cases}))
            with patch.object(cr,"ROOT",root),patch.object(cr,"HISTORY",h),patch.object(cr,"REQUIRED_HISTORICAL_IDS",["H99"]):
                issues=cr.check()
            for expected in ("regression test removed","regression test file removed","unsafe","malformed","Duplicate","missing finding","missing permanent test selectors","permanent regression record removed"):
                self.assertTrue(any(expected.lower() in issue.lower() for issue in issues),expected+" "+str(issues))
            (root/"tests/test_valid.py").write_text("def not_python(\n")
            h.write_text(json.dumps({"entries":[{"id":"A","finding":"f","fixed_commit":"c",
                          "tests":["tests/test_valid.py::test_alive"]}]}))
            with patch.object(cr,"ROOT",root),patch.object(cr,"HISTORY",h),patch.object(cr,"REQUIRED_HISTORICAL_IDS",[]):
                self.assertTrue(any("Cannot parse" in e for e in cr.check()))

    def test_brti_public_market_handles_404_pending_and_finalized_without_leakage(self):
        import requests
        class Response:
            def __init__(self,data=None,status=200):
                self.data=data
                self.status_code=status
                self.content=b"{}"
            def raise_for_status(self):
                if self.status_code>=400:
                    e=requests.HTTPError("simulated HTTP error")
                    e.response=self
                    raise e
            def json(self):return self.data
        class FakeSession:
            def __init__(self,responses):
                self.responses=list(responses)
                self.urls=[]
            def get(self,url,**kw):
                self.urls.append(url)
                return self.responses.pop(0)
        for first,second,expected in [
            (Response(status=404),Response({"market":TERMS}),"settled"),
            (Response({"market":{**TERMS,"status":"closed"}}),Response({"market":TERMS}),"settled"),
            (Response({"market":{**TERMS,"status":"closed"}}),Response(status=404),"closed"),
        ]:
            session=FakeSession([first,second])
            got=b._public_market(session,TERMS["ticker"])
            self.assertEqual(got["status"],expected)
            self.assertEqual(len(session.urls),2)
        self.assertIsNone(b._public_market(FakeSession([Response(status=404),Response(status=404)]),TERMS["ticker"]))
        with self.assertRaises(requests.HTTPError):
            b._public_market(FakeSession([Response(status=503)]),TERMS["ticker"])

    def test_brti_audit_invalid_listing_missing_fields_and_conflict(self):
        with patch.dict(os.environ,{"KALSHI_API_KEY_ID":"ephemeral-id","KALSHI_PRIVATE_KEY_PEM":"ephemeral-key"}),patch.object(
                b.requests,"Session",Session),patch("time.time",return_value=NOW):
            with patch.object(b,"_get",return_value={"markets":"bad"}):
                self.assertEqual(b.audit()["status"],"NOT_VERIFIED")
            with patch.object(b,"_get",return_value={"markets":[]}):
                self.assertEqual(b.audit()["status"],"NOT_VERIFIED")
            with patch.object(b,"_get",return_value={"markets":[TERMS]}),patch.object(
                    b,"_public_market",return_value=None):
                self.assertEqual(b.audit()["status"],"NOT_VERIFIED")
            with patch.object(b,"_get",return_value={"markets":[TERMS]}),patch.object(
                    b,"_public_market",return_value={**TERMS,"result":"no"}):
                self.assertEqual(b.audit()["status"],"CONFLICT")
            with patch.object(b,"_get",return_value={"markets":[TERMS]}),patch.object(
                    b,"_public_market",return_value={**TERMS,"floor_strike":None}):
                self.assertEqual(b.audit()["pending_official_fields"],[TERMS["ticker"]])
            with patch.object(b,"_get",return_value={"markets":[TERMS]}),patch.object(
                    b,"_public_market",return_value=TERMS),patch.object(
                    b,"_load_hours",return_value=(ticks()[:-1],["synthetic-hour"])):
                report=b.audit()
                self.assertEqual(report["status"],"PENDING_INDEX_PUBLICATION")
                self.assertEqual(report["pending_index_publication"][0]["closing_seconds"],59)
            with patch.object(b,"_get",return_value={"markets":[TERMS]}),patch.object(
                    b,"_public_market",return_value=TERMS),patch.object(
                    b,"_load_hours",return_value=(ticks(),["synthetic-hour"])):
                self.assertEqual(b.audit()["status"],"RECONCILED")
            with patch.object(b,"_get",return_value={"markets":[TERMS]}),patch.object(
                    b,"_public_market",return_value=TERMS),patch.object(
                    b,"_load_hours",side_effect=ValueError("synthetic source error")):
                self.assertEqual(b.audit()["status"],"SOURCE_ERROR")

    def test_brti_cli_status_output_and_unexpected_exception(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"sanitized.json"
            with patch.dict(os.environ,{"AXIOM_BRTI_EVIDENCE_PATH":str(out)}),patch.object(
                    b,"audit",return_value={"status":"RECONCILED","winner_verified":True}):
                self.assertEqual(b.main(),0)
                self.assertEqual(json.loads(out.read_text())["status"],"RECONCILED")
            with patch.dict(os.environ,{"AXIOM_BRTI_EVIDENCE_PATH":str(out)}),patch.object(
                    b,"audit",side_effect=RuntimeError("synthetic failure")):
                self.assertEqual(b.main(),2)
                self.assertEqual(json.loads(out.read_text())["status"],"SOURCE_ERROR")

    def test_public_collector_fetch_enforces_limit_and_token_origin(self):
        class Stream(io.BytesIO):pass
        seen=[]
        def fake_open(req,timeout=None):
            seen.append((req.full_url,req.headers))
            return Stream(b"ABCD")
        with patch.object(c.urllib.request,"urlopen",side_effect=fake_open),patch.dict(
                os.environ,{"GITHUB_TOKEN":"test-only-not-real"}):
            self.assertEqual(c.fetch("https://api.github.com/repos/x",max_bytes=5),b"ABCD")
            self.assertTrue(any("Authorization" in k for k in seen[-1][1]))
            self.assertEqual(c.fetch("https://gitlab.com/example",max_bytes=5),b"ABCD")
            self.assertFalse(any("Authorization" in k for k in seen[-1][1]))
            with self.assertRaises(ValueError):
                c.fetch("https://api.github.com/repos/x",max_bytes=2)

    def test_public_collector_retries_master_after_invalid_main_zip_and_reports_failure(self):
        blob=io.BytesIO()
        with zipfile.ZipFile(blob,"w") as z:
            for name in ("a/project.xcodeproj/project.pbxproj","a/package.json",
                         "a/Dockerfile","a/notebook.ipynb"):
                z.writestr(name,"synthetic")
        raw=blob.getvalue()
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            (out/"repositories").mkdir()
            with patch.object(c,"OUTPUT",out),patch.object(c,"fetch",side_effect=[b"bad",raw]):
                got=c.collect({"name":"Example","availability":"public_source",
                               "repository":"test/repo","url":"https://github.com/test/repo"})
            self.assertEqual(got["status"],"downloaded")
            self.assertEqual(got["branch"],"master")
            self.assertTrue("macOS/Xcode" in got["detected_stack"])
            with patch.object(c,"OUTPUT",out),patch.object(c,"fetch",side_effect=OSError("offline")):
                failed=c.collect({"name":"Example","availability":"public_source",
                                  "repository":"test/repo"})
            self.assertEqual(failed["status"],"download_failed")
            self.assertTrue("master" in failed["notes"])

if __name__=="__main__":
    unittest.main(verbosity=2)
