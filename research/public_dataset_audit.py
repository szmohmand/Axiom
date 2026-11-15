"""One-shot real historical *data suitability* audit, never AXIOM model validation.

Downloads publicly published DegenHedge CSV tables (Jan-Oct 2026) and
cross-checks official Kalshi BTC15m labels with their selected signal log.
No source code is executed from the provider. All results are descriptive,
selected-sample and no trade execution/fill/profit guarantee is implied.
Only aggregate stats + SHA256 fingerprints are printed; raw data NOT committed.
"""
from __future__ import annotations
import collections
import csv
import hashlib
import io
import json
import math
import statistics
from datetime import datetime, timezone
from urllib.request import Request, urlopen

DATASET="DegenHedge/kalshi-btc-15m"
BASE="https://huggingface.co/datasets/"+DATASET+"/resolve/main/"
MAX_SIZE=8_000_000


def fetch_csv(name):
    url=BASE+name
    request=Request(url,headers={"User-Agent":"AXIOM-research-public-data-read-only/1.0"})
    with urlopen(request,timeout=45) as response:
        buf=response.read(MAX_SIZE+1)
        if len(buf)>MAX_SIZE:
            raise ValueError("Historical public dataset unexpectedly large")
    text=buf.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))),hashlib.sha256(buf).hexdigest()


def instant(s):
    return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)


def number(s):
    return None if s is None or s=="" else float(s)


def stats(rows):
    if not rows:
        return {"n":0}
    positives=sum(r["correct"] for r in rows)
    n=len(rows)
    brier=sum((r["p"]-r["y"])**2 for r in rows)/n
    logloss=-sum(r["y"]*math.log(max(1e-7,r["p"]))+
                 (1-r["y"])*math.log(max(1e-7,1-r["p"])) for r in rows)/n
    ask_pnl=[r["correct"]-r["ask"] for r in rows if r["ask"] is not None]
    per_share_fee=[math.ceil((.07*r["ask"]*(1-r["ask"]))*100-1e-9)/100
                   for r in rows if r["ask"] is not None]
    nask=len(ask_pnl)
    return {"n":n,"side_accuracy":round(positives/n,6),
            "brier_yes":round(brier,6),"logloss_yes":round(logloss,6),
            "mean_signal_probability_for_chosen_side":round(statistics.mean(r["side_p"] for r in rows),6),
            "price_eligible_n":nask,
            "illustrative_ask_only_gross_per_contract":round(statistics.mean(ask_pnl),6) if nask else None,
            "illustrative_taker_fee_per_contract":round(statistics.mean(per_share_fee),6) if nask else None,
            "illustrative_ask_only_after_fee_per_contract":round(statistics.mean(a-b for a,b in zip(ask_pnl,per_share_fee)),6) if nask else None}


def audit(windows,signals,shas):
    issues=collections.Counter()
    universe={}; since=[]; official=0; strike_ok=0
    for w in windows:
        ticker=w.get("window_ticker")
        if not ticker or not ticker.startswith("KXBTC15M-"):
            issues["bad_window_ticker"]+=1;continue
        if ticker in universe:
            issues["duplicate_window"]+=1;continue
        try:
            opened,closed=instant(w["open_utc"]),instant(w["close_utc"])
        except (KeyError,ValueError):
            issues["bad_window_clock"]+=1;continue
        if (closed-opened).total_seconds()!=900:
            issues["non_15m_window"]+=1
        if w.get("result") in ("yes","no"):
            official+=1
        if w.get("strike_flag")=="ok" and number(w.get("official_strike")) is not None:
            strike_ok+=1
        universe[ticker]=w
        since.append((opened,closed))
    prior_accepted=set()
    paired=[]
    for s in signals:
        ticker=s.get("window_ticker")
        w=universe.get(ticker)
        if not w:
            issues["unmatched_signal"]+=1;continue
        if ticker in prior_accepted:
            issues["duplicate_signal_ticker"]+=1;continue
        prior_accepted.add(ticker)
        if s.get("graded_from")!="kalshi_official":
            issues["nonofficial_signal_grade_excluded"]+=1;continue
        result=w.get("result")
        if result not in ("yes","no") or s.get("official_result")!=result:
            issues["official_outcome_mismatch_excluded"]+=1;continue
        if s.get("side") not in ("UP","DOWN"):
            issues["invalid_side"]+=1;continue
        try:
            close=instant(w["close_utc"])
            signal_ts=instant(s["signal_time_utc"])
            actual_seconds=(close-signal_ts).total_seconds()
            declared_seconds=float(s["seconds_to_close"])
            p_side=float(s["model_prob"])
            ask=int(s["entry_ask_cents"])/100
        except (KeyError,ValueError,TypeError):
            issues["invalid_signal_fields"]+=1;continue
        if (actual_seconds<0 or actual_seconds>900 or
            abs(actual_seconds-declared_seconds)>2):
            issues["signal_clock_mismatch"]+=1;continue
        if not (0<=p_side<=1 and 0<ask<1):
            issues["signal_probability_or_ask_invalid"]+=1;continue
        selected_yes=(s["side"]=="UP")
        expected_correct=int(selected_yes == (result=="yes"))
        if s.get("won")!=str(expected_correct):
            issues["logged_win_mismatch"]+=1;continue
        paired.append({"ticker":ticker,"p":p_side if selected_yes else 1-p_side,
                       "side_p":p_side,"y":int(result=="yes"),
                       "correct":expected_correct,"ask":ask,
                       "remain":actual_seconds,
                       "month":w["close_utc"][:7],"day":w["close_utc"][:10]})
    overall=stats(paired)
    # Resample entire UTC days; consecutive 15m outcomes are not independent.
    # These CIs describe selected alerts only and do not establish real fills.
    import random
    days=collections.defaultdict(list)
    for row in paired:
        days[row["day"]].append(row)
    aggregates=[]
    for day in sorted(days):
        items=days[day]
        aggregates.append((
            len(items),sum(x["correct"] for x in items),
            sum((x["p"]-x["y"])**2 for x in items),
            sum(x["correct"]-x["ask"]-math.ceil(.07*x["ask"]*(1-x["ask"])*100-1e-9)/100 for x in items)))
    bootstrap={"method":"UTC_day_cluster_percentile_95","seed":20261115,
               "replicates":1000,"day_count":len(aggregates),
               "interpretation":"selected sample; NOT proven executable strategy PnL"}
    if len(aggregates)>=20:
        rng=random.Random(20261115)
        draws=collections.defaultdict(list)
        for _ in range(1000):
            selected=[aggregates[rng.randrange(len(aggregates))] for _ in aggregates]
            n=sum(a[0] for a in selected)
            draws["accuracy"].append(sum(a[1] for a in selected)/n)
            draws["brier"].append(sum(a[2] for a in selected)/n)
            draws["illustrative_net_usd"].append(sum(a[3] for a in selected)/n)
        for name,values in draws.items():
            values.sort()
            bootstrap[name+"_ci_95"]=[round(values[24],6),round(values[975],6)]
    months=collections.defaultdict(list)
    remain=collections.defaultdict(list)
    for row in paired:
        months[row["month"]].append(row)
        if row["remain"]>=600: x="10m_plus"
        elif row["remain"]>=300: x="5_to_10m"
        elif row["remain"]>=120: x="2_to_5m"
        elif row["remain"]>=60: x="1_to_2m"
        else: x="under_1m"
        remain[x].append(row)
    months_summary={month:stats(items) for month,items in sorted(months.items())}
    timing_summary={name:stats(remain.get(name,[])) for name in
                    ("10m_plus","5_to_10m","2_to_5m","1_to_2m","under_1m")}
    return {
        "research_status":"PUBLIC_SELECTED_SIGNALS_ONLY_NOT_AXIOM_CHALLENGERS",
        "dataset":DATASET,
        "sha256":shas,
        "total_windows_csv":len(windows),"distinct_valid_window_rows":len(universe),
        "official_result_windows":official,
        "strike_ok_windows":strike_ok,
        "original_selected_signals":len(signals),
        "official_joined_strict_signals":len(paired),
        "excluded_or_invalid":dict(sorted(issues.items())),
        "all_official_selected":overall,
        "utc_day_block_bootstrap_ci":bootstrap,
        "by_month":months_summary,
        "by_seconds_remaining":timing_summary,
        "can_establish_BRTI_outcome":"Only labels and published strikes; not original 1s BRTI history",
        "can_replay_AXIOM_models":False,
        "can_show_1_to_2_min_early_move_alert":False,
        "can_claim_trading_PnL":False,
        "caveat":"DegenHedge published-alert sample selected by its model and 1-99 cent ask. Reported ask is not a guaranteed fill and taker fees are an illustration, not verified market-specific execution costs. Signal spot/features are not published; AXIOM engines cannot be fairly reconstructed on these files. No source provided true post-publication revision/latency audit.",
        "attribution":"DegenHedge/kalshi-btc-15m public dataset, DegenHedge-created fields CC BY 4.0"
    }


def main():
    rows={}; hashes={}
    for name in ("windows.csv","signals.csv"):
        rows[name],hashes[name]=fetch_csv(name)
    result=audit(rows["windows.csv"],rows["signals.csv"],hashes)
    print("BEGIN_AXIOM_PUBLIC_RESEARCH_JSON")
    print(json.dumps(result,sort_keys=True,indent=2))
    print("END_AXIOM_PUBLIC_RESEARCH_JSON")


if __name__=="__main__":
    main()
