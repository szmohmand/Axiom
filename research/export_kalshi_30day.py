"""30 consecutive days KXBTC15M official terms, 1m quote candles and trades.

All interactions are GET with the public Kalshi market API. Historic
end-of-period OHLC is NOT an exact executable order-book quote. Market's
post-settlement YES/NO bid/ask fields are never interpreted as past prices.
Historical NO book quotes at minute resolution are *theoretically derived*
as (1-YES bid) and (1-YES ask); not independently observed depth.
"""
import collections,csv,datetime as dt,gzip,hashlib,json,math,os,pathlib,time
from research.export_shared_historical import json_get

ROOT=pathlib.Path("extended_KALSHI")
OUT=ROOT/"KALSHI"
BEGIN=dt.datetime(2026,10,17,tzinfo=dt.timezone.utc)
END=dt.datetime(2026,11,16,tzinfo=dt.timezone.utc)
LO=int(BEGIN.timestamp());HI=int(END.timestamp())
TICKER_PREFIX="KXBTC15M-"
PUBLIC_TRADE_SAMPLE_BEGIN=int(dt.datetime(2026,11,13,tzinfo=dt.timezone.utc).timestamp())
PUBLIC_TRADE_SAMPLE_END=int(dt.datetime(2026,11,15,tzinfo=dt.timezone.utc).timestamp())

def time_s(v):
    try:
        if isinstance(v,(int,float)):return int(v)
        return int(dt.datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
    except (ValueError,TypeError,AttributeError):return None

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for buf in iter(lambda:f.read(1<<20),b""):h.update(buf)
    return h.hexdigest()

def fetch_terms():
    OUT.mkdir(parents=True,exist_ok=True)
    requested=0;found={};cursor=None;cursor_seen=set()
    params={"series_ticker":"KXBTC15M","min_close_ts":LO+1,
            "max_close_ts":HI+1,"limit":1000}
    for page in range(30):
        q=dict(params)
        if cursor:q["cursor"]=cursor
        response=json_get("/markets",q)
        listed=response.get("markets")
        if not isinstance(listed,list):raise ValueError("Kalshi markets response invalid")
        requested+=1
        for m in listed:
            ticker=m.get("ticker")
            if not (isinstance(ticker,str) and ticker.startswith(TICKER_PREFIX)):continue
            start=time_s(m.get("open_time"))
            close=time_s(m.get("close_time"))
            if start is None or close is None:continue
            if LO<=start<HI and close-start==900:
                if ticker in found:raise ValueError("Duplicate contract ticker in paginated market history")
                found[ticker]=m
        nextcursor=response.get("cursor")
        if not nextcursor:break
        if nextcursor in cursor_seen:raise ValueError("Kalshi market cursor repeated")
        cursor_seen.add(nextcursor);cursor=nextcursor
    else:raise ValueError("Kalshi market history pagination hit limit")

    cols=["ticker","event_ticker","status","result","floor_strike","open_time","close_time",
      "expected_expiration_time","latest_expiration_time","settlement_ts","expiration_value",
      "rules_primary","settlement_value_dollars","volume_fp","open_interest_fp"]
    path=OUT/"KXBTC15M_contract_terms_official_30d.csv"
    sorted_markets=sorted(found.values(),key=lambda v:(time_s(v["open_time"]),v["ticker"]))
    with open(path,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols+["source","time_of_original_strike_publication_verified"])
        w.writeheader()
        for m in sorted_markets:
            row={k:m.get(k) for k in cols}
            row["source"]="Kalshi public REST /markets query after historical settlement"
            row["time_of_original_strike_publication_verified"]="false"
            w.writerow(row)
    starts=[time_s(m["open_time"]) for m in sorted_markets]
    gaps=[{"from_utc":dt.datetime.fromtimestamp(starts[i],dt.timezone.utc).isoformat(),
           "to_utc":dt.datetime.fromtimestamp(starts[i+1],dt.timezone.utc).isoformat(),
           "gap_seconds":starts[i+1]-starts[i]} for i in range(len(starts)-1)
          if starts[i+1]-starts[i]!=900]
    summary={"pages":requested,"markets":len(sorted_markets),
       "yes_results":sum(m.get("result")=="yes" for m in sorted_markets),
       "no_results":sum(m.get("result")=="no" for m in sorted_markets),
       "unfinished_results":sum(m.get("result") not in ("yes","no") for m in sorted_markets),
       "expected_30_days_96_windows_per_day":2880,
       "missing_or_non15min_starts":2880-len(set(starts)),
       "nonconsecutive_start_gaps":gaps[:100],
       "output_file":str(path)}
    print("MARKET_TERMS_SUMMARY",json.dumps({k:v for k,v in summary.items() if k!="nonconsecutive_start_gaps"}),flush=True)
    if not sorted_markets:raise ValueError("No Kalshi BTC15m contracts returned")
    return sorted_markets,summary

def numeric(v):
    if v in (None,""):return None
    try:
        x=float(v)
        if not math.isfinite(x):return None
        return x
    except (TypeError,ValueError):return None

def candle_ohlc(c,prefix):
    v=c.get(prefix)
    if not isinstance(v,dict):return {}
    return {prefix+"_"+key:v.get(key+"_dollars",v.get(key)) for key in
      (("open","high","low","close","mean") if prefix=="price" else
       ("open","high","low","close"))}

def fetch_candles(markets):
    path=OUT/"KXBTC15M_actual_bid_ask_trade_1min_OHLC_30d.csv.gz"
    derived=OUT/"KXBTC15M_implied_NO_quotes_1min_30d.csv.gz"
    columns=["ticker","end_period_ts","end_period_utc","within_contract",
             "yes_bid_open","yes_bid_high","yes_bid_low","yes_bid_close",
             "yes_ask_open","yes_ask_high","yes_ask_low","yes_ask_close",
             "price_open","price_high","price_low","price_close","price_mean",
             "volume_fp","open_interest_fp","source"]
    derivedcols=["ticker","end_period_ts","end_period_utc","yes_bid_close",
          "yes_ask_close","implied_no_bid","implied_no_ask",
          "yes_spread","implied_no_spread","quote_status"]
    rows=0;issues=collections.Counter();per=collections.Counter()
    with gzip.open(path,"wt",newline="",compresslevel=4) as out, gzip.open(
        derived,"wt",newline="",compresslevel=4) as no:
        writer=csv.DictWriter(out,fieldnames=columns);writer.writeheader()
        d_writer=csv.DictWriter(no,fieldnames=derivedcols);d_writer.writeheader()
        for begin in range(0,len(markets),15):
            batch=markets[begin:begin+15]
            start=min(time_s(m["open_time"]) for m in batch)-60
            end=max(time_s(m["close_time"]) for m in batch)+60
            # Request no more than 10k possible 1m candle periods.
            if ((end-start+59)//60)*len(batch)>10000:
                raise ValueError("Batch candle request exceeds documented Kalshi limit")
            tickers=[m["ticker"] for m in batch]
            response=json_get("/markets/candlesticks",{
                "market_tickers":",".join(tickers),
                "start_ts":start,"end_ts":end,"period_interval":1})
            blocks=response.get("markets")
            if not isinstance(blocks,list):raise ValueError("Batch candles not a list")
            recognized=set()
            for block in blocks:
                ticker=block.get("market_ticker")
                if ticker not in tickers:raise ValueError("Batch result unknown ticker")
                recognized.add(ticker)
                market=next(m for m in batch if m["ticker"]==ticker)
                start_t=time_s(market["open_time"]);end_t=time_s(market["close_time"])
                clist=block.get("candlesticks",[])
                if not isinstance(clist,list):raise ValueError("Malformed market candles")
                unique=set()
                for candle in clist:
                    ts=candle.get("end_period_ts")
                    if not isinstance(ts,(int,float)):issues["non_numeric_end_period_ts"]+=1;continue
                    ts=int(ts)
                    if ts in unique:issues["duplicate_candle_timestamp"]+=1;continue
                    unique.add(ts)
                    item={"ticker":ticker,"end_period_ts":ts,
                        "end_period_utc":dt.datetime.fromtimestamp(ts,dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "within_contract":str(start_t<ts<=end_t).lower(),
                        "volume_fp":candle.get("volume_fp",candle.get("volume")),
                        "open_interest_fp":candle.get("open_interest_fp",candle.get("open_interest")),
                        "source":"Kalshi public historical 1m candlestick REST, recorded end-period summary; not executable L2"}
                    for mode in ("yes_bid","yes_ask","price"):item.update(candle_ohlc(candle,mode))
                    yb=numeric(item.get("yes_bid_close"))
                    ya=numeric(item.get("yes_ask_close"))
                    if yb is None or ya is None:
                        issues["candle_missing_bid_or_ask"]+=1
                    elif not(0<=yb<=ya<=1):
                        issues["invalid_or_crossed_yes_market_quote"]+=1
                    if item["within_contract"]=="true":per[ticker]+=1
                    writer.writerow(item);rows+=1
                    deriv={"ticker":ticker,"end_period_ts":ts,
                           "end_period_utc":item["end_period_utc"],
                           "yes_bid_close":item.get("yes_bid_close"),
                           "yes_ask_close":item.get("yes_ask_close"),
                           "quote_status":"theoretical_NO_complement_not_native_executable_book"}
                    if yb is not None and ya is not None and 0<=yb<=ya<=1:
                        deriv.update({"implied_no_bid":f"{1-ya:.4f}",
                            "implied_no_ask":f"{1-yb:.4f}",
                            "yes_spread":f"{ya-yb:.4f}",
                            "implied_no_spread":f"{ya-yb:.4f}"})
                    d_writer.writerow(deriv)
            for ticker in tickers:
                if ticker not in recognized:issues["ticker_missing_batch_response"]+=1
            if begin%(15*10)==0:print("KALSHI_CANDLES_BATCH_PROGRESS",begin+len(batch),"of",len(markets),rows,flush=True)
            time.sleep(.07)
    completeness=[{"ticker":m["ticker"],"within_15m_candles":per[m["ticker"]]}
                  for m in markets if per[m["ticker"]]<15]
    summary={"contracts_requested":len(markets),"candles_all_rows":rows,
        "unique_contracts_with_15_or_more_inside_bars":sum(per[m["ticker"]]>=15 for m in markets),
        "contracts_missing_one_or_more_15m_bars":completeness[:300],
        "integrity_issues":dict(issues),
        "file":str(path),"derived_no_file":str(derived)}
    print("KALSHI_CANDLE_SUMMARY",json.dumps({k:v for k,v in summary.items() if k!="contracts_missing_one_or_more_15m_bars"}),flush=True)
    if issues["invalid_or_crossed_yes_market_quote"]>0:raise ValueError("Source crossed invalid historical bid/ask")
    return summary

def fetch_trades(markets):
    # 2 FULL consecutive days of transaction-level data. The broader
    # 30-day minute candles/official outcomes are separately complete.
    selected=[m for m in markets if PUBLIC_TRADE_SAMPLE_BEGIN<=time_s(m["open_time"])<PUBLIC_TRADE_SAMPLE_END]
    path=OUT/"KXBTC15M_ACTUAL_TRADE_TICKS_2026-11-13_to_14.csv.gz"
    coverage=OUT/"ACTUAL_TRADE_PAGINATION_PER_CONTRACT.csv"
    cols=["trade_id","ticker","created_time","count_fp","yes_price_dollars",
          "no_price_dollars","taker_outcome_side","taker_book_side",
          "taker_side","is_block_trade","source"]
    total=0;errors={};summary=[];pages=0
    with gzip.open(path,"wt",newline="",compresslevel=4) as out:
        writer=csv.DictWriter(out,fieldnames=cols);writer.writeheader()
        for index,m in enumerate(selected,1):
            ticker=m["ticker"];start=time_s(m["open_time"]);end=time_s(m["close_time"])
            cursor=None;seen_cursors=set();seen_ids=set();n=0;p=0
            try:
                for page in range(150):
                    q={"ticker":ticker,"min_ts":start-1,"max_ts":end+1,"limit":1000}
                    if cursor:q["cursor"]=cursor
                    obj=json_get("/markets/trades",q)
                    got=obj.get("trades")
                    if not isinstance(got,list):raise ValueError("trades response not a list")
                    p+=1;pages+=1
                    for row in got:
                        tid=row.get("trade_id")
                        if row.get("ticker")!=ticker or not tid:raise ValueError("invalid trade id")
                        if tid in seen_ids:raise ValueError("duplicate trade within ticker")
                        seen_ids.add(tid)
                        ts=time_s(row.get("created_time"))
                        if ts is None or not(start-5<=ts<=end+5):raise ValueError("invalid trade UTC timestamp")
                        val={k:row.get(k) for k in cols}
                        val["source"]="Kalshi public API historical executed transaction (NOT order book quote)"
                        writer.writerow(val);n+=1;total+=1
                    new=obj.get("cursor")
                    if not new:break
                    if new in seen_cursors:raise ValueError("trade pagination cursor repeated")
                    seen_cursors.add(new);cursor=new
                else:raise ValueError("trade pagination exceeded 150 pages")
            except Exception as e:
                errors[ticker]=type(e).__name__
            summary.append({"ticker":ticker,"trade_rows":n,"pages":p,
                            "complete_api_pagination":ticker not in errors})
            if index%40==0:print("KALSHI_TRADE_PROGRESS",index,"of",len(selected),
                                 "records",total,flush=True)
            time.sleep(.08)
    with open(coverage,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(summary[0]) if summary else
            ["ticker","trade_rows","pages","complete_api_pagination"])
        w.writeheader();w.writerows(summary)
    return {"trade_window_utc":"2026-11-13 through 2026-11-14 inclusive",
            "contracts_requested":len(selected),"total_trade_ticks":total,
            "pages":pages,"errors_by_ticker":errors,"file":str(path),
            "per_market_coverage":str(coverage),
            "note":"All returned executed trades included (including block), no synthesized fills or implied liquidity; stop if pagination fails."}

def run():
    markets,market_summary=fetch_terms()
    candle_summary=fetch_candles(markets)
    trade_summary=fetch_trades(markets)
    # Explicit missing historical book evidence: REST orderbook is live
    # snapshot, not recorded past updates.
    series=json_get("/series/KXBTC15M")
    fee_meta=series.get("series",{})
    allowed=("ticker","title","category","frequency","fee_type",
        "fee_multiplier","settlement_sources","contract_terms_url")
    fees={k:fee_meta.get(k) for k in allowed if k in fee_meta}
    missing={
      "recorded_full_orderbook_updates":"NOT_AVAILABLE_FROM_HISTORICAL_KALSHI_REST",
      "displayed_quantity_at_each_historical_bid_ask":"UNAVAILABLE_WITHOUT_ORIGINAL_L2_SNAPSHOTS",
      "exact_slippage_or_fill_probability":"CANNOT_VERIFY_WITH_MINUTE_CANDLES",
      "exact_historical_fee_schedule":"NEEDS_DATE_SPECIFIC_KALSHI_FEE_RULES",
      "real_exact_NO_bid_ask":"DERIVED_AS_THEORETICAL_COMPLEMENT_ONLY",
      "all_trades_for_older_28_days":"NOT_EXPORTED_BY_THIS_RUN",
      "published_strike_first_observed_timestamp":"NOT_PROVEN_FROM_POST_SETTLEMENT_MARKET_METADATA"}
    (ROOT/"AUDIT").mkdir(exist_ok=True)
    (ROOT/"AUDIT"/"NOT_OBSERVED_OR_NOT_VERIFIED.json").write_text(json.dumps(missing,indent=2)+"\n")
    (ROOT/"AUDIT"/"series_fee_metadata.json").write_text(json.dumps(fees,indent=2)+"\n")
    files={}
    for p in ROOT.rglob("*"):
        if p.is_file():files[str(p.relative_to(ROOT))]={"sha256":sha(p),"bytes":p.stat().st_size}
    quality={"source":"Kalshi public REST, all GET, read-only",
        "scope":["2026-10-17","2026-11-15"],"market_contract_terms":market_summary,
        "one_minute_price_quote_candles":candle_summary,
        "executed_trade_tick_subset":trade_summary,"source_series_metadata":fees,
        "unavailable":missing,"files":files,
        "security":"No user private key, API Key ID, signatures, orders or account identity"}
    (ROOT/"AUDIT"/"KALSHI_30DAY_MANIFEST.json").write_text(json.dumps(quality,indent=2)+"\n")
    print("KALSHI_EXTENDED_EXPORT_SUMMARY",json.dumps({
        "markets":market_summary["markets"],
        "setttled":market_summary["yes_results"]+market_summary["no_results"],
        "candles":candle_summary["candles_all_rows"],
        "trade_days":2,"trades":trade_summary["total_trade_ticks"],
        "trade_errors":len(trade_summary["errors_by_ticker"]),
        "contract_gaps":len(market_summary["nonconsecutive_start_gaps"]),
        "missing_quote_rows":candle_summary["integrity_issues"].get("candle_missing_bid_or_ask",0)}),flush=True)
    if trade_summary["errors_by_ticker"]:
        print("WARNING_INCOMPLETE_TRADES_UNRESOLVED",len(trade_summary["errors_by_ticker"]),flush=True)

if __name__=="__main__":run()
