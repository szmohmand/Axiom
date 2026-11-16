"""Private original-source archive: KalshiEye 10-deep 1s historical Kalshi books.

Exactly Oct13 and Oct25 2026, two NON-CONSECUTIVE research samples.
Source is KalshiEye/kalshi-order-book-sample CC BY-NC 4.0. Check SHA256
against independent earlier source audit, then export both original Parquet
and filtered KXBTC15M CSV.GZ. Never claim true every-update L2 or full
month depth; these are 1-second snapshots (up to 10 levels per side).
"""
from __future__ import annotations
import csv,gzip,hashlib,json,os,pathlib,urllib.request
import pyarrow as pa,pyarrow.parquet as pq,pyarrow.compute as pc

URL="https://huggingface.co/datasets/KalshiEye/kalshi-order-book-sample/resolve/main/"
ROOT=pathlib.Path("kalshieye_orderbook_sample")
DAYS=("2026-10-13","2026-10-25")
FILES={
("2026-10-13","markets"):("kalshieye-data/markets/date=2026-10-13/markets-2026-10-13.parquet","3194445c2fa2a159dfe1bd930ca2f58208b7575ccd7718fb1418fb41ca9fcff3"),
("2026-10-13","settlements"):("kalshieye-data/settlements/date=2026-10-13/settlements-2026-10-13.parquet","9867e2ccb6a248e3d25d22d653f19c3c258e982b9b3e2abe5004063ce8923cec"),
("2026-10-13","bbo_1m"):("kalshieye-data/bbo_1m/date=2026-10-13/series=KXBTC15M/bbo_1m-KXBTC15M-2026-10-13.parquet","97de131ae574cfaca53804893e40c3b70b62bcb48ccc138f0f333b11e0a06a3e"),
("2026-10-13","book_snap_1s"):("kalshieye-data/book_snap_1s/date=2026-10-13/series=KXBTC15M/book_snap_1s-KXBTC15M-2026-10-13.parquet","7d4de4f3dd1d64c8393fa05d87d52232ba3d828e50d31e1bdfdab36d0dd37360"),
("2026-10-25","markets"):("kalshieye-data/markets/date=2026-10-25/markets-2026-10-25.parquet","1f2dd387a4044c79e0326b10d4ea757bf37e652d5ee12821e984961a73420eb8"),
("2026-10-25","settlements"):("kalshieye-data/settlements/date=2026-10-25/settlements-2026-10-25.parquet","5579fb1ebd05260a5efac58bc86f31024c22f0bb80470af4eb41d157b0ee99c3"),
("2026-10-25","bbo_1m"):("kalshieye-data/bbo_1m/date=2026-10-25/series=KXBTC15M/bbo_1m-KXBTC15M-2026-10-25.parquet","08de827bbb77c69c7878c25e109413be378d40b7a16ce5e49c7536351554c38f"),
("2026-10-25","book_snap_1s"):("kalshieye-data/book_snap_1s/date=2026-10-25/series=KXBTC15M/book_snap_1s-KXBTC15M-2026-10-25.parquet","d2bfa4186113eb39f66fe4c6c70407e85693d8d09e421acc234eb6bc76865872")}
def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()
def fetch(remote,out):
    out.parent.mkdir(parents=True,exist_ok=True)
    req=urllib.request.Request(URL+remote,headers={"User-Agent":"AXIOM-private-offline-research/1.0"})
    with urllib.request.urlopen(req,timeout=125) as src, open(out,"wb") as f:
        size=0
        while True:
            b=src.read(1<<20)
            if not b:break
            size+=len(b)
            if size>120_000_000:raise ValueError("source unexpectedly large")
            f.write(b)
def export_csv(p,day,family):
    tab=pq.read_table(p)
    if "series" in tab.column_names:
        tab=tab.filter(pc.equal(tab["series"],"KXBTC15M"))
    header=list(tab.column_names)
    out=ROOT/"CSV_RESEARCH"/f"KXBTC15M_{family}_{day}.csv.gz"
    out.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(out,"wt",newline="",encoding="utf8",compresslevel=4) as f:
        w=csv.writer(f);w.writerow(header)
        for batch in tab.to_batches(max_chunksize=10000):
            casted=[]
            for col in batch.columns:
                if pa.types.is_timestamp(col.type):col=col.cast(pa.int64())
                casted.append(col.to_pylist())
            for item in zip(*casted):w.writerow(item)
    return len(tab),str(out.relative_to(ROOT))
def main():
    ROOT.mkdir(exist_ok=True)
    result=[]
    for (day,family),(remote,expected_sha) in FILES.items():
        p=ROOT/"ORIGINAL_PROVIDER_PARQUET"/day/f"{family}-{day}.parquet"
        fetch(remote,p)
        h=digest(p)
        if h!=expected_sha:raise ValueError(f"publisher content fingerprint changed for {day} {family}")
        file=pq.ParquetFile(p)
        n,converted=export_csv(p,day,family)
        rec={"day":day,"family":family,
             "actual_sha256":h,"bytes":p.stat().st_size,
             "raw_rows":file.metadata.num_rows,
             "btc15m_export_rows":n,
             "original_path":str(p.relative_to(ROOT)),
             "csv_path":converted,
             "column_names":file.schema_arrow.names}
        result.append(rec)
        print("VERIFIED_KALSHI_EYE_ARCHIVE",json.dumps({
            "day":day,"family":family,"rows":n,"sha256":h}),flush=True)
    manifest={
      "publisher":"KalshiEye/kalshi-order-book-sample",
      "license":"CC BY-NC 4.0, NONCOMMERCIAL private research",
      "dates":"2026-10-13 and 2026-10-25 only (nonconsecutive, NOT a full month)",
      "source":"https://huggingface.co/datasets/KalshiEye/kalshi-order-book-sample",
      "verified_against":"separate earlier GitHub Actions schema-fingerprint run 43774135219",
      "files":result,
      "method":"Preserve original Parquet, convert BTC15m rows to gzip CSV preserving raw nanosecond timestamp integers",
      "limitations":[
       "Book is a 1-second recorder snapshot with up to ten price/size levels, NOT every exchange order event or original full-depth order book.",
       "Coverage includes documented recorder incidents; do not treat an outage as quiet market activity.",
       "Some source markets and settlements may be backfilled; original contract strike first-observed timestamp unverified.",
       "Spot quote rows include Coinbase, Kraken and Bitstamp but are NOT CF Benchmarks BRTI.",
       "Quote timestamp and venue timestamp differ; check feed latency before causal features or execution simulation.",
       "No per-order guaranteed execution or market-depth fill truth.",
       "Not a full-day BTC15m book coverage claim; consult incidents and observed span."
      ]}
    (ROOT/"MANIFEST_KALSHIEYE.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("KALSHIEYE_SOURCE_SUMMARY",json.dumps({
        "files":len(result),"book_snapshots":sum(x["btc15m_export_rows"] for x in result if x["family"]=="book_snap_1s"),
        "quote_minutes":sum(x["btc15m_export_rows"] for x in result if x["family"]=="bbo_1m")}),flush=True)
if __name__=="__main__":main()
