"""Private research export of official 5Hz BRTI and lossless 1Hz sampling.

Standalone one-shot cloud runner, fully read-only authenticated GET requests;
never writes credentials, signatures, auth headers, user portfolio, or orders.
Scope: 30 consecutive complete UTC days 2026-10-17 through 2026-11-15
plus 2026-10-16T23:00Z BRTI pre-window warmup.
Original 5Hz feed retained as 30 daily .csv.gz files; separate first-tick
per-second reconstruction and hourly coverage diagnostics.
"""
from __future__ import annotations
import csv,datetime as dt,gzip,hashlib,json,math,os,pathlib,time
from collections import Counter
from research.export_shared_historical import json_get,walk_values
from research.brti_access_probe import load_key,sign_headers

ROOT=pathlib.Path("extended_BRTI")
INDEX_DIR=ROOT/"BRTI_5HZ_ORIGINAL"
BEGIN=dt.datetime(2026,10,17,tzinfo=dt.timezone.utc)
END=dt.datetime(2026,11,16,tzinfo=dt.timezone.utc)
FIRST_HOUR=BEGIN-dt.timedelta(hours=1)
UTC=dt.timezone.utc
def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for piece in iter(lambda:f.read(1024*1024),b""):
            h.update(piece)
    return h.hexdigest()

def iter_hours():
    x=FIRST_HOUR
    while x<END:
        yield x
        x+=dt.timedelta(hours=1)

def run():
    INDEX_DIR.mkdir(parents=True,exist_ok=True)
    (ROOT/"AUDIT").mkdir(exist_ok=True)
    keyid=os.environ["KALSHI_API_KEY_ID"].strip()
    key,_=load_key(os.environ["KALSHI_PRIVATE_KEY_PEM"])
    p="/cfbenchmarks/history/values"
    day_writer=None
    day_file=None
    active_day=None
    byday=[]
    hour_log=[]
    raw_total=0
    one_second_total=0
    anomalies=Counter()
    prior_ms=-1
    prior_sec=-1
    one_path=ROOT/"BRTI_1S_first_tick_every_second.csv.gz"
    with gzip.open(one_path,"wt",encoding="utf8",newline="",compresslevel=4) as out_sec:
        persecond=csv.writer(out_sec)
        persecond.writerow(["index_id","timestamp_utc","epoch_second","first_tick_timestamp_ms",
            "BRTI_USD_first_tick_in_second","reconstruction_rule","historical_source"])
        try:
            for ix,hour in enumerate(iter_hours(),1):
                timestamp=hour.strftime("%Y-%m-%dT%H:00:00.000Z")
                day=hour.date().isoformat()
                if day!=active_day:
                    if day_file is not None:
                        day_file.close()
                    active_day=day
                    fp=INDEX_DIR/("BRTI_5HZ_"+day+".csv.gz")
                    day_file=gzip.open(fp,"wt",newline="",encoding="utf8",compresslevel=4)
                    day_writer=csv.writer(day_file)
                    day_writer.writerow(["index_id","timestamp_utc","timestamp_ms","BRTI_USD","source"])
                result=json_get(p,{"id":"BRTI","timespan":"HOUR","timestamp":timestamp},
                    sign_headers(keyid,key,"GET","/trade-api/v2"+p))
                # "data" envelope can change; trust only actual time/value objects
                # after strict numeric/time checks and source-hour boundaries.
                lo=int(hour.timestamp())*1000;hi=lo+3600000
                n=0;seconds=0;errors=0
                for obj in walk_values(result):
                    try:ms=int(obj["time"]);price=float(obj["value"])
                    except (ValueError,TypeError,KeyError):
                        errors+=1;continue
                    if not (lo<=ms<hi and 100<price<1_000_000 and math.isfinite(price)):
                        errors+=1;continue
                    if ms<=prior_ms:raise ValueError("BRTI original feed chronology violated")
                    prior_ms=ms
                    utc=dt.datetime.fromtimestamp(ms/1000,UTC).isoformat(timespec="milliseconds").replace("+00:00","Z")
                    day_writer.writerow(["BRTI",utc,ms,format(price,".8f"),"CF_Benchmarks_index_via_Kalshi"])
                    n+=1;raw_total+=1
                    sec=ms//1000
                    if sec!=prior_sec:
                        if sec<prior_sec:raise ValueError("BRTI second order violated")
                        prior_sec=sec
                        w=dt.datetime.fromtimestamp(sec,UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                        persecond.writerow(["BRTI",w,sec,ms,format(price,".8f"),
                            "first tick as received in historical archive during second",
                            "CF_Benchmarks_index_via_Kalshi"])
                        one_second_total+=1;seconds+=1
                hour_log.append({"hour":timestamp,"raw_ticks":n,"first_ticks_per_second":seconds,
                                "rejected":errors,"complete_5hz":n==18000,
                                "complete_seconds":seconds==3600})
                anomalies["hours_with_no_ticks"]+=int(n==0)
                anomalies["hours_not_exactly_18000"]+=int(n!=18000)
                anomalies["rejected_points"]+=errors
                if ix%24==0:
                    print("BRTI_EXPORT_DAY_BATCH",ix//24,"of",31,
                        "ticks",raw_total,"seconds",one_second_total,flush=True)
                time.sleep(.03)
        finally:
            if day_file is not None:
                day_file.close()
    files={}
    for pth in ROOT.rglob("*"):
        if pth.is_file():
            files[str(pth.relative_to(ROOT))]={"sha256":sha(pth),"size_bytes":pth.stat().st_size}
    start=int(FIRST_HOUR.timestamp())
    finish=int(END.timestamp())
    manifest={
       "provider":"CF Benchmarks BRTI official historical values via user-authorized read-only Kalshi REST",
       "utc_complete_days_covered_from":"2026-10-17",
       "utc_complete_days_covered_through":"2026-11-15",
       "includes_extra_hour_preopening_warmup":"2026-10-16T23:00:00Z",
       "historical_price_sample_interval_seconds":0.2,
       "expected_5hz_ticks_per_complete_hour":18000,
       "hours_requested":len(hour_log),
       "5hz_ticks_exported":raw_total,
       "first_tick_1hz_samples":one_second_total,
       "coverage_issues":dict(anomalies),
       "hours_summary":hour_log,
       "files":files,
       "never_included":["private_key","API_key_ID","signature","portfolio","order","personal_identity"],
       "limitations":[
        "Historical archive event timestamp is not proof BRTI was delivered to a trader by that time.",
        "First BRTI tick each second is the deterministic 1Hz research reconstruction policy, not a documented official guarantee that these are the exact settlement samples.",
        "No interpolation; gaps stay observable in both the tick files and coverage manifest.",
        "Provider re-distribution rules may restrict public posting; private user-owned library research only.",
        "Final 60-second averages and contract outcomes require a separate verified Kalshi contract index for exact identities."
       ]
    }
    (ROOT/"AUDIT"/"BRTI_30DAY_MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("OFFICIAL_BRTI_EXPORT_SUMMARY",json.dumps({
       "hours":len(hour_log),"original_5hz_ticks":raw_total,
       "reconstructed_1hz_samples":one_second_total,
       "noncomplete_hours":anomalies["hours_not_exactly_18000"],
       "output_files":len(files)}),flush=True)
    if anomalies["hours_with_no_ticks"]>1:
       print("WARNING_BRTI_HOURS_MISSING",anomalies["hours_with_no_ticks"],flush=True)

if __name__=="__main__":run()
