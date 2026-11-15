"""AXIOM Batch 1: exactly 100 individually numbered, independently asserted
research-safety experiment checks. Synthetic test inputs, NOT return claims.

G01-G10: contract/time, G11-G20: spot, G21-G30: candles,
G31-G40: Kalshi comparator, G41-G50: official labels,
G51-G60: checkpoint clock, G61-G70: independent models,
G71-G80: proper scoring, G81-G90: chronological training,
G91-G100: read-only collection and isolated grading.

The project-wide full suite MUST also pass. One PASS here is evidence of
a specific implemented property only, never of prediction performance.
"""
import copy
import math
from pathlib import Path

import pytest

from app.ensemble import engine_pack
from research import challenger_lab as lab
from research import record_live

MISSING=object()


def sample(i=0, seconds_left=840, midpoint=.5):
    opening=1_800_000_000+900*i
    expiry=opening+900
    ts=expiry-seconds_left
    end=(int(ts)//60)*60
    base=90500+17*i
    candles=[]
    for j in range(61):
        close=base+math.sin((j+i)/9)*75+1.1*j
        candles.append({"t":end-(61-j)*60,"close":close,
                        "high":close+6,"low":close-6,"volume":1+j/40})
    return {"ticker":f"KXBTC15M-BATCH1-{i:04d}",
            "open_ts":opening,"expires_ts":expiry,"target_ts":opening,
            "ts":ts,"spot_ts":ts,"spot":base+75,"target":base,
            "candles":candles,"market_mid":midpoint,"market_mid_ts":ts}


def modify(row, field, value):
    x=copy.deepcopy(row)
    if value is MISSING:
        x.pop(field,None)
    else:
        x[field]=value(x) if callable(value) else value
    return x


def normalized(i=0, **kwargs):
    return lab.normalize_observation(sample(i,**kwargs))


def official(row, result="yes", source="kalshi_official", late=8):
    return {"ticker":row["ticker"],"result":result,"source":source,
            "expires_ts":row["expires_ts"],"settled_at":row["expires_ts"]+late}


# G001–G010: contract identity and as-of chronology
CONTRACT_CASES=[
    ("G001","ticker",""),
    ("G002","ticker","KXETH15M-WRONG"),
    ("G003","ticker",123),
    ("G004","ticker",MISSING),
    ("G005","ts",lambda r:r["open_ts"]-1),
    ("G006","ts",lambda r:r["expires_ts"]),
    ("G007","expires_ts",lambda r:r["open_ts"]-1),
    ("G008","open_ts",lambda r:r["ts"]+1),
    ("G009","target_ts",lambda r:r["ts"]+1),
    ("G010","target",0),
]


@pytest.mark.parametrize("case,field,value",CONTRACT_CASES,
                         ids=[x[0] for x in CONTRACT_CASES])
def test_batch1_contract_guard(case,field,value):
    with pytest.raises(lab.ReplayError):
        lab.normalize_observation(modify(sample(),field,value))


# G011–G020: spot source freshness and finite numbers
SPOT_CASES=[
    ("G011","spot_ts",lambda r:r["ts"]+1),
    ("G012","spot_ts",lambda r:r["ts"]-31),
    ("G013","spot_ts",None),
    ("G014","spot_ts",True),
    ("G015","spot",0),
    ("G016","spot",-1),
    ("G017","spot",float("inf")),
    ("G018","spot",float("nan")),
    ("G019","spot",True),
    ("G020","spot","not-a-price"),
]


@pytest.mark.parametrize("case,field,value",SPOT_CASES,
                         ids=[x[0] for x in SPOT_CASES])
def test_batch1_spot_guard(case,field,value):
    with pytest.raises(lab.ReplayError):
        lab.normalize_observation(modify(sample(),field,value))


# G021–G030: completed authentic minute candle provenance
CANDLE_CASES=[
    ("G021",lambda c:None),
    ("G022",lambda c:c[:30]),
    ("G023",lambda c:[*c[:-1],"malformed"]),
    ("G024",lambda c:[*c[:-1],dict(c[-1],t=c[-1]["t"]+.5)]),
    ("G025",lambda c:[*c[:-1],dict(c[-1],t=c[-1]["t"]+60)]),
    ("G026",lambda c:[*c[:-1],dict(c[-1],t=c[-1]["t"]-60)]),
    ("G027",lambda c:[*c[:-1],dict(c[-1],t=c[-1]["t"]+120)]),
    ("G028",lambda c:[*c[:-1],dict(c[-1],high=c[-1]["close"]-1)]),
    ("G029",lambda c:[*c[:-1],dict(c[-1],low=-2)]),
    ("G030",lambda c:[*c[:-1],dict(c[-1],volume=-1)]),
]


@pytest.mark.parametrize("case,mutation",CANDLE_CASES,
                         ids=[x[0] for x in CANDLE_CASES])
def test_batch1_candle_guard(case,mutation):
    row=sample()
    row["candles"]=mutation(row["candles"])
    with pytest.raises(lab.ReplayError):
        lab.normalize_observation(row)


# G031–G040: Kalshi quote benchmark validity; never infer from bad quote
MARKET_CASES=[
    ("G031","market_mid",-.001),
    ("G032","market_mid",0),
    ("G033","market_mid",1),
    ("G034","market_mid",1.1),
    ("G035","market_mid",float("nan")),
    ("G036","market_mid","not-a-probability"),
    ("G037","market_mid_ts",MISSING),
    ("G038","market_mid_ts",lambda r:r["ts"]+1),
    ("G039","market_mid_ts",lambda r:r["ts"]-31),
    ("G040","market_mid",True),
]


@pytest.mark.parametrize("case,field,value",MARKET_CASES,
                         ids=[x[0] for x in MARKET_CASES])
def test_batch1_market_quote_guard(case,field,value):
    with pytest.raises(lab.ReplayError):
        lab.normalize_observation(modify(sample(),field,value))


# G041–G050: official result provenance must be independent of BTC spot
LABEL_CASES=[
    ("G041","ticker",""),
    ("G042","ticker","KXETH15M-WRONG"),
    ("G043","result","unresolved"),
    ("G044","result",0),
    ("G045","source","unknown"),
    ("G046","source","synthetic_fixture"),
    ("G047","settled_at",lambda r:r["expires_ts"]-1),
    ("G048","expires_ts",None),
    ("G049","settled_at",float("nan")),
    ("G050","result",None),
]


@pytest.mark.parametrize("case,field,value",LABEL_CASES,
                         ids=[x[0] for x in LABEL_CASES])
def test_batch1_official_result_guard(case,field,value):
    row=official(sample())
    with pytest.raises(lab.ReplayError):
        lab.normalize_settlement(modify(row,field,value))


# G051–G060: published checkpoint tolerance, no post-expiration calls
CLOCK_CASES=[
    ("G051",840,"14m"),
    ("G052",869,"14m"),
    ("G053",810,"14m"),
    ("G054",720,"12m"),
    ("G055",600,"10m"),
    ("G056",300,"5m"),
    ("G057",60,"1m"),
    ("G058",29,None),
    ("G059",180,None),
    ("G060",901,None),
]


@pytest.mark.parametrize("case,remaining,expected",CLOCK_CASES,
                         ids=[x[0] for x in CLOCK_CASES])
def test_batch1_checkpoint_classification(case,remaining,expected):
    assert lab.checkpoint(remaining)==expected


# G061–G070: direct observed Kalshi quote never enters independent forecasts
INDEPENDENCE_CASES=[
    ("G061",.01,.99),
    ("G062",.02,.98),
    ("G063",.07,.93),
    ("G064",.15,.85),
    ("G065",.25,.75),
    ("G066",.30,.70),
    ("G067",.40,.60),
    ("G068",.45,.55),
    ("G069",.49,.51),
    ("G070",.05,.95),
]


@pytest.mark.parametrize("case,low,high",INDEPENDENCE_CASES,
                         ids=[x[0] for x in INDEPENDENCE_CASES])
def test_batch1_models_independent_of_contract_quote(case,low,high):
    a=normalized(midpoint=low)
    b=normalized(midpoint=high)
    assert lab.inputs(a)==lab.inputs(b)
    assert lab.zero_drift(a)==lab.zero_drift(b)
    assert lab.logistic_predict([0,.5,.4,.3],a)==lab.logistic_predict([0,.5,.4,.3],b)
    market=lambda r:{"target":r["target"],"seconds_left":r["seconds_left"],
                     "market_mid":r["market_mid"]}
    pa=engine_pack(a["spot"],market(a),a["candles"])
    pb=engine_pack(b["spot"],market(b),b["candles"])
    ea={x["name"]:x["prob_above"] for x in pa["engines"]}
    eb={x["name"]:x["prob_above"] for x in pb["engines"]}
    assert ea["kalshi_market"]!=eb["kalshi_market"]
    for name in lab.INDEPENDENT:
        if name in ea:
            assert ea[name]==eb[name],name
    assert pa["prob_above"]==pb["prob_above"]


# G071–G080: Brier/log-loss direction proper-scoring arithmetic
SCORING_CASES=[
    ("G071",.01,0),
    ("G072",.10,0),
    ("G073",.20,0),
    ("G074",.33,0),
    ("G075",.49,0),
    ("G076",.50,1),
    ("G077",.51,1),
    ("G078",.73,1),
    ("G079",.90,1),
    ("G080",.99,1),
]


@pytest.mark.parametrize("case,p,y",SCORING_CASES,
                         ids=[x[0] for x in SCORING_CASES])
def test_batch1_proper_scoring_identity(case,p,y):
    got=lab._score([(p,y,"KXBTC15M-TEST",840)])
    assert got["n"]==1
    assert got["directional_accuracy"]==1
    assert got["brier"]==pytest.approx((p-y)**2,abs=1e-6)
    assert got["logloss"]==pytest.approx(-math.log(p if y else 1-p),abs=1e-5)
    assert got["ece_5_bin"]==pytest.approx(abs(p-y),abs=1e-6)
    assert sum(bin_["n"] for bin_ in got["calibration"])==1


# G081–G090: chronological training / source isolation
TRAINING_CASES=[
    ("G081","insufficient_nine"),
    ("G082","one_sided_outcome"),
    ("G083","labels_future"),
    ("G084","only_nine_available"),
    ("G085","minimum_ten"),
    ("G086","row_order_permutation"),
    ("G087","market_odds_perturbation"),
    ("G088","future_added_label"),
    ("G089","boundary_settlement_time"),
    ("G090","bounded_outlier_probability"),
]


@pytest.mark.parametrize("case,scenario",TRAINING_CASES,
                         ids=[x[0] for x in TRAINING_CASES])
def test_batch1_training_leakage_gate(case,scenario):
    rows=[normalized(i) for i in range(16)]
    labels={r["ticker"]:lab.normalize_settlement(
        official(sample(i),result="yes" if i%2==0 else "no"))
        for i,r in enumerate(rows)}
    cutoff=max(x["settled_at"] for x in labels.values())+100
    original=lab.fit_independent_logistic(rows,labels,cutoff)
    assert original is not None
    if scenario=="insufficient_nine":
        assert lab.fit_independent_logistic(rows[:9],labels,cutoff) is None
    elif scenario=="one_sided_outcome":
        all_yes={k:dict(v,result="yes") for k,v in labels.items()}
        assert lab.fit_independent_logistic(rows,all_yes,cutoff) is None
    elif scenario=="labels_future":
        future={k:dict(v,settled_at=cutoff+5) for k,v in labels.items()}
        assert lab.fit_independent_logistic(rows,future,cutoff) is None
    elif scenario=="only_nine_available":
        partial={k:(v if index<9 else dict(v,settled_at=cutoff+1))
                 for index,(k,v) in enumerate(labels.items())}
        assert lab.fit_independent_logistic(rows,partial,cutoff) is None
    elif scenario=="minimum_ten":
        assert lab.fit_independent_logistic(rows[:10],labels,cutoff) is not None
    elif scenario=="row_order_permutation":
        reversed_fit=lab.fit_independent_logistic(list(reversed(rows)),labels,cutoff)
        assert reversed_fit==pytest.approx(original)
    elif scenario=="market_odds_perturbation":
        changed=[dict(r,market_mid=.99 if i%2 else .01) for i,r in enumerate(rows)]
        assert lab.fit_independent_logistic(changed,labels,cutoff)==pytest.approx(original)
    elif scenario=="future_added_label":
        extra=normalized(200)
        extra_label=lab.normalize_settlement(official(sample(200)))
        x=dict(labels,**{extra["ticker"]:dict(extra_label,settled_at=cutoff+1)})
        assert lab.fit_independent_logistic(rows+[extra],x,cutoff)==pytest.approx(original)
    elif scenario=="boundary_settlement_time":
        boundary={k:dict(v,settled_at=cutoff) for k,v in labels.items()}
        assert lab.fit_independent_logistic(rows,boundary,cutoff) is None
    elif scenario=="bounded_outlier_probability":
        other=normalized(300)
        p=lab.logistic_predict(original,other)
        assert math.isfinite(p) and 0<p<1


class StubProvider:
    def __init__(self,row):
        self.row=row
        self.candle_quality={"status":"FULL","source":"SYNTHETIC"}
        self.calls=[]
        self.outcome="yes"
    def market(self):
        self.calls.append("market")
        return {"ticker":self.row["ticker"],"target":self.row["target"],
                "close_ts":self.row["expires_ts"],
                "market_mid":self.row["market_mid"]}
    def price(self):
        self.calls.append("price")
        return self.row["spot"]
    def candles(self):
        self.calls.append("candles")
        return self.row["candles"]
    def settlement(self,ticker):
        self.calls.append("settlement")
        return self.outcome


# G091–G100: real collector call graph exercised with explicit synthetic stubs
COLLECTOR_CASES=[
    ("G091","missing_market"),
    ("G092","missing_target"),
    ("G093","missing_close"),
    ("G094","insufficient_candles"),
    ("G095","stale_candles"),
    ("G096","first_record"),
    ("G097","duplicate_record"),
    ("G098","no_grading_before_expiration"),
    ("G099","official_grading_only"),
    ("G100","idempotent_grading"),
]


@pytest.mark.parametrize("case,scenario",COLLECTOR_CASES,
                         ids=[x[0] for x in COLLECTOR_CASES])
def test_batch1_collector_and_official_ledger(case,scenario,tmp_path):
    raw=sample()
    provider=StubProvider(raw)
    root=tmp_path/"isolated"
    clock=lambda:raw["ts"]
    path=root/"observations.jsonl"
    if scenario=="missing_market":
        provider.market=lambda:None
        assert record_live.observe(provider,root,clock)["status"]=="NO_KNOWN_TARGET"
    elif scenario=="missing_target":
        provider.market=lambda:{"target":None,"close_ts":raw["expires_ts"],"ticker":raw["ticker"]}
        assert record_live.observe(provider,root,clock)["status"]=="NO_KNOWN_TARGET"
    elif scenario=="missing_close":
        provider.market=lambda:{"target":raw["target"],"close_ts":None,"ticker":raw["ticker"]}
        assert record_live.observe(provider,root,clock)["status"]=="NO_KNOWN_TARGET"
    elif scenario=="insufficient_candles":
        provider.candles=lambda:raw["candles"][:10]
        assert record_live.observe(provider,root,clock)["status"]=="INPUT_WITHHELD"
    elif scenario=="stale_candles":
        provider.candles=lambda:[dict(c,t=c["t"]-240) for c in raw["candles"]]
        assert record_live.observe(provider,root,clock)["status"]=="INPUT_WITHHELD"
    else:
        assert record_live.observe(provider,root,clock)["status"]=="RECORDED"
        assert provider.calls==["market","price","candles"]
        assert len(record_live._rows(path))==1
        if scenario=="first_record":
            assert not (root/"settlements.jsonl").exists()
        elif scenario=="duplicate_record":
            assert record_live.observe(provider,root,clock)["status"]=="ALREADY_RECORDED"
            assert len(record_live._rows(path))==1
        elif scenario=="no_grading_before_expiration":
            assert record_live.grade(provider,root,clock)["new_official_results"]==0
            assert "settlement" not in provider.calls
        elif scenario=="official_grading_only":
            got=record_live.grade(provider,root,lambda:raw["expires_ts"]+10)
            assert got["new_official_results"]==1
            assert record_live._rows(root/"settlements.jsonl")[0]["source"]=="kalshi_official"
            assert "result" not in record_live._rows(path)[0]
        elif scenario=="idempotent_grading":
            when=lambda:raw["expires_ts"]+10
            assert record_live.grade(provider,root,when)["new_official_results"]==1
            assert record_live.grade(provider,root,when)["new_official_results"]==0
            assert len(record_live._rows(root/"settlements.jsonl"))==1
    if scenario in ("missing_market","missing_target","missing_close",
                    "insufficient_candles","stale_candles"):
        assert not path.exists()


def test_batch1_exactly_one_hundred_distinct_numbered_cases():
    groups=(CONTRACT_CASES,SPOT_CASES,CANDLE_CASES,MARKET_CASES,LABEL_CASES,
            CLOCK_CASES,INDEPENDENCE_CASES,SCORING_CASES,TRAINING_CASES,COLLECTOR_CASES)
    ids=[case[0] for group in groups for case in group]
    assert len(ids)==100 and len(set(ids))==100
    assert ids==[f"G{n:03d}" for n in range(1,101)]
