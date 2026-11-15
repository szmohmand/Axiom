"""Read-only Hugging Face dataset manifest probe.

No source code from the dataset is executed; no AXIOM app imports,
credential usage, changes to trading runtimes, or automated market orders.
"""
import collections, json, urllib.request, urllib.error
from pathlib import Path

DATASET="KalshiEye/kalshi-order-book-sample"
BASE="https://huggingface.co/api/datasets/"+DATASET+"/tree/main?recursive=true&limit=1000"
HEADERS={"User-Agent":"AXIOM-isolated-research/0.1"}

def get(url, max_bytes=2_000_000):
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=45) as r:
        data=r.read(max_bytes+1)
    if len(data)>max_bytes:
        raise ValueError("Public dataset manifest exceeds safe response size")
    return data

def main():
    listed=json.loads(get(BASE))
    files=[{"path":x["path"],"size":x.get("size"),"type":x.get("type")}
           for x in listed if x.get("type")=="file"]
    print("BEGIN_KALSHIEYE_MANIFEST")
    print(json.dumps({
        "dataset":DATASET,
        "files":files,
        "families":dict(collections.Counter(
             x["path"].split("/")[1] for x in files
             if x["path"].startswith("kalshieye-data/"))),
        "data_bytes":sum(x.get("size") or 0 for x in files),
        "source_license":"CC BY-NC 4.0; non-commercial research only",
    },sort_keys=True,indent=2))
    print("END_KALSHIEYE_MANIFEST")
if __name__=="__main__":
    main()
