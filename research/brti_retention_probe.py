"""Bounded read-only source retention/capabilities. No raw confidential output."""
import datetime as dt,json,os,time
from research.export_shared_historical import json_get,walk_values
from research.brti_access_probe import load_key,sign_headers
from research.historical_access_capabilities_probe import probe
if __name__=="__main__":
 keyid=os.environ["KALSHI_API_KEY_ID"].strip()
 key,_=load_key(os.environ["KALSHI_PRIVATE_KEY_PEM"])
 dates=["2026-11-14","2026-11-13","2026-11-12","2026-11-08","2026-11-01","2026-10-16","2026-09-15","2026-08-01","2026-06-01"]
 for d in dates:
  p="/cfbenchmarks/history/values"
  q={"id":"BRTI","timespan":"HOUR","timestamp":d+"T12:00:00.000Z"}
  try:
   obj=json_get(p,q,sign_headers(keyid,key,"GET","/trade-api/v2"+p))
   vals=list(walk_values(obj))
   v=vals[0] if vals else None
   print("HISTORY_RANGE",json.dumps({"date":d,"points":len(vals),"root_fields":list(obj),
         "data_kind":type(obj.get("data")).__name__,
         "first_point_field_names":list(v) if v else None}),flush=True)
  except Exception as e:
   print("HISTORY_RANGE",json.dumps({"date":d,"status":"API_unavailable",
    "error_type":type(e).__name__}),flush=True)
  time.sleep(.2)
 p="/cfbenchmarks/history/values"
 try:
  obj=json_get(p,{"id":"BRTI","timespan":"DAY","timestamp":"2026-11-13T00:00:00.000Z"},sign_headers(keyid,key,"GET","/trade-api/v2"+p))
  pts=list(walk_values(obj))
  print("DAY_HISTORY_CAPABILITY",json.dumps({"count":len(pts),"root_keys":list(obj),
      "start_ms":pts[0].get("time") if pts else None,
      "end_ms":pts[-1].get("time") if pts else None}),flush=True)
 except Exception as e:
  print("DAY_HISTORY_CAPABILITY",json.dumps({"status":"NOT_VERIFIED","error_type":type(e).__name__}),flush=True)
 ticker="KXBTC15M-26NOV121915-15"
 probe("BOOK_AT_SETTLED","/markets/"+ticker+"/orderbook",{"depth":10})
 probe("SERIES_METADATA","/series/KXBTC15M")
