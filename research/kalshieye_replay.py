"""AXIOM independent research replay on 2 real October 2026 KalshiEye days.

Critical methodological boundaries:
* Receives all 3 BTC exchange quotes and book snapshots on ORIGINAL recorder
  nanosecond timestamps, never joined to future data.
* Reconstructs completed one-minute MID-QUOTE bars (NOT Coinbase OHLCV trades).
* Market target comes from a day-end published file, and its AS-OF publication
  time is NOT known. Scores are conditional retrospective research ONLY.
* Official settlement labels used only AFTER inference and training.
* Trains learned challengers on Oct 13, hold-out entirely Oct 25.
* No app.main, database, credentials, live orders, or service changes.
* No data copied into source control. License: Kalshi Eye CC BY-NC 4.0.
"""
from __future__ import annotations
import bisect,collections,hashlib,json,math,statistics
from datetime import datetime,timezone
from research.kalshieye_schema import download,path_for
from app.ensemble import engine_pack, taker_fee

DAYS=("2026-10-13","2026-10-25")
CHECKPOINTS={"14m":840,"12m":720,"10m":600,"5m":300,"1m":60}
SOURCES=("coinbase","bitstamp","kraken")
NSEC=1_000_000_000


def table_records(day,family,fields):
    import pyarrow.parquet as pq, pyarrow as pa, pyarrow.compute as pc
    file=pq.ParquetFile(download(path_for(family,day)))
    schema=set(file.schema_arrow.names)
    if any(x not in schema for x in fields):
        raise ValueError(f"{family} changed columns: {sorted(set(fields)-schema)}")
    table=file.read(columns=list(fields))
    if "series" in fields:
        table=table.filter(pc.equal(table["series"],"KXBTC15M"))
    data={}
    for name in fields:
        a=table[name]
        if pa.types.is_timestamp(a.type):
            a=a.cast(pa.int64())
        data[name]=a.to_pylist()
    for vals in zip(*(data[n] for n in fields)):
        yield dict(zip(fields,vals))


def minute_candles(day):
    """Observed per-minute quote highs/lows/closes, no invented trade volume."""
    import pyarrow.parquet as pq,pyarrow as pa
    p=pq.ParquetFile(download(path_for("spot",day)))
    bars={venue:{} for venue in SOURCES}
    secmap={venue:{} for venue in SOURCES}
    total=0;bad=0;lags=collections.Counter()
    columns=("ts_recv","source","bid","ask","mid")
    for batch in p.iter_batches(batch_size=100000,columns=columns):
        ts=batch.column(0).cast(pa.int64()).to_pylist()
        venue=batch.column(1).to_pylist()
        bids=batch.column(2).to_pylist()
        asks=batch.column(3).to_pylist()
        mids=batch.column(4).to_pylist()
        for t,src,bid,ask,price in zip(ts,venue,bids,asks,mids):
            total+=1
            if (src not in SOURCES or t is None or price is None or
                bid is None or ask is None or not
                all(math.isfinite(float(v)) for v in (bid,ask,price)) or
                price<=0 or bid<=0 or ask<bid):
                bad+=1; continue
            sec=int(t//NSEC)
            secmap[src][sec]=(t,float(price))
            minute=(sec//60)*60
            existing=bars[src].get(minute)
            if existing is None:
                bars[src][minute]={"t":minute,"close":float(price),
                                   "high":float(price),"low":float(price),
                                   "open":float(price),"source":"MID_QUOTE",
                                   "last_ts_ns":t,"n_updates":1}
            else:
                existing["high"]=max(existing["high"],price)
                existing["low"]=min(existing["low"],price)
                existing["close"]=float(price)
                existing["last_ts_ns"]=t
                existing["n_updates"]+=1
    return {"bars":bars,"seconds":secmap,
            "times":{s:sorted(secmap[s]) for s in SOURCES},
            "quality":{"raw_spot_events":total,"ignored_bad":bad,
                       "minutes_by_source":{s:len(bars[s]) for s in SOURCES},
                       "seconds_by_source":{s:len(secmap[s]) for s in SOURCES}}}


def point(spot,source,t,max_age_s=2):
    # The as-of second must be COMPLETE BEFORE the decision, not same second:
    # a recorder's last update of second t can arrive AFTER t. Use <=t-1.
    times=spot["times"][source]
    idx=bisect.bisect_right(times,int(t)-1)-1
    if idx<0:return None
    sec=times[idx]
    if t-sec-1>max_age_s:return None
    raw_ns,p=spot["seconds"][source][sec]
    return {"price":p,"asof_sec":sec,"recv_ns":raw_ns}


def candles_at(spot,source,t,lookback=61):
    # At exact checkpoint t, the 1m period [t-60,t) is complete and may be
    # used. Any gap in the last 61 minutes invalidates the window.
    end=(t//60)*60
    vals=[]
    for start in range(end-60*lookback,end,60):
        c=spot["bars"][source].get(start)
        if c is None or c["last_ts_ns"]>=end*NSEC:
            return None
        vals.append(c)
    return vals


def k_market(day):
    start=datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()
    result={}
    for m in table_records(day,"markets",
        ("series","ticker","open_ts","close_ts","floor_strike",
         "fee_multiplier","result","status")):
        opening=m["open_ts"]; close=m["close_ts"]
        if opening is None or close is None or m["floor_strike"] is None:
            continue
        a=opening//NSEC;b=close//NSEC
        if not(start<=b<start+86400 and 780<=b-a<=960):continue
        if m["floor_strike"]<=0:continue
        if m["ticker"] in result:
            raise AssertionError("Duplicate contract in market catalog")
        result[m["ticker"]]={**m,"open":a,"close":b}
    return result


def outcomes(day):
    out={}
    for m in table_records(day,"settlements",
          ("series","ticker","result","close_ts","settlement_ts","floor_strike","ts_recv",
           "coin_price_start","coin_price_end","expiration_value")):
        if m["result"] not in ("yes","no"):continue
        if m["settlement_ts"] is None or m["close_ts"] is None:continue
        if m["settlement_ts"]<m["close_ts"]:continue
        old=out.get(m["ticker"])
        if old and old["result"]!=m["result"]:
            raise AssertionError("Conflicting official market outcome")
        out[m["ticker"]]=m
    return out


def book_at(day):
    # End-of-second snapshots; features at a decision t only use snapshots
    # strictly BEFORE the second t begins, to avoid within-second leakage.
    by_ticker=collections.defaultdict(list)
    for x in table_records(day,"book_snap_1s",
         ("ticker","ts","bid_px_0","ask_px_0","bid_sz_0","ask_sz_0")):
        if x["ts"] is not None:
            by_ticker[x["ticker"]].append(x)
    return by_ticker


def asof_book(history,second,max_age=5):
    if not history:return None
    # Data are returned in timestamp order by original publisher.
    times=[x["ts"] for x in history]
    ix=bisect.bisect_left(times,int(second)*NSEC)-1
    if ix<0:return None
    q=history[ix]
    if (second-q["ts"]/NSEC)>max_age:return None
    yb,ya=q["bid_px_0"],q["ask_px_0"]
    if yb is None or ya is None or not(0<yb<=ya<1):return None
    if (q["bid_sz_0"] or 0)<=0 or (q["ask_sz_0"] or 0)<=0:return None
    return {"yes_bid":yb,"yes_ask":ya,
            "no_ask":1-yb,"market_mid":(yb+ya)/2,
            "bid_size":q["bid_sz_0"],"ask_size":q["ask_sz_0"],
            "snapshot_recv_ns":q["ts"]}


def incidents(day):
    import pyarrow.parquet as pq,pyarrow as pa
    p=pq.ParquetFile(download(f"kalshieye-data/incidents/date={day}/incidents-{day}.parquet"))
    cols=("hour_start","blind_s","seq_missing","dropped","coverage_pct")
    table=p.read(columns=list(cols))
    raw={}
    for col in cols:
        a=table[col]
        if col=="hour_start":a=a.cast(pa.int64())
        raw[col]=a.to_pylist()
    affected=[];detail=[]
    for row in zip(*(raw[c] for c in cols)):
        hour,blind,missing,dropped,pct=row
        # Some source rows have blank coverage percentage, so use the actual
        # recorded outage and missed-sequence counts conservatively.
        if (blind or 0)>0 or (missing or 0)>0 or (dropped or 0)>0 or pct is None or pct<99.9:
            affected.append(int(hour//NSEC))
            detail.append({"hour":int(hour//NSEC),"blind":blind,
                           "seq_missing":missing,"dropped":dropped,
                           "coverage_pct":pct})
    return affected,detail


def math_features(r):
    c=r["candles"];s=r["spot"];k=r["target"];seconds=r["remaining"]
    prices=[x["close"] for x in c[-61:]]
    ret=[math.log(v/u) for u,v in zip(prices,prices[1:])]
    sigma=max(statistics.stdev(ret),1e-6)
    minute=seconds/60
    effective=max(minute-2/3,1/3)
    head=max(-10,min(10,(s-k)/(s*sigma*math.sqrt(effective))))
    mom=max(-10,min(10,sum(ret[-5:])/(sigma*math.sqrt(5))))
    diffs=[v-u for u,v in zip(prices[-15:],prices[-14:])]
    gain=sum(max(d,0) for d in diffs)
    loss=sum(max(-d,0) for d in diffs)
    rsi=(gain/(gain+loss)-.5)*4 if gain+loss>0 else 0.
    logdistance=math.log(s/k)
    return {"headstart":head,"momentum5":mom,"rsi":rsi,
            "volatility":sigma,"log_distance":logdistance,
            "minutes_left":minute,"time_sin":math.sin(2*math.pi*(r["ts"]%86400)/86400),
            "time_cos":math.cos(2*math.pi*(r["ts"]%86400)/86400)}


def zero_drift(r):
    x=math_features(r)
    sec=r["remaining"];sigma=x["volatility"]/math.sqrt(60)
    z=(math.log(r["spot"]/r["target"])-.5*sigma*sigma*(sec-30)) / (sigma*math.sqrt(sec-40))
    return max(1e-6,min(1-1e-6,.5*(1+math.erf(z/math.sqrt(2)))))


def vector(x):
    return [1.,x["headstart"],x["momentum5"],x["rsi"]]


def sigmoid(x):
    return 1/(1+math.exp(-max(-40,min(40,x))))


def fit_logit(rows):
    vals=[(vector(row["features"]),row["y"]) for row in rows]
    if len(vals)<25 or len({y for _,y in vals})<2:return None
    priors=[0.,1.7,0.,0.]; theta=priors[:]
    for _ in range(400):
        gradients=[0.,0.,0.,0.]
        for x,y in vals:
            d=sigmoid(sum(a*b for a,b in zip(theta,x)))-y
            for j in range(4):gradients[j]+=d*x[j]
        for j in range(4):
            theta[j]-=.12*(gradients[j]/len(vals)+.08*(theta[j]-priors[j]))
    return theta


def audit_benchmark_proxy_basis(spot,markets,labels,bad_hours):
    """Compare official settled BTC benchmark with 60 observed quote seconds.

    Official values are after-the-event diagnostics ONLY; never predictive
    inputs. Neither quote mean nor Coinbase mid is BRTI itself.
    """
    differences=collections.defaultdict(list)
    mismatches=collections.Counter()
    official_count=0;target_checks=[];rejected=collections.Counter()
    for ticker,m in markets.items():
        result=labels.get(ticker)
        if not result:continue
        value=result.get("coin_price_end")
        if value is None:
            try:value=float(result.get("expiration_value"))
            except (TypeError,ValueError):value=None
        if value is None or not math.isfinite(value) or value<=0:
            rejected["no_numerical_official_end_index"]+=1;continue
        if any(h+3600>m["open"] and h<m["close"] for h in bad_hours):
            rejected["incident_window"]+=1;continue
        official_count+=1
        target_index=result.get("coin_price_start")
        if target_index is not None and math.isfinite(target_index):
            target_checks.append(abs(target_index-m["floor_strike"]))
        for venue in SOURCES:
            sample=[]
            for sec in range(int(m["close"]-60),int(m["close"])):
                # Access latest quote received on or before second 'sec':
                # point() internally refuses the currently incomplete second.
                q=point(spot,venue,sec+1,2)
                if q is None:
                    break
                sample.append(q["price"])
            if len(sample)!=60:
                rejected[f"incomplete_60s_{venue}"]+=1
                continue
            avg=sum(sample)/60
            differences[venue].append(avg-value)
            mismatches[venue]+=int((avg>=m["floor_strike"]) != (result["result"]=="yes"))
    stats={}
    for venue,errs in differences.items():
        abs_errors=sorted(abs(x) for x in errs)
        stats[venue]={
            "markets_with_60_complete_spot_seconds":len(errs),
            "mean_signed_usd":round(statistics.mean(errs),4),
            "mean_absolute_usd":round(statistics.mean(abs_errors),4),
            "median_absolute_usd":round(statistics.median(abs_errors),4),
            "p95_absolute_usd":round(abs_errors[min(len(errs)-1,int(.95*(len(errs)-1)))],4),
            "max_absolute_usd":round(max(abs_errors),4),
            "wrong_contract_winner_if_replaced_with_spot_average":mismatches[venue]}
    return {"official_end_index_markets_after_excluding_incidents":official_count,
            "target_vs_official_start_index_available":len(target_checks),
            "max_abs_target_minus_index_start_usd":round(max(target_checks),4) if target_checks else None,
            "by_exchange":stats,
            "unusable":dict(rejected),
            "interpretation":"This uses official end-of-window index only as POST-SETTLEMENT ground truth; spot quote averages must never become the official contract result."}


def make_dataset():
    all_obs={};provenance={};summary={}
    for day in DAYS:
        spot=minute_candles(day)
        markets=k_market(day)
        labels=outcomes(day)
        books=book_at(day)
        bad_hours,incident_details=incidents(day)
        excluded=collections.Counter()
        rows=[]; candidate_market=len(markets)
        for ticker,m in sorted(markets.items()):
            label=labels.get(ticker)
            if label is None:
                excluded["no_official_settlement"]+=1;continue
            if (m["result"] not in ("yes","no",None) or
                (m["result"] in ("yes","no") and m["result"]!=label["result"])):
                excluded["catalog_official_conflict"]+=1;continue
            if label["floor_strike"] is not None and abs(label["floor_strike"]-m["floor_strike"])>0.011:
                excluded["catalog_settlement_strike_mismatch"]+=1;continue
            # Exclude the whole trade window if any known recorder incident
            # overlaps it; no stitching market book across blind intervals.
            if any(h+3600>m["open"] and h<m["close"] for h in bad_hours):
                excluded["recorder_incident_overlap"]+=1;continue
            for cp,remain in CHECKPOINTS.items():
                now=int(m["close"]-remain)
                if now<=m["open"] or now>=m["close"]:
                    excluded["checkpoint_outside_contract"]+=1;continue
                quote=point(spot,"coinbase",now,2)
                if quote is None:
                    excluded["stale_coinbase_spot"]+=1;continue
                candles=candles_at(spot,"coinbase",now,61)
                if candles is None:
                    excluded["missing_completed_quote_candle"]+=1;continue
                market=asof_book(books.get(ticker,[]),now,5)
                # Predictions may still be made without a recent Kalshi mid;
                # the quote benchmark is then unavailable, NEVER invented.
                outcome=int(label["result"]=="yes")
                row={"ticker":ticker,"date":day,"checkpoint":cp,"remaining":remain,
                     "ts":now,"spot":quote["price"],"target":m["floor_strike"],
                     "candles":candles,"features":None,"quote":market,
                     "y":outcome,"source_recv_ns":quote["recv_ns"],
                     "fee_multiplier":m["fee_multiplier"] if m["fee_multiplier"] is not None else 1.0}
                # Robustness: compute the same unchanged AXIOM ensemble
                # against three independently recorded exchange MID QUOTE
                # candle streams. This measures proxy sensitivity, NOT BRTI.
                venue_p={}
                for venue in SOURCES:
                    vp=point(spot,venue,now,2)
                    vc=candles_at(spot,venue,now,61)
                    if vp is not None and vc is not None:
                        pred=engine_pack(vp["price"],
                            {"target":m["floor_strike"],"seconds_left":remain,
                             "market_mid":None},vc)
                        if pred["available"]:
                            venue_p[venue]={"prob":pred["prob_above"],
                                            "spot":vp["price"]}
                row["venue_proxy_ensembles"]=venue_p
                row["features"]=math_features(row)
                rows.append(row)
                if market is None:
                    excluded["no_recent_balanced_kalshi_quote"]+=1
        all_obs[day]=rows
        basis=audit_benchmark_proxy_basis(spot,markets,labels,bad_hours)
        summary[day]={"official_index_vs_quote_basis":basis,
                      "contract_catalog_count":candidate_market,
                      "official_outcomes_with_ticker":len(labels),
                      "clean_checkpoints":len(rows),
                      "clean_distinct_contracts":len({r["ticker"] for r in rows}),
                      "checkpoints":dict(collections.Counter(r["checkpoint"] for r in rows)),
                      "with_recent_book":sum(r["quote"] is not None for r in rows),
                      "rejections":dict(excluded),
                      "recorder_incidents":incident_details,
                      "spot_source_quality":spot["quality"],
                      "file_hashes":{
                          f:hashlib.sha256(download(path_for(f,day)).read_bytes()).hexdigest()
                          for f in ("spot","markets","settlements","book_snap_1s")}}
        # Test an independent, noncontract-based early movement indicator from
        # the same recorder. Exchange differences are NOT used in forecasting.
        early=[]
        start=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
        # End-of-second top-book state belongs only to this market while
        # active. Kalshi book pressure is a SEPARATE market-derived probe.
        ticker_by_minute={}
        for ticker,m in markets.items():
            for minute in range(int((m["open"]+59)//60*60),int(m["close"]),60):
                ticker_by_minute[minute]=ticker
        for now in range(start+3600,start+86400-120,60):
            if (now//3600)*3600 in bad_hours:
                continue  # unknown Kalshi recorder state invalidates the test
            a=point(spot,"coinbase",now,2)
            b=point(spot,"bitstamp",now,2)
            c=point(spot,"kraken",now,2)
            future=point(spot,"coinbase",now+60,2)
            prior=point(spot,"coinbase",now-60,2)
            if None in (a,b,c,future,prior):continue
            spread=a["price"]-(b["price"]+c["price"])/2
            trend=a["price"]-prior["price"]
            move=future["price"]-a["price"]
            ticker=ticker_by_minute.get(now)
            bq=asof_book(books.get(ticker,[]),now,5) if ticker else None
            pressure=((bq["bid_size"]-bq["ask_size"]) /
                      (bq["bid_size"]+bq["ask_size"])
                      if bq is not None else None)
            early.append({"date":day,"ts":now,"dislocation":spread,
                          "trend":trend,"future_move":move,
                          "market_book_pressure":pressure})
        provenance[day]={"early_move_inputs":early}
    return all_obs,summary,provenance


def score_predictions(preds):
    if not preds:return {"n":0}
    n=len(preds)
    b=sum((p-y)**2 for p,y in preds)/n
    loss=-sum(y*math.log(max(1e-6,p))+(1-y)*math.log(max(1e-6,1-p))
              for p,y in preds)/n
    correct=sum(int((p>=.5)==bool(y)) for p,y in preds)
    bins=[];ece=0.0
    for j in range(5):
        lo=j*.2;hi=lo+.2
        chunk=[(p,y) for p,y in preds if lo<=p<hi or (j==4 and p==1)]
        if chunk:
            mean=sum(p for p,_ in chunk)/len(chunk)
            obs=sum(y for _,y in chunk)/len(chunk)
            bins.append({"low":round(lo,2),"n":len(chunk),
                         "mean_p":round(mean,4),"observed_yes":round(obs,4)})
            ece+=len(chunk)/n*abs(mean-obs)
    return {"n":n,"brier":round(b,6),"logloss":round(loss,6),
            "directional_accuracy":round(correct/n,6),
            "ece_5bin":round(ece,6),"calibration":bins}


def eval_models(observations):
    train=observations[DAYS[0]]
    test=observations[DAYS[1]]
    by_cp=collections.defaultdict(list)
    for r in train:by_cp[r["checkpoint"]].append(r)
    logit={cp:fit_logit(rows) for cp,rows in by_cp.items()}
    xgb={}
    try:
        from xgboost import XGBClassifier
        for cp,rows in by_cp.items():
            if len(rows)<35 or len({r["y"] for r in rows})<2:continue
            keys=("headstart","momentum5","rsi","volatility","log_distance",
                  "time_sin","time_cos")
            clf=XGBClassifier(n_estimators=60,max_depth=2,learning_rate=.055,
                              subsample=1,colsample_bytree=1,random_state=19,
                              eval_metric="logloss",n_jobs=1,objective="binary:logistic")
            clf.fit([[r["features"][key] for key in keys] for r in rows],
                    [r["y"] for r in rows])
            xgb[cp]=clf
    except ImportError:
        pass
    score=collections.defaultdict(list)
    paired=collections.defaultdict(list)
    saved=collections.defaultdict(dict)
    opportunities=collections.defaultdict(list)
    call_candidates=collections.defaultdict(list)
    venue_sensitivity=collections.defaultdict(list)
    eval_summary={"train_day":DAYS[0],"test_day":DAYS[1],
                  "train_labeled_checkpoint_rows":len(train),
                  "test_labeled_checkpoint_rows":len(test),
                  "train_contracts":len({r["ticker"] for r in train}),
                  "test_contracts":len({r["ticker"] for r in test}),
                  "trained_logit_at":sorted(cp for cp,v in logit.items() if v is not None),
                  "trained_xgboost_at":sorted(xgb),
                  "conditional_strike_replay":True}
    for r in test:
        vp=r.get("venue_proxy_ensembles",{})
        if "coinbase" in vp and ("bitstamp" in vp or "kraken" in vp):
            values=[x["prob"] for x in vp.values()]
            venue_sensitivity[r["checkpoint"]].append(max(values)-min(values))
        pack=engine_pack(r["spot"],
                        {"target":r["target"],"seconds_left":r["remaining"],
                         "market_mid":r["quote"]["market_mid"] if r["quote"] else None},
                        r["candles"])
        preds={e["name"]:e["prob_above"] for e in pack["engines"] if e["available"]
               and e["name"]!="kalshi_market"}
        if pack["available"]:preds["axiom_ensemble"]=pack["prob_above"]
        preds["schen_m0_minute_proxy"]=zero_drift(r)
        cp=r["checkpoint"];x=r["features"]
        if logit.get(cp) is not None:
            preds["independent_logit_candle_features"]=sigmoid(sum(
                a*b for a,b in zip(logit[cp],vector(x))))
        if cp in xgb:
            keys=("headstart","momentum5","rsi","volatility","log_distance",
                  "time_sin","time_cos")
            preds["xgb_spot_only_subset"]=float(xgb[cp].predict_proba(
                [[x[k] for k in keys]])[0][1])
        if r["quote"]:
            preds["kalshi_yes_mid_benchmark"]=r["quote"]["market_mid"]
        for name,p in preds.items():
            if p is not None and math.isfinite(p):
                p=min(1-1e-6,max(1e-6,p))
                saved[(cp,r["ticker"])][name]=p
                saved[(cp,r["ticker"])]["y"]=r["y"]
                score[(cp,name)].append((p,r["y"]))
                call_candidates[(name,r["ticker"])].append((r["remaining"],p,r["y"]))
                if r["quote"] and name!="kalshi_yes_mid_benchmark":
                    base=r["quote"]["market_mid"]
                    paired[(cp,name)].append((p,base,r["y"]))
                # Illustrative 1-contract YES/NO taker-at-ask, paper only,
                # at PREDECLARED 8-cent edge, spread<=4c, visible 1ct size,
                # and >=2m until close. Neither fill nor profit is proven.
                q=r["quote"]
                if q and r["remaining"]>=120:
                    side="yes" if p>=.5 else "no"
                    ask=q["yes_ask"] if side=="yes" else q["no_ask"]
                    bid=q["yes_bid"] if side=="yes" else 1-q["yes_ask"]
                    spread=ask-bid
                    fee_mult=r["fee_multiplier"]
                    fee=math.ceil(fee_mult*.07*ask*(1-ask)*100-1e-9)/100
                    edge=(p if side=="yes" else 1-p)-ask-fee
                    if .05<=ask<=.90 and 0<=spread<=.04 and edge>=.08:
                        # Do not use a market benchmark to propose itself as
                        # an independent strategy.
                        if name!="kalshi_yes_mid_benchmark":
                            win=int((side=="yes")==bool(r["y"]))
                            opportunities[(name,r["ticker"])].append(
                                (r["remaining"],win-ask-fee,edge))
    by_score=[{"checkpoint":cp,"model":model,**score_predictions(vals)}
              for (cp,model),vals in sorted(score.items())]
    paired_scores=[]
    for (cp,model),vals in sorted(paired.items()):
        paired_scores.append({"checkpoint":cp,"model":model,"n_matched_with_market":len(vals),
            "brier_skill_vs_market":round(sum((b-y)**2-(p-y)**2 for p,b,y in vals)/len(vals),6)})
    # All comparisons use the SAME ticker/checkpoint and held-out label.
    # Positive delta Brier = first model better than the second.
    # Block-bootstrap contracts (one record per contract/checkpoint). This
    # does NOT control fully for correlation across adjacent contracts.
    import random
    rng=random.Random(20261115)
    comparisons=(
        ("schen_m0_minute_proxy","axiom_ensemble"),
        ("schen_m0_minute_proxy","kalshi_yes_mid_benchmark"),
        ("independent_logit_candle_features","axiom_ensemble"),
        ("xgb_spot_only_subset","axiom_ensemble"),
        ("axiom_ensemble","kalshi_yes_mid_benchmark"),
    )
    paired_ci=[]
    for cp in CHECKPOINTS:
        cp_rows=[v for (checkpoint,ticker),v in saved.items() if checkpoint==cp]
        for first,second in comparisons:
            deltas=[(v[second]-v["y"])**2-(v[first]-v["y"])**2 for v in cp_rows
                    if first in v and second in v]
            if not deltas:continue
            n=len(deltas)
            draws=[]
            for _ in range(2000):
                draws.append(sum(deltas[rng.randrange(n)] for _ in range(n))/n)
            draws.sort()
            paired_ci.append({"checkpoint":cp,"first":first,"second":second,
                              "matched":n,"positive_is_first_better":True,
                              "delta_brier":round(statistics.mean(deltas),6),
                              "approx_pair_bootstrap95":[round(draws[49],6),round(draws[1950],6)],
                              "limited_to_one_holdout_day":True})
    leads=[]
    for name in sorted({m for m,t in call_candidates}):
        calls=collections.defaultdict(list)
        for (model,ticker),vals in call_candidates.items():
            if model==name:
                chosen=next((v for v in sorted(vals,reverse=True)
                             if v[1]>=.6 or v[1]<=.4),None)
                if chosen:calls[ticker]=chosen
        source_tickers={tick for model,tick in call_candidates if model==name}
        if source_tickers:
            leads.append({"model":name,"test_contracts":len(source_tickers),
                "confident_first_calls":len(calls),
                "coverage":round(len(calls)/len(source_tickers),4),
                "first_call_accuracy":round(statistics.mean(
                    int((p>=.5)==bool(y)) for remain,p,y in calls.values()),4) if calls else None,
                "first_call_lead_sec":round(statistics.mean(
                    remain for remain,p,y in calls.values()),2) if calls else None})
    opp=[]
    for name in sorted({m for m,t in opportunities}):
        selected=[]
        for (model,t),values in opportunities.items():
            if model==name:selected.append(sorted(values,reverse=True)[0])
        if selected:
            opp.append({"model":name,"one_earliest_paper_entry_per_contract":len(selected),
                        "mean_hypothetical_after_fee_dollars":round(statistics.mean(x[1] for x in selected),6),
                        "actual_fills_verified":False})
    venue_report=[]
    for cp,spreads in sorted(venue_sensitivity.items()):
        venue_report.append({"checkpoint":cp,
          "asof_2s_matched_quote_sets":len(spreads),
          "median_probability_range":round(statistics.median(spreads),6),
          "mean_probability_range":round(statistics.mean(spreads),6),
          "range_over_0_05":sum(x>0.05 for x in spreads),
          "range_over_0_10":sum(x>0.10 for x in spreads)})
    return {"evaluation":eval_summary,
            "venue_proxy_sensitivity":venue_report,
            "scores":by_score,"paired_brier_vs_market":paired_scores,
            "paired_brier_contract_bootstrap_ci":paired_ci,
            "first_confident_call":leads,"paper_ask_only_opportunities":opp}


def early_test(provenance):
    train=provenance[DAYS[0]]["early_move_inputs"]
    test=provenance[DAYS[1]]["early_move_inputs"]
    def summarize(records,signal,filter_moves=0):
        eligible=[r for r in records if abs(r["future_move"])>=filter_moves
                  and signal(r) is not None and signal(r)!=0]
        if not eligible:return {"n":0}
        n=len(eligible)
        good=sum(int((signal(r)>0)==(r["future_move"]>0)) for r in eligible)
        return {"n":n,"directional_accuracy":round(good/n,6),
                "avg_abs_next_60s_move_usd":round(statistics.mean(abs(r["future_move"]) for r in eligible),2),
                "positive_future_share":round(sum(r["future_move"]>0 for r in eligible)/n,5)}
    funcs={"spot_trend_prev_60s":lambda r:r["trend"],
           "coinbase_minus_other_venues":lambda r:r["dislocation"],
           "kalshi_yes_top_book_pressure_market_derived":lambda r:r["market_book_pressure"],
           "always_up":lambda r:1}
    scores={}
    for name,fn in funcs.items():
        scores[name]={"train_oct13_all":summarize(train,fn),
                      "holdout_oct25_all":summarize(test,fn),
                      "holdout_oct25_moves_20usd_or_more":summarize(test,fn,20)}
    # Train ONE predeclared logistic model only on Oct 13; evaluate the
    # completely untouched Oct 25 movements. Market price pressure cannot
    # be relabeled as an independent BTC forecast.
    ml={"status":"OPTIONAL_MISSING_DEPENDENCY"}
    try:
        from sklearn.linear_model import LogisticRegression
        keys=("trend","dislocation","market_book_pressure")
        train_ml=[r for r in train if r["market_book_pressure"] is not None]
        test_ml=[r for r in test if r["market_book_pressure"] is not None]
        if len(train_ml)>=100 and len(test_ml)>=100:
            # Fixed USD scales chosen before inspecting test outcomes.
            def vec(row):
                return [row["trend"]/25,row["dislocation"]/10,
                        row["market_book_pressure"]]
            clf=LogisticRegression(C=1.0,random_state=19,max_iter=500)
            clf.fit([vec(r) for r in train_ml],
                    [int(r["future_move"]>0) for r in train_ml])
            probs=clf.predict_proba([vec(r) for r in test_ml])[:,1].tolist()
            actual=[int(r["future_move"]>0) for r in test_ml]
            n=len(actual)
            ml={"status":"TESTED_MARKET_DERIVED_BENCHMARK_NOT_INDEPENDENT",
                "train_n":len(train_ml),"holdout_n":n,
                "positive_outcome_rate":round(sum(actual)/n,6),
                "holdout_brier":round(sum((p-y)**2 for p,y in zip(probs,actual))/n,6),
                "holdout_accuracy":round(sum((p>=.5)==bool(y) for p,y in zip(probs,actual))/n,6),
                "constant_50pct_brier":0.25,
                "feature_coefs":dict(zip(keys,[round(x,4) for x in clf.coef_[0]])),
                "no_live_model_promotion":True}
        else:
            ml={"status":"INSUFFICIENT_CLEAN_TRAIN_OR_TEST_MARKET_BOOK",
                "train_n":len(train_ml),"holdout_n":len(test_ml)}
    except ImportError:
        pass
    return {"train_minute_samples":len(train),"test_minute_samples":len(test),
            "market_derived_logistic_holdout":ml,
            "tests":scores,
            "limits":"Next-minute outcome is NOT identification of move onset. Aggregated quotes can be concurrent price action; no true pre-move lead-time is established."}


def main():
    observations,quality,spot=make_dataset()
    models=eval_models(observations)
    early=early_test(spot)
    report={"status":"CONDITIONAL_HISTORICAL_REPLAY_NOT_VERIFIED_PRODUCTION_ALPHA",
            "source":"KalshiEye/kalshi-order-book-sample (CC BY-NC 4.0)",
            "source_dates":list(DAYS),
            "quality_by_day":quality,
            "held_out_model_comparison":models,
            "independent_next_minute_price_action_probe":early,
            "caveats":[
                "Kalshi contract target/strike comes from day-end market file, publication time not independently proven: conditional research rather than validated as-of production history",
                "Spot features derived from recorder exchange quote mid; not Coinbase real OHLCV trades, not official BRTI index; volume not available",
                "Kalshi quote inputs are only separate comparison/illustrative asks, never forecast model features",
                "2 noncontiguous days too small for robust claims, 10/13 trains, 10/25 tests. No tuning on 10/25; strong regime drift possible",
                "Known Kalshi recorder incident windows excluded, no interpolated missing minute bars, no future seconds admitted",
                "Trained logit and XGB are reduced feature challengers, NOT unmodified third-party full trained models",
                "No actual executions, fill guarantee, trading profitability or 1-2 minute pre-move signal proven"] }
    print("BEGIN_REAL_REPLAY_RESULTS")
    print(json.dumps(report,sort_keys=True,indent=2))
    print("END_REAL_REPLAY_RESULTS")

if __name__=="__main__":
    main()
