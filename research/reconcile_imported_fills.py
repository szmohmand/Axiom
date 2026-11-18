"""Strict research-only accounting of imported fills, never assumed live fills.

No account API, credentials, PII, deployment, files, or real orders. This
reconciles *supplied* rows and actual supplied fee_cost fields only. The result
MUST NOT be called verified actual returns until input account provenance,
history completeness, adjustments and official results have been checked in
a separately authorized private authenticated workflow.

See Kalshi v2 GET /portfolio/fills and historical fill cutoffs.
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation

MAX_ROWS = 10000
MAX_CONTRACTS = Decimal("1000000")


def _decimal(value, name, *, positive=False):
    if value is None or isinstance(value, bool):
        raise ValueError("Missing or invalid " + name)
    try:
        number=Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError("Invalid " + name) from None
    if not number.is_finite() or number<0 or (positive and number<=0):
        raise ValueError("Nonfinite or negative " + name)
    return number


def _event_time(value):
    if not isinstance(value,str):
        raise ValueError("Missing fill UTC creation time")
    stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Fill requires an actual UTC-offset timestamp")
    return stamp.timestamp()


def reconcile_imported_records(fills, settled_markets):
    """Conservative accounting, no claim of source authentication or profit."""
    base={"kind":"IMPORTED_ACCOUNT_RECORD_ACCOUNTING","status":"NO_EVIDENCE",
          "source_authenticated":False,"historical_cutoff_coverage_proven":False,
          "official_fee_completeness_proven":False,
          "realized_net_profit_usd":None,"actual_trading_profit_verified":False,
          "computed_record_net_usd":None,"records_validated":0,
          "pending_contracts":[],"settled_contracts":0,
          "fees_from_supplied_rows_usd":None,
          "no_real_orders_sent":True,
          "warning":"Imported rows are not authenticated private account records"}
    if fills is None or fills==[]:
        return {**base,"reason":"No authenticated fill records supplied"}
    if not isinstance(fills,list) or len(fills)>MAX_ROWS or not isinstance(settled_markets,dict):
        return {**base,"status":"INVALID_INPUT","reason":"Fill list or official terms invalid"}
    try:
        normalized=[]
        seen=set()
        for row in fills:
            if not isinstance(row,dict):
                raise ValueError("Malformed imported fill row")
            ident=row.get("fill_id")
            if not isinstance(ident,str) or not ident or ident in seen:
                raise ValueError("Missing/duplicate exchange fill identity")
            seen.add(ident)
            ticker=row.get("ticker") or row.get("market_ticker")
            if not isinstance(ticker,str) or not ticker.startswith("KXBTC15M-"):
                raise ValueError("Fill for unexpected exchange series")
            side=str(row.get("side") or "").lower()
            action=str(row.get("action") or "").lower()
            if side not in ("yes","no") or action not in ("buy","sell"):
                raise ValueError("Invalid exchange fill side/action")
            count=_decimal(row.get("count_fp"),"fill count",positive=True)
            if count>MAX_CONTRACTS:
                raise ValueError("Excessive fill contract count")
            price=_decimal(row.get(side+"_price_dollars"),"side-specific fill price",positive=True)
            if price>=1:
                raise ValueError("Impossible contract fill price")
            fee=_decimal(row.get("fee_cost"),"actual recorded fill fee")
            when=_event_time(row.get("created_time"))
            normalized.append((when,ident,ticker,side,action,count,price,fee))
        normalized.sort()
        money={}
        positions={}
        fees=Decimal(0)
        for _,ident,ticker,side,action,quantity,price,fee in normalized:
            key=(ticker,side)
            current=positions.get(key,Decimal(0))
            if action=="sell" and quantity>current:
                raise ValueError("Imported sells exceed prior recorded buys")
            positions[key]=current+(quantity if action=="buy" else -quantity)
            money[key]=money.get(key,Decimal(0)) + (
                -quantity*price if action=="buy" else quantity*price) - fee
            fees+=fee
        pending=[]
        settled=0
        total=Decimal(0)
        for (ticker,side),balance in positions.items():
            record=settled_markets.get(ticker)
            if balance>0:
                if not isinstance(record,dict) or str(record.get("status") or "").lower() not in ("settled","finalized") or str(record.get("result") or "").lower() not in ("yes","no"):
                    pending.append(ticker)
                    continue
                payout=balance if record["result"].lower()==side else Decimal(0)
                money[(ticker,side)]+=payout
                settled+=1
            total+=money[(ticker,side)]
        details={"records_validated":len(normalized),
                 "fees_from_supplied_rows_usd":str(fees),
                 "pending_contracts":sorted(set(pending)),
                 "settled_contracts":settled}
        if pending:
            return {**base,**details,"status":"PARTIAL_OPEN_POSITIONS",
                    "reason":"Some fills remain open or lack final official settlement"}
        return {**base,**details,
                "status":"RECORD_ARITHMETIC_COMPLETE",
                "computed_record_net_usd":str(total),
                "reason":"Calculated from supplied rows; provenance and completeness not verified"}
    except (KeyError,ValueError,TypeError,OverflowError) as exc:
        return {**base,"status":"INVALID_INPUT",
                "reason":type(exc).__name__+": "+str(exc)[:110]}
