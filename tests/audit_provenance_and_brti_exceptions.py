"""Additional adversarial security and data-provenance cases, local-only.

The audit intentionally uses temporary paths, mock HTTP responses, and
ephemeral credentials; no external requests, actual index secrets, or orders.
"""
from __future__ import annotations
import base64
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phase0 import check_regression_history as hist, verify_transfer as transfer
from research import verify_official_brti_live as brti
from research_sources import collect_sources as collector


def zip_bytes(mapping):
    f=io.BytesIO()
    with zipfile.ZipFile(f,"w") as z:
        for name,payload in mapping.items():
            z.writestr(name,payload)
    return f.getvalue()


def fixture(root):
    a=root/"phase0"/"source_archives"
    a.mkdir(parents=True)
    original=b"immutable original text"
    zipped=zip_bytes({"AXIOM_v2/app/source.py":original})
    (a/"original.zip").write_bytes(zipped)
    (root/"app").mkdir()
    (root/"app/source.py").write_bytes(original)
    manifest={
        "transfer_base":"original.zip",
        "source_artifacts":[{"type":"research_report","filename":"other.pdf"},
                            {"type":"legacy_zip","filename":"original.zip",
                             "sha256":hashlib.sha256(zipped).hexdigest()}],
        "transferred_files":[{"path":"app/source.py","sha256":hashlib.sha256(original).hexdigest(),
                              "original_sha256":hashlib.sha256(original).hexdigest()}],
    }
    (root/"phase0/transfer_manifest.json").write_text(json.dumps(manifest))
    return manifest


def response_error(status):
    r=requests.Response();r.status_code=status
    return requests.HTTPError(f"source returned {status}",response=r)


class FakeSession:
    def __init__(self):
        self.headers={}
    def __enter__(self):
        return self
    def __exit__(self,*a):
        return False


class HardeningAdversarialChecks(unittest.TestCase):
    def test_regression_checker_rejects_missing_invalid_and_malformed_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"tests").mkdir()
            (root/"tests/test_valid.py").write_text("def test_good():\n    assert True\n")
            (root/"tests/test_bad.py").write_text("def test_bad(:\n")
            p=root/"regression_history.json"
            cases=[
                {"id":"H01","finding":"","fixed_commit":"","tests":[]},
                {"id":"H01","finding":"exists","fixed_commit":"sha",
                 "tests":[43,"invalid","/tmp/root.py::test_a",
                          "tests/../not_safe.py::test_a",
                          "tests/a.txt::test_a","other/x.py::test_a",
                          "tests/test_valid.py::wrong",
                          "tests/test_missing.py::test_absent",
                          "tests/test_bad.py::test_broken",
                          "tests/test_valid.py::test_not_present",
                          "tests/test_valid.py::test_good"]},
            ]
            p.write_text(json.dumps({"entries":cases}))
            with patch.object(hist,"ROOT",root),patch.object(hist,"HISTORY",p):
                errors=hist.check()
            self.assertTrue(any("Duplicate" in x for x in errors),errors)
            self.assertTrue(any("missing finding or commit" in x for x in errors))
            self.assertTrue(any("malformed selector" in x for x in errors))
            self.assertTrue(any("unsafe or invalid" in x for x in errors))
            self.assertTrue(any("regression test file removed" in x for x in errors))
            self.assertTrue(any("Cannot parse" in x for x in errors))
            self.assertTrue(any("regression test removed" in x for x in errors))
            self.assertTrue(any("permanent regression record removed" in x for x in errors))

    def test_regression_checker_detects_valid_fixture_and_main_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"regression_history.json"
            p.write_text(json.dumps({"entries":[{"id":ident,"finding":"tested","fixed_commit":"sha",
                          "tests":["tests/test_engine.py::test_probabilities_coherent"]}
                          for ident in hist.REQUIRED_HISTORICAL_IDS]}))
            with patch.object(hist,"HISTORY",p):
                self.assertEqual(hist.check(),[])
            capture=io.StringIO()
            with contextlib.redirect_stdout(capture),patch.object(sys,"argv",["check_regression_history.py"]):
                runpy.run_path(str(Path(hist.__file__)),run_name="__main__")
            self.assertIn("permanent regression",capture.getvalue())
            self.assertIn("PASS:",capture.getvalue())

    def test_frozen_archive_verifier_reports_missing_corrupt_and_wrong_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=fixture(root);a=root/"phase0/source_archives/original.zip"
            self.assertEqual(transfer.verify(root,require_archives=True),[])
            a.unlink()
            self.assertTrue(any("missing frozen ZIP" in x for x in
                                transfer.verify(root,require_archives=True)))
            a.write_bytes(b"definitely-not-a-zip")
            manifest["source_artifacts"][-1]["sha256"]=hashlib.sha256(a.read_bytes()).hexdigest()
            (root/"phase0/transfer_manifest.json").write_text(json.dumps(manifest))
            self.assertTrue(any("source ZIP is invalid" in x for x in
                                transfer.verify(root,require_archives=True)))
            manifest["source_artifacts"][-1]["sha256"]="wrong-sha"
            (root/"phase0/transfer_manifest.json").write_text(json.dumps(manifest))
            self.assertTrue(any("archive hash mismatch" in x for x in
                                transfer.verify(root,require_archives=True)))

    def test_transfer_missing_source_entry_wrong_original_and_untracked_sensitivity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=fixture(root);a=root/"phase0/source_archives/original.zip"
            a.write_bytes(zip_bytes({"AXIOM_v2/some_other.py":b"not original"}))
            m["source_artifacts"][-1]["sha256"]=hashlib.sha256(a.read_bytes()).hexdigest()
            (root/"phase0/transfer_manifest.json").write_text(json.dumps(m))
            self.assertTrue(any("missing file in frozen" in x for x in
                                transfer.verify(root)))
            a.write_bytes(zip_bytes({"AXIOM_v2/app/source.py":b"changed original"}))
            m["source_artifacts"][-1]["sha256"]=hashlib.sha256(a.read_bytes()).hexdigest()
            (root/"phase0/transfer_manifest.json").write_text(json.dumps(m))
            self.assertTrue(any("source manifest mismatch" in x for x in
                                transfer.verify(root)))
            (root/"app/source.py").unlink()
            self.assertTrue(any("missing current source file" in x for x in transfer.verify(root)))
            (root/".env").write_text("synthetic=1")
            with patch.object(transfer.subprocess,"check_output",return_value=
                              b"\0.env\0config/my.pem\0config/private.key\0safe.txt\0"):
                errors=transfer.verify(root)
            self.assertTrue(any("credential artifact" in x for x in errors))
            self.assertTrue(any("sensitive tracked path" in x for x in errors))

    def test_transfer_nonarchive_git_missing_and_legacy_zip_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            other=root/"bad-original.zip";other.write_bytes(b"bad")
            with patch.object(transfer.subprocess,"check_output",side_effect=FileNotFoundError):
                result=transfer.verify(root,legacy_zip=other,require_archives=True)
            self.assertEqual(len(result),1)
            self.assertIn("legacy ZIP hash mismatch",result[0])

    def test_transfer_cli_main_success_and_failure_using_synthetic_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            with patch.object(sys,"argv",["verify_transfer.py","--checkout",str(root),"--require-archives"]):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    runpy.run_path(str(Path(transfer.__file__)),run_name="__main__")
                self.assertIn("PASS:",output.getvalue())
            (root/"phase0/source_archives/original.zip").unlink()
            with patch.object(sys,"argv",["verify_transfer.py","--checkout",str(root),"--require-archives"]):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    with self.assertRaises(SystemExit) as caught:
                        runpy.run_path(str(Path(transfer.__file__)),run_name="__main__")
                self.assertEqual(caught.exception.code,1)
                self.assertIn("FAIL:",output.getvalue())

    def test_index_historical_lookup_handles_not_found_missing_final_and_http_500(self):
        ticker="KXBTC15M-SYNTHETIC-001"
        with patch.object(brti,"_get",side_effect=[response_error(404),{"market":{"status":"settled","result":"no"}}]):
            result=brti._public_market(object(),ticker)
            self.assertEqual(result["result"],"no")
        with patch.object(brti,"_get",side_effect=[{},{}]):
            self.assertIsNone(brti._public_market(object(),ticker))
        with patch.object(brti,"_get",side_effect=[{"market":{"status":"closed","result":"yes"}},
                                                     {"market":{"status":"closed","result":"yes"}}]):
            self.assertEqual(brti._public_market(object(),ticker)["status"],"closed")
        with patch.object(brti,"_get",side_effect=response_error(500)):
            with self.assertRaises(requests.HTTPError):
                brti._public_market(object(),ticker)

    def test_missing_index_auth_and_api_payload_never_produces_verified_win(self):
        with patch.dict(os.environ,{"KALSHI_API_KEY_ID":"","KALSHI_PRIVATE_KEY_PEM":""}):
            r=brti.audit()
            self.assertEqual(r["status"],"NOT_VERIFIED")
        with patch.dict(os.environ,{"KALSHI_API_KEY_ID":"fake","KALSHI_PRIVATE_KEY_PEM":"fake"}):
            with patch.object(brti.requests,"Session",return_value=FakeSession()):
                with patch.object(brti,"_get",return_value={"markets":"not-a-list"}):
                    self.assertEqual(brti.audit()["status"],"NOT_VERIFIED")
                with patch.object(brti,"_get",return_value={"markets":[]}):
                    self.assertEqual(brti.audit()["status"],"NOT_VERIFIED")

    def test_index_audit_skips_recent_and_old_contracts_missing_fields(self):
        clock=1794957700
        def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
        recent={"ticker":"KXBTC15M-VERYRECENT","result":"yes","close_time":iso(clock-40)}
        old={"ticker":"KXBTC15M-OLD","result":"yes","close_time":iso(clock-4*86400)}
        middle={"ticker":"KXBTC15M-FIELD","result":"yes","close_time":iso(clock-600)}
        listing={"markets":[recent,old,middle]}
        with patch.dict(os.environ,{"KALSHI_API_KEY_ID":"test","KALSHI_PRIVATE_KEY_PEM":"test"}):
            with patch.object(brti.requests,"Session",return_value=FakeSession()),patch.object(
                brti,"_get",return_value=listing),patch.object(brti.time if hasattr(brti,"time") else __import__("time"),"time",return_value=clock):
                with patch.object(brti,"_public_market",return_value={"ticker":middle["ticker"],
                       "result":"yes","status":"settled","open_time":iso(clock-1500),
                       "close_time":iso(clock-600),"floor_strike":None}):
                    r=brti.audit()
        self.assertEqual(r["status"],"NOT_VERIFIED")
        self.assertEqual(r["pending_official_fields"],[middle["ticker"]])
        self.assertEqual(r["tried_contracts"],1)

    def test_index_audit_conflict_source_exception_and_missing_detail(self):
        clock=1794957700
        close=datetime.fromtimestamp(clock-600,timezone.utc).isoformat()
        active={"ticker":"KXBTC15M-TEST","close_time":close,"result":"yes"}
        with patch.dict(os.environ,{"KALSHI_API_KEY_ID":"test","KALSHI_PRIVATE_KEY_PEM":"test"}),patch.object(
            brti.requests,"Session",return_value=FakeSession()),patch.object(
            brti,"_get",return_value={"markets":[active]}),patch("time.time",return_value=clock):
            with patch.object(brti,"_public_market",return_value=None):
                r=brti.audit();self.assertEqual(r["status"],"NOT_VERIFIED")
            with patch.object(brti,"_public_market",return_value={
                "ticker":active["ticker"],"status":"settled","result":"no"}):
                r=brti.audit()
                self.assertEqual(r["status"],"CONFLICT")
            with patch.object(brti,"_public_market",side_effect=response_error(429)):
                r=brti.audit()
                self.assertEqual(r["status"],"SOURCE_ERROR")

    def test_index_audit_main_serializes_sanitized_success_and_error_without_leaking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/"summary.json")
            with patch.dict(os.environ,{"AXIOM_BRTI_EVIDENCE_PATH":path}):
                with patch.object(brti,"audit",return_value={"status":"RECONCILED",
                    "reason":"synthetic-only"}),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(brti.main(),0)
                self.assertEqual(json.loads(Path(path).read_text())["status"],"RECONCILED")
                with patch.object(brti,"audit",side_effect=RuntimeError("secret must not be echoed")):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(brti.main(),2)
                evidence=json.loads(Path(path).read_text())
                self.assertEqual(evidence["status"],"SOURCE_ERROR")
                self.assertNotIn("secret must not be echoed",json.dumps(evidence))
        with patch.dict(os.environ,{"KALSHI_API_KEY_ID":"","KALSHI_PRIVATE_KEY_PEM":""}):
            with patch.object(sys,"argv",["verify_official_brti_live.py"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as e:
                        runpy.run_path(str(Path(brti.__file__)),run_name="__main__")
                self.assertEqual(e.exception.code,2)

    def test_public_source_fetch_caps_bytes_and_scopes_optional_github_token(self):
        class Stream:
            def __init__(self,blocks):self.blocks=list(blocks)
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self,_):return self.blocks.pop(0) if self.blocks else b""
        seen=[]
        def urlopen(request,timeout):
            seen.append(request)
            return Stream([b"123",b"456",b""])
        with patch.object(collector.urllib.request,"urlopen",side_effect=urlopen):
            with patch.dict(os.environ,{"GITHUB_TOKEN":"mock-token-not-real"}):
                data=collector.fetch("https://api.github.com/repos/safe/list",max_bytes=6)
                self.assertEqual(data,b"123456")
                self.assertEqual(seen[-1].get_header("Authorization"),"Bearer mock-token-not-real")
                collector.fetch("https://example.com/public",max_bytes=6)
                self.assertIsNone(seen[-1].get_header("Authorization"))
                with self.assertRaises(ValueError):
                    collector.fetch("https://api.github.com/repos/safe/list",max_bytes=5)

    def test_source_collector_detects_stacks_and_fails_cleanly_with_bad_archives(self):
        multi=zip_bytes({"sample.xcodeproj/project.pbxproj":b"","setup.py":b"",
                         "package.json":b"{}","Dockerfile":b"FROM scratch","README.ipynb":b""})
        stacks,_=collector.zip_type(multi)
        self.assertIn("macOS/Xcode",stacks)
        self.assertIn("Node/JS",stacks)
        self.assertIn("Docker",stacks)
        self.assertIn("Notebook",stacks)
        self.assertEqual(collector.zip_type(zip_bytes({"README.md":b"nothing"}))[0],"Inspect README")
        with patch.object(collector,"fetch",return_value=b"invalid-not-zip"):
            error=collector.collect({"name":"Invalid public archive","availability":"public_source",
                                     "repository":"a/b"})
        self.assertEqual(error["status"],"download_failed")
        self.assertIn("main:",error["notes"])
        self.assertIn("master:",error["notes"])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"repositories").mkdir()
            with patch.object(collector,"OUTPUT",root),patch.object(collector,"fetch",return_value=multi):
                fetched=collector.collect({"name":"GitLab mirrored source","availability":"public_source_gitlab",
                                           "repository":"somegroup%2Frepo"})
            self.assertEqual(fetched["branch"],"default")
            self.assertTrue((root/"repositories"/fetched["filename"]).exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
