"""Prepare a research-only, shareable Kalshi/BRTI/BTC historical dataset.

Output is a folder uploaded as ONE GitHub Actions artifact ZIP. The user's
private key and API identifier are never written, logged, or serialized.
All calls are GET and only public market endpoints or the authorized BRTI
historical endpoint. No trades, transfers, orders, account portfolio, bot
runtime, DB, or production operations.

The package is historical observation data, NOT claims of profitable trading.
"""
from __future__ import annotations
import csv,datetime as dt,gzip,hashlib,io,json,math,os,pathlib,sys,time
import urllib.error,urllib.parse,urllib.request,zipfile
from collections import Counter,defaultdict

API="https://external-api.kalshi.com/trade-api/v2"
PUBLIC="https://external-api.kalshi.com/trade-api/v2"
DATA="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/"
WINDOWS="https://huggingface.co/datasets/DegenHedge/kalshi-btc-15m/resolve/main/windows.csv"
EXPECTED_WINDOWS_SHA="9fd4f92f7b85038c825c7468e4e982ca17f7f4c4bb4cba75f1760f51262078d7"
REQUESTS_PER_SECOND=7
DEFAULT_DAYS=("2026-11-13","2026-11-14")
OUT=pathlib.Path("data_export")
HEADER={"User-Agent":"AXIOM-private-research-archive/1.0","Accept":"application/json"}

def get(url,headers=None,cap=25_000_000):
    for i in range(5):
        try:
            req=urllib.request.Request(url,headers=dict(HEADER,**(headers or {})),method="GET")
            with urllib.request.urlopen(req,timeout=50) as res:
                payload=res.read(cap+1)
                if len(payload)>cap:
                    raise ValueError("response size exceeds source safety limit")
                return payload
        except urllib.error.HTTPError as e:
            if e.code not in (429,502,503,504) or i==4:
                raise RuntimeError("GET blocked, HTTP="+str(e.code)) from None
        except (TimeoutError,urllib.error.URLError):
            if i==4:raise RuntimeError("source network timeout")
        time.sleep(min(8,2**i))
    raise AssertionError("unreachable")

def json_get(path,params=None,auth=None):
    url=API+path
    if params:url+="?"+urllib.parse.urlencode(params)
    raw=get(url,headers=auth,cap=30_000_000)
    val=json.loads(raw)
    if not isinstance(val,dict):raise ValueError("unexpected API JSON envelope")
    return val

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def walk_values(obj):
    if isinstance(obj,list):
        for v in obj:yield from walk_values(v)
    elif isinstance(obj,dict):
        if "time" in obj and "value" in obj:
            yield obj
        else:
            for k in ("data","payload","values","history","items","results"):
                if k in obj:yield from walk_values(obj[k])

def utc_ms(t):
    return dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).isoformat().replace("+00:00","Z")

def to_sec(v):
    if isinstance(v,(float,int)):return int(v)
    if isinstance(v,str):
        try:return int(dt.datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
        except ValueError: return None
    return None

def hour_iter(days):
    for day in days:
        base=dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc)
        for h in range(24):yield base+dt.timedelta(hours=h)

def brti_history(days,keyid,key):
    from research.brti_access_probe import sign_headers
    (OUT/"01_BRTI_official").mkdir(parents=True,exist_ok=True)
    p=OUT/"01_BRTI_official"/"brti_5hz_historical.csv.gz"
    hlog=[];raw_count=0;invalid=0;repeated=0;seen=set()
    min_time=None;max_time=None;first_sample=None
    with gzip.open(p,"wt",encoding="utf8",newline="",compresslevel=6) as out:
        w=csv.writer(out)
        w.writerow(["index_id","timestamp_utc","timestamp_ms","value_usd","source",
                    "request_utc_hour","point_available_at_request_not_original_receipt"])
        for idx,h in enumerate(hour_iter(days),1):
            timestamp=h.strftime("%Y-%m-%dT%H:00:00.000Z")
            path="/cfbenchmarks/history/values"
            params={"id":"BRTI","timespan":"HOUR","timestamp":timestamp}
            d=json_get(path,params,sign_headers(keyid,key,"GET","/trade-api/v2"+path))
            points=list(walk_values(d))
            accepted=0;dupes=0
            for pt in points:
                try:
                    ms=int(pt["time"]);val=float(pt["value"])
                except (ValueError,KeyError,TypeError):
                    invalid+=1;continue
                lo=int(h.timestamp())*1000
                if ms<lo or ms>=lo+3600000 or not(100<val<1_000_000) or not math.isfinite(val):
                    invalid+=1;continue
                if ms in seen:
                    dupes+=1;repeated+=1;continue
                seen.add(ms)
                w.writerow(["BRTI",utc_ms(ms),ms,format(val,".8f"),"Kalshi authenticated CF Benchmarks REST passthrough",timestamp,"true"])
                accepted+=1;raw_count+=1
                min_time=ms if min_time is None else min(min_time,ms)
                max_time=ms if max_time is None else max(max_time,ms)
                if first_sample is None:first_sample={"time":ms,"value":val}
            hlog.append({"hour_utc":timestamp,"returned":len(points),"accepted":accepted,"duplicates":dupes})
            if idx%6==0:print("BRTI_HOURS_DONE",idx,"POINTS",raw_count,flush=True)
            time.sleep(1/REQUESTS_PER_SECOND)
    summary={"source":"Kalshi authorized CF Benchmarks BRTI REST","hours_checked":len(hlog),
             "hours_with_points":sum(x["accepted"]>0 for x in hlog),
             "records":raw_count,"invalid":invalid,"duplicate_timestamps":repeated,
             "earliest_utc":utc_ms(min_time) if min_time else None,
             "latest_utc":utc_ms(max_time) if max_time else None,
             "hourly_coverage":hlog,"file":str(p)}
    return summary

def get_market_pages(days):
    (OUT/"02_Kalshi_contracts").mkdir(parents=True,exist_ok=True)
    start=min(days);end=(dt.date.fromisoformat(max(days))+dt.timedelta(days=1)).isoformat()
    begin=int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp())
    finish=int(dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc).timestamp())
    params={"series_ticker":"KXBTC15M","min_close_ts":begin,"max_close_ts":finish,"limit":1000}
    found={};cursor=None;page=0;maxpages=15
    for _ in range(maxpages):
        query=dict(params)
        if cursor:query["cursor"]=cursor
        obj=json_get("/markets",query)
        raw=obj.get("markets",[])
        if not isinstance(raw,list):raise ValueError("bad markets array")
        for m in raw:
            t=m.get("ticker")
            if isinstance(t,str) and t.startswith("KXBTC15M-"):found[t]=m
        page+=1
        newcursor=obj.get("cursor")
        if not newcursor or not raw:break
        if newcursor==cursor:raise ValueError("market paging did not advance")
        cursor=newcursor
        time.sleep(.2)
    if page==maxpages and cursor: raise RuntimeError("market-pagination truncated")
    out=OUT/"02_Kalshi_contracts"/"market_terms_and_official_outcomes.csv"
    keys=["ticker","event_ticker","status","result","floor_strike","open_time","close_time",
          "expected_expiration_time","latest_expiration_time","settlement_ts",
          "expiration_value","settlement_value_dollars","rules_primary",
          "yes_bid_dollars","yes_ask_dollars","no_bid_dollars","no_ask_dollars",
          "last_price_dollars","volume_fp","open_interest_fp","source"]
    valid={}
    with out.open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        for ticker,m in sorted(found.items()):
            a=to_sec(m.get("close_time"))
            if a is None or not(begin<=a<finish):continue
            valid[ticker]=m
            item={k:m.get(k) for k in keys}
            item["source"]="Kalshi official /markets response (queried after outcome)"
            w.writerow(item)
    return valid,{"market_pages":page,"returned_tickers":len(found),"in_range":len(valid),
                  "official_settled":sum(m.get("result") in ("yes","no") for m in valid.values()),
                  "file":str(out),"query_range_utc":[start,end]}

def candle_sources(markets):
    p=OUT/"02_Kalshi_contracts"/"yes_bid_ask_trade_1minute_candles.csv.gz"
    fields=["ticker","end_period_ts","end_period_utc","yes_bid_open","yes_bid_high",
            "yes_bid_low","yes_bid_close","yes_ask_open","yes_ask_high",
            "yes_ask_low","yes_ask_close","price_open","price_high","price_low",
            "price_close","price_mean","volume","open_interest","source"]
    ok=0;rows=0;bad=0;errors={};skipped=0
    with gzip.open(p,"wt",newline="",encoding="utf8",compresslevel=6) as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for idx,(ticker,m) in enumerate(sorted(markets.items()),1):
            begin=to_sec(m.get("open_time"));end=to_sec(m.get("close_time"))
            if begin is None or end is None:
                skipped+=1;continue
            series=urllib.parse.quote(ticker,safe="")
            path="/series/KXBTC15M/markets/"+series+"/candlesticks"
            params={"start_ts":begin-1800,"end_ts":end+120,"period_interval":1}
            try:
                data=json_get(path,params)
                cs=data.get("candlesticks",[])
                if not isinstance(cs,list):raise ValueError("non-array candlesticks")
                ok+=1
                for c in cs:
                    t=c.get("end_period_ts")
                    if not isinstance(t,(float,int)):bad+=1;continue
                    item={"ticker":ticker,"end_period_ts":int(t),
                          "end_period_utc":dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat(),
                          "source":"Kalshi official 1-minute candlestick endpoint"}
                    for node in ("yes_bid","yes_ask","price"):
                        v=c.get(node)
                        if isinstance(v,dict):
                            for key in ("open","high","low","close"):
                                # Active Kalshi candle fields use *_dollars;
                                # archived API fields may use unsuffixed names.
                                item[node+"_"+key]=v.get(key+"_dollars",
                                                             v.get(key))
                            if node=="price":
                                item["price_mean"]=v.get("mean_dollars",
                                                          v.get("mean"))
                    item["volume"]=c.get("volume_fp",c.get("volume"))
                    item["open_interest"]=c.get("open_interest_fp",c.get("open_interest"))
                    if not (item.get("yes_bid_close") or item.get("yes_ask_close")):
                        raise ValueError("historical candle lacks both market bid/ask; no silent blank-price rows")
                    w.writerow(item);rows+=1
            except Exception:
                errors[ticker]="data_unavailable_or_api_rejected"
            if idx%40==0:print("CONTRACT_CANDLE_REQUESTS_DONE",idx,"rows",rows,flush=True)
            time.sleep(.16)
    return {"contracts_requested":len(markets),"http_ok":ok,
            "candle_rows":rows,"invalid_time_rows":bad,"missing_market_times":skipped,
            "errors_by_ticker":errors,"file":str(p)}

def binance(days):
    folder=OUT/"03_BTC_spot_trade_klines";folder.mkdir(parents=True,exist_ok=True)
    p=folder/"binance_BTCUSDT_1minute_spot_trades.csv.gz"
    total=0;manifest=[]
    with gzip.open(p,"wt",newline="",encoding="utf8",compresslevel=6) as dst:
        w=csv.writer(dst)
        w.writerow(["timestamp_utc","timestamp_ms","open","high","low","close",
                    "base_volume_BTC","quote_volume_USDT","taker_buy_base_volume",
                    "trades","source"])
        for d in days:
            base=f"BTCUSDT-1m-{d}.zip"
            blob=get(DATA+base,cap=8_000_000)
            chk=get(DATA+base+".CHECKSUM",cap=800).decode().split()[0].lower()
            actual=hashlib.sha256(blob).hexdigest()
            if actual!=chk:raise ValueError("Binance archive checksum mismatch")
            z=zipfile.ZipFile(io.BytesIO(blob))
            if len(z.namelist())!=1:raise ValueError("Binance zip unexpected members")
            n=0
            with z.open(z.namelist()[0]) as f:
                for record in csv.reader(io.TextIOWrapper(f,encoding="utf8")):
                    if len(record)<11:raise ValueError("Binance candle incomplete")
                    ts=int(record[0])
                    # Binance archives may contain microsecond timestamps
                    ms=(ts//1000 if ts>10**14 else ts)
                    w.writerow([utc_ms(ms),ms,record[1],record[2],record[3],
                                record[4],record[5],record[7],record[9],record[8],
                                "Binance official BTCUSDT spot trades 1m OHLCV"])
                    n+=1;total+=1
            manifest.append({"day_utc":d,"zip_sha256":actual,"one_minute_rows":n})
    return {"rows":total,"days":manifest,"file":str(p)}

def source_historical_windows():
    out=OUT/"02_Kalshi_contracts"/"kalshi_BTC15m_windows_Jan_Oct_2026_publisher_archive.csv"
    raw=get(WINDOWS,cap=20_000_000)
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=EXPECTED_WINDOWS_SHA:
        raise ValueError("historical publisher CSV fingerprint changed")
    out.write_bytes(raw)
    rows=raw.count(b"\n")-1
    return {"rows_approx":rows,"source_url":WINDOWS,
            "publisher_file_sha256":digest,
            "source_note":"Third-party historical compilation; includes Kalshi outcomes and publisher-added metadata; original time-of-publication NOT independently verified.",
            "file":str(out)}

def main():
    from research.brti_access_probe import load_key
    days=tuple(os.getenv("RESEARCH_DATES","2026-11-13,2026-11-14").split(","))
    for d in days:dt.date.fromisoformat(d)
    if not(1<=len(days)<=4 and len(set(days))==len(days)):
        raise ValueError("Date list limited to 1-4 distinct days")
    OUT.mkdir(parents=True,exist_ok=True)
    secrets_present=bool(os.getenv("KALSHI_API_KEY_ID")) and bool(os.getenv("KALSHI_PRIVATE_KEY_PEM"))
    if not secrets_present:raise RuntimeError("missing secret inputs; no collection")
    # No secret contents in any output, including manifests.
    keyid=os.environ["KALSHI_API_KEY_ID"].strip()
    key,kind=load_key(os.environ["KALSHI_PRIVATE_KEY_PEM"])
    index=brti_history(days,keyid,key)
    markets,market_summary=get_market_pages(days)
    candles=candle_sources(markets)
    spot=binance(days)
    prior=source_historical_windows()
    if not markets or not candles["candle_rows"]:
        raise RuntimeError("No usable Kalshi markets or priced candles; reject incomplete export")
    if candles["errors_by_ticker"]:
        raise RuntimeError("At least one Kalshi market candle fetch failed; reject incomplete export")
    manifest={
        "package_name":"AXIOM_Shared_Kalshi_BRTI_Historical_Research",
        "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope_days_utc":list(days),
        "access_succeeded":{ "historical_cfbenchmarks_BRTI":index["records"]>0,
                              "Kalshi_15min_market_metadata":market_summary["in_range"]>0,
                              "Kalshi_bid_ask_1m_candles":candles["candle_rows"]>0,
                              "Binance_BTCUSDT_1min_trade_candles":spot["rows"]>0},
        "source_counts":{"brti":index,"kalshi_market_terms":market_summary,
                         "kalshi_yes_bid_ask_prices":candles,"spot":spot,
                         "past_publisher_kalshi_windows":prior},
        "files":{},
        "restrictions":[
            "Research-only private copy; check vendor redistribution rights before sharing outside your own work.",
            "BRTI is official CF Benchmarks historical tick feed via Kalshi. Data may be revised; timestamp is value time, not proof first availability to user.",
            "Kalshi historical outcome is official in per-market API when result is yes/no. Publisher compiled older file is separately labeled.",
            "Kalshi 1m bid/ask candle is historical summary, NOT fill-guaranteed executable quote or every order book update.",
            "Binance BTCUSDT is NOT BTC/USD or CF Benchmarks BRTI and cannot serve as official settlement.",
            "No API key ID, private key, signatures, auth headers, portfolio, or orders included.",
            "No intrasecond book depth; no artificial imputation or guessed price data.",
        ]
    }
    for p in OUT.rglob("*"):
        if p.is_file():
            manifest["files"][str(p.relative_to(OUT))]={
                "size_bytes":p.stat().st_size,"sha256":sha(p)}
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    readme=f"""# Shared BTC / Kalshi / BRTI Historical Research Package

Created: {manifest["created_utc"]}
Kalshi/BRTI dates (UTC): {', '.join(days)}
Verified BRTI observations: {index["records"]:,}
Kalshi BTC15m official market rows: {market_summary["in_range"]:,}
Kalshi 1-minute YES bid/ask/trade OHLC rows: {candles["candle_rows"]:,}
Binance BTCUSDT 1-minute OHLCV candles: {spot["rows"]:,}
Older third-party 2026 Kalshi contract-window CSV: approximately {prior["rows_approx"]:,} records.

## How another research thread should use the files

Read MANIFEST.json first. Preserve original ticker, UTC timestamp, source,
actual result and exact fields. Read .csv.gz with Python gzip / pandas / polars,
or decompress before loading into tools.

01_BRTI_official: authenticated historical CF Benchmarks BRTI price points
provided by Kalshi, 5Hz nominal. These are actual index observations, not
Binance/Coinbase estimated prices. Missing hours are explicitly recorded in
MANIFEST.json; no gap is interpolated. No source-side receipt timestamp is
known, and the feed may include revised data, so do not infer contemporaneous
availability from the historical event timestamp alone.

02_Kalshi_contracts:
- market_terms_and_official_outcomes.csv, per-contract strike, open/close,
  official result, expiration index value if provider supplied. The market
  `close_time` is the contract's 15m end; `expected_expiration_time`
  may be later administrative processing time. Listed yes_bid/ask snapshot
  fields were requested after settlement and MUST NOT be used as historical
  entry prices. Use timestamped 1-minute market candles below instead.
- yes_bid_ask_trade_1minute_candles.csv.gz, historical last bid/ask and
  traded-price OHLC, volume per minute. A bid/ask candle close is not a
  guarantee an order could be executed there.
- kalshi_BTC15m_windows_Jan_Oct_2026_publisher_archive.csv,
  older publisher-derived historical contract windows. Integrity fingerprint
  recorded, but originally published first-observation time not verified.

03_BTC_spot_trade_klines:
- Binance BTCUSDT spot 1-minute OHLCV, with published daily ZIP checksums.
  It is a different market/index; NEVER use it for official Kalshi settlement.

Critical: For BTC15m contracts consult the ORIGINAL contract terms, average
actual BRTI values over precisely the contract-defined 60-second opening and
closing intervals, and check original official outcome. Gaps or discrepancies
are unresolved and must be recorded—not filled with other price feeds.

Data provider documentation:
https://docs.kalshi.com/api-reference/
https://docs.cfbenchmarks.com/api/rest/historical-values/
https://data.binance.vision/
https://huggingface.co/datasets/DegenHedge/kalshi-btc-15m

The BRTI data was fetched via a read-only user-authorized API key.
Only source observations, not credentials or secret-dependent code, are
contained in this package. Do not republish without verifying provider terms.
"""
    (OUT/"README_FIRST.md").write_text(readme)
    print("RESEARCH_EXPORT_SUMMARY",json.dumps({
        "brti_ticks":index["records"],"markets":market_summary["in_range"],
        "prices_candles":candles["candle_rows"],
        "spot_bars":spot["rows"],"older_windows":prior["rows_approx"],
        "all_categories_nonempty":all(manifest["access_succeeded"].values()),
        "files":list(manifest["files"]),
        "errors_candle_requests":len(candles["errors_by_ticker"]),
    }),flush=True)

if __name__=="__main__":
    main()
