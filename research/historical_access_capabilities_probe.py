"""Read-only capability probe for older BRTI hours and historical Kalshi trades."""
import json,os
from research.export_shared_historical import json_get, get
from research.brti_access_probe import load_key,sign_headers

def probe(tag,path,params=None,auth=None):
    try:
        obj=json_get(path,params,auth=auth)
        out={"tag":tag,"ok":True,"root_fields":list(obj)[:30]}
        if tag.startswith("BRTI"):
            data=obj.get("data",{})
            x=data.get("values",[]) if isinstance(data,dict) else []
            out["rows"]=len(x) if isinstance(x,list) else None
        elif tag.startswith("TRADE"):
            trades=obj.get("trades") if isinstance(obj.get("trades"),list) else None
            out["rows"]=len(trades) if trades is not None else None
            out["has_next_cursor"]=bool(obj.get("cursor"))
            if trades:out["trade_field_names"]=sorted(trades[0])
        elif tag.startswith("CANDLES"):
            markets=obj.get("markets")
            out["markets"]=len(markets) if isinstance(markets,list) else None
            if markets:out["market_fields"]=sorted(markets[0])
        else:
            m=obj.get("markets",[])
            out["market_count"]=len(m) if isinstance(m,list) else None
        print("PROBE "+json.dumps(out),flush=True)
    except Exception as ex:
        print("PROBE "+json.dumps({"tag":tag,"ok":False,"failure_type":str(ex.__class__.__name__),"http_code":str(ex)[:50] if "HTTP=" in str(ex) else "unknown"}),flush=True)
if __name__=="__main__":
    key_id=os.environ["KALSHI_API_KEY_ID"].strip()
    key,_=load_key(os.environ["KALSHI_PRIVATE_KEY_PEM"])
    for stamp in ["2026-10-16T12:00:00.000Z","2026-11-01T12:00:00.000Z","2026-11-12T12:00:00.000Z"]:
        probe("BRTI_"+stamp,"/cfbenchmarks/history/values",
              {"id":"BRTI","timespan":"HOUR","timestamp":stamp},
              sign_headers(key_id,key,"GET","/trade-api/v2/cfbenchmarks/history/values"))
    ticker="KXBTC15M-26NOV121915-15"
    probe("TRADES_ACTIVE","/markets/trades",{"ticker":ticker,"limit":10})
    probe("TRADES_HISTORIC","/historical/trades",{"ticker":ticker,"limit":10})
    probe("CANDLES_BATCH","/markets/candlesticks",{"market_tickers":ticker,"start_ts":1794528000,"end_ts":1794528900,"period_interval":1})
    probe("HISTORIC_MARKET","/historical/markets",{"series_ticker":"KXBTC15M","limit":2})
