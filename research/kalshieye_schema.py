"""Inspect the actual KalshiEye parquet schema and source-dated values.

This code only reads published datasets; it does not execute downloaded code.
Outputs bounded schema, sorted clock span and 1 row per file, NOT raw source.
"""
import hashlib,json,os,sys,tempfile,urllib.request
from datetime import datetime
from pathlib import Path

DATASET="KalshiEye/kalshi-order-book-sample"
URL="https://huggingface.co/datasets/"+DATASET+"/resolve/main/"
FAMILIES=("spot","markets","settlements","bbo_1m","book_snap_1s")
DATES=("2026-10-13","2026-10-25")

def path_for(family,day):
    if family=="spot":
        return f"kalshieye-data/spot/date={day}/asset=BTC/spot-BTC-{day}.parquet"
    if family in ("markets","settlements"):
        return f"kalshieye-data/{family}/date={day}/{family}-{day}.parquet"
    return f"kalshieye-data/{family}/date={day}/series=KXBTC15M/{family}-KXBTC15M-{day}.parquet"

def download(path,cache=Path("/tmp/axiom-kalshieye")):
    cache.mkdir(exist_ok=True,parents=True)
    dest=cache / path.replace("/","__")
    if dest.exists():
        return dest
    req=urllib.request.Request(URL+path,headers={"User-Agent":"AXIOM-readonly-research/1.0"})
    with urllib.request.urlopen(req,timeout=120) as src, dest.open("wb") as out:
        total=0
        while True:
            data=src.read(1024*1024)
            if not data:break
            total+=len(data)
            if total>120_000_000:
                dest.unlink(missing_ok=True)
                raise ValueError("Too large for research probe: "+path)
            out.write(data)
    return dest

def source_schema():
    import pyarrow.parquet as pq
    report=[]
    for d in DATES:
        for family in FAMILIES:
            p=download(path_for(family,d))
            f=pq.ParquetFile(p)
            schema=f.schema_arrow
            names=[{"name":field.name,"type":str(field.type)} for field in schema]
            table=pq.read_table(p)
            data=table.slice(0,1).to_pylist()
            sample={}
            for k,v in data[0].items() if data else []:
                if isinstance(v,(str,int,float,bool,type(None))):
                    sample[k]=str(v)[:130]
                elif isinstance(v,datetime):
                    sample[k]=v.isoformat()
                else: sample[k]=str(v)[:200]
            hashes=hashlib.sha256(p.read_bytes()).hexdigest()
            result={"date":d,"family":family,"size_bytes":p.stat().st_size,
                    "sha256":hashes,"n":f.metadata.num_rows,"columns":names,
                    "first_row":sample,"file_path":path_for(family,d)}
            report.append(result)
            print("DATA_SCHEMA "+json.dumps(result,default=str),flush=True)
    print("BEGIN_SCHEMA_SUMMARY")
    print(json.dumps({"datasets":len(report),"files":report},default=str,sort_keys=True))
    print("END_SCHEMA_SUMMARY")

if __name__=="__main__":
    source_schema()
