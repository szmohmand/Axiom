"""Phase 3 paper-ledger and authenticated BRTI settlement boundary checks."""
import math
import sqlite3
from datetime import datetime

import pytest

from app import brti_live as live
from app import paper_exits as exits
from app import settlement_probability as sp
from app.orderbook import normalize_orderbook
from app.storage import Ledger


NOW = 1_800_000_000.
TICKER = "KXBTC15M-PHASE123-COVER"


def book(bid=".40", nobid=".50", t=NOW, bsize="8", nosize="8"):
    return normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[[bid,bsize]],"no_dollars":[[nobid,nosize]]}},TICKER,t)


def position(side="YES", rule=None, target=None):
    return {"ticker":TICKER,"side":side,"created":NOW-300,
            "invalidation_rule":rule,"take_profit":target}


def market(seconds=360):
    return {"ticker":TICKER, "close_ts":NOW+seconds,
            "seconds_left":seconds,"target":64000.,
            "yes_ask":.45,"no_ask":.55}


def brti(**kwargs):
    return {"status":"STREAMING","authenticated_stream_verified":True,
            "latest_value_usd":"64010",
            "source_ts_ms":int(NOW*1000),
            "axiom_received_at_ms":int(NOW*1000),**kwargs}


def minute_bars(n=46):
    base=int(NOW//60)*60-n*60
    return [{"t":base+i*60,"source":"cfbenchmarks_brti_authenticated_live",
             "close":64000. + i*3 + (i%2)*2.,"open":64000.+i*3,
             "high":64005.+i*3,"low":63995.+i*3,"volume":None}
            for i in range(n)]


def test_real_bid_depth_and_all_exit_invalidations():
    p=position()
    m=market()
    assert exits._number("bad") is None
    assert exits._number(float("nan")) is None
    assert exits.evaluate_exit(None,m,brti(),[],book(),{},NOW) is None
    assert exits.evaluate_exit(p,None,brti(),[],book(),{},NOW) is None
    assert exits.evaluate_exit({**p,"ticker":"OTHER"},m,brti(),[],book(),{},NOW) is None
    assert exits.evaluate_exit({**p,"side":"WRONG"},m,brti(),[],book(),{},NOW) is None
    assert exits.evaluate_exit(p,{"ticker":TICKER,"close_ts":"bad"},brti(),[],book(),{},NOW) is None
    assert exits.evaluate_exit(p,market(0),brti(),[],book(),{},NOW) is None
    assert exits.evaluate_exit(p,m,brti(),[],book(t=NOW-20),{},NOW) is None
    no_bid=normalize_orderbook({"orderbook_fp":{"yes_dollars":[],
                       "no_dollars":[[".5","10"]]}},TICKER,NOW)
    assert exits.evaluate_exit(p,m,brti(),[],no_bid,{},NOW) is None
    thin=book(bsize=".5")
    assert exits.evaluate_exit(p,m,brti(),[],thin,{},NOW) is None
    assert exits.evaluate_exit(position(target=.7),m,brti(),[],book(),{},NOW) is None
    assert exits.evaluate_exit(position(target=.4),m,brti(),[],book(),{},NOW)["exit_reason"]=="TAKE_PROFIT"
    assert exits.evaluate_exit(position(),market(100),brti(),[],book(),{},NOW)["exit_reason"]=="TIME_STOP"
    assert exits.evaluate_exit(position("NO"),market(100),brti(),[],book(nobid=".4"),{},NOW)["exit_reason"]=="TIME_STOP"
    assert exits.evaluate_exit(position(),m,brti(),[],book(),
                               {"available":True,"CVD_norm_60s":-.3,
                                "cvd_60_span":50},NOW)["exit_reason"]=="CVD_SIGN_FLIP"
    assert exits.evaluate_exit(position("NO"),m,brti(),[],book(nobid=".4"),
                               {"available":True,"CVD_norm_60s":.3,
                                "cvd_60_span":50},NOW)["exit_reason"]=="CVD_SIGN_FLIP"
    assert exits.evaluate_exit(position(),m,brti(),[],book(),
                               {"available":True,"CVD_norm_60s":"bad",
                                "cvd_60_span":55},NOW) is None
    assert exits.evaluate_exit(position(),m,brti(),[],book(),
                               {"available":False,"CVD_norm_60s":-.3,
                                "cvd_60_span":55},NOW) is None
    assert exits.evaluate_exit(position(),m,brti(),[],book(),
                               {"available":True,"CVD_norm_60s":-.3,
                                "cvd_60_span":"bad"},NOW) is None
    assert exits.evaluate_exit(position(),market(170),brti(),[],book(),
                               {"available":True,"CVD_norm_60s":-.3,
                                "cvd_60_span":55},NOW) is None


def test_brti_rules_reject_stale_missing_and_check_both_directions():
    bars=minute_bars()
    newest={"t":NOW-60,"source":"cfbenchmarks_brti_authenticated_live",
            "volume":None,"close":63900.}
    valid=[newest]
    up={"type":"BRTI_CLOSE_BACK_INSIDE_RANGE","level_usd":63980.,"direction":"UP"}
    down={**up,"direction":"DOWN","level_usd":63920.}
    p=position(rule=up)
    assert not exits._invalidated(p,{},valid,NOW)
    assert not exits._invalidated(p,brti(status="STALE"),valid,NOW)
    assert not exits._invalidated(p,brti(authenticated_stream_verified=False),valid,NOW)
    assert not exits._invalidated(p,brti(latest_value_usd="nan"),valid,NOW)
    assert not exits._invalidated(p,brti(source_ts_ms=0),valid,NOW)
    assert not exits._invalidated(position(rule=up | {"level_usd":None}),brti(),valid,NOW)
    assert not exits._invalidated(position(rule=up | {"direction":"NONE"}),brti(),valid,NOW)
    assert not exits._invalidated(p,brti(),[],NOW)
    assert not exits._invalidated(p,brti(),[{**newest,"source":"wrong"}],NOW)
    assert not exits._invalidated(p,brti(),[{**newest,"volume":4}],NOW)
    assert not exits._invalidated(p,brti(),[{**newest,"t":NOW-150}],NOW)
    assert not exits._invalidated(p,brti(),[{**newest,"close":"bad"}],NOW)
    assert exits._invalidated(p,brti(),valid,NOW)
    assert not exits._invalidated(position(rule=up|{"level_usd":63800.}),brti(),valid,NOW)
    assert exits._invalidated(position(rule=down),brti(),[{**newest,"close":63950.}],NOW)
    assert not exits._invalidated(position(rule=down|{"level_usd":64000.}),brti(),valid,NOW)
    strike={"type":"BRTI_STRIKE_BAND_OR_CVD_FLIP","strike":64000.,
            "max_deviation_bps":10}
    assert exits._invalidated(position(rule=strike),brti(latest_value_usd="64100"),[],NOW)
    assert not exits._invalidated(position(rule=strike),brti(),[],NOW)
    assert not exits._invalidated(position(rule=strike|{"strike":None}),brti(),[],NOW)
    assert not exits._invalidated(position(rule=strike|{"max_deviation_bps":0}),brti(),[],NOW)
    extend={"type":"BRTI_CONFIRMED_VENUE_EXTENSION","beyond_outlier_usd":64000.}
    assert exits._invalidated(position("NO",extend),brti(),[],NOW)
    assert exits._invalidated(position("YES",extend),brti(latest_value_usd="63900"),[],NOW)
    assert not exits._invalidated(position("YES",extend),brti(),[],NOW)
    assert not exits._invalidated(position("NO",extend|{"beyond_outlier_usd":None}),brti(),[],NOW)
    assert not exits._invalidated(position(rule={"type":"UNKNOWN"}),brti(),[],NOW)


def test_storage_fee_time_bounds_open_close_and_repeated_settlement(tmp_path):
    led=Ledger(str(tmp_path/"coverage.sqlite3"))
    m=market()
    for value in (True,float("nan"),-1,1.1):
        with pytest.raises(ValueError):
            led.paper_fee(value)
    for side in ("MAYBE",):
        with pytest.raises(ValueError):
            led.trade(m,side,NOW)
    with pytest.raises(ValueError):
        led.trade(market(10),"YES",NOW)
    with pytest.raises(ValueError):
        led.trade({**m,"yes_ask":None},"YES",NOW)
    for invalid in (True,0,1.5,float("nan")):
        with pytest.raises(ValueError):
            led.trade(m,"YES",NOW,take_profit=invalid)
    for invalid in ("string",{"type":"OTHER"}):
        with pytest.raises(ValueError):
            led.trade(m,"YES",NOW,invalidation_rule=invalid)
    assert led.trade(m,"YES",NOW-5,take_profit=.7)["entry"]==.45
    with pytest.raises(ValueError):
        led.trade(m,"YES",NOW)
    for value in (True,float("nan"),float("inf")):
        with pytest.raises(ValueError):
            led.close_paper(TICKER,.6,"TAKE_PROFIT",value)
    for value in (True,float("nan"),0,1.):
        with pytest.raises(ValueError):
            led.close_paper(TICKER,value,"TAKE_PROFIT",NOW)
    with pytest.raises(ValueError):
        led.close_paper(TICKER,.6,"BAD_REASON",NOW)
    with pytest.raises(ValueError):
        led.close_paper(TICKER,.6,"TIME_STOP",NOW-10)
    led.conn.execute("UPDATE paper_trades SET entry_fee=NULL WHERE ticker=?",(TICKER,))
    led.conn.commit()
    result=led.close_paper(TICKER,.6,"TAKE_PROFIT",NOW)
    assert result["entry_fee"]==led.paper_fee(.45)
    assert result["exit_fee"]==led.paper_fee(.6)
    assert led.close_paper(TICKER,.8,"TAKE_PROFIT",NOW+5) is None
    led.grade(TICKER,"no",NOW+450)
    row=led.data()["trades"][0]
    assert row["exit_price"]==.6 and row["exit_fee"]==led.paper_fee(.6)
    assert row["exit_reason"]=="TAKE_PROFIT" and row["net_pnl"]==result["net_pnl"]
    assert led.data()["stats"]["early_exit_paper_trades"]==1
    with pytest.raises(ValueError):
        led.grade(TICKER,"unknown",NOW)
    led.conn.close()


def test_student_t_benchmark_source_and_final_window_fail_closed():
    assert sp._sigma_benchmark_only(None) is None
    assert sp._sigma_benchmark_only([{"source":"coinbase"}]*32) is None
    assert sp._sigma_benchmark_only([{"source":"cfbenchmarks_brti_authenticated_live",
                                      "close":0}]*31) is None
    assert sp._sigma_benchmark_only(minute_bars(46)) is not None
    assert sp._regularized_beta(-1,2.,3.)==0
    assert sp._regularized_beta(2,2.,3.)==1
    assert 0<sp._regularized_beta(.6,2.,3.)<1
    assert math.isfinite(sp._beta_cf(2.,1.,.75))
    assert sp._student_t_cdf(-3)<.1 and sp._student_t_cdf(3)>.9
    bars=minute_bars()
    m=market()
    expected=brti(completed_minute_sigma_45=.002)
    assert sp.forecast(m,expected,bars,NOW)["available"]
    assert not sp.forecast(None,expected,bars,NOW)["available"]
    assert not sp.forecast(m,None,bars,NOW)["available"]
    assert not sp.forecast({**m,"target":0},expected,bars,NOW)["available"]
    assert not sp.forecast(market(1000),expected,bars,NOW)["available"]
    assert not sp.forecast(market(-5),expected,bars,NOW)["available"]
    assert not sp.forecast(m,brti(status="STALE"),bars,NOW)["available"]
    assert not sp.forecast(m,brti(latest_value_usd="bad"),bars,NOW)["available"]
    assert not sp.forecast(m,brti(source_ts_ms=0),bars,NOW)["available"]
    assert not sp.forecast(m,brti(completed_minute_sigma_45=None),[],NOW)["available"]
    assert not sp.forecast(m,brti(completed_minute_sigma_45=None),
                           [{"source":"wrong"}]*40,NOW)["available"]
    assert sp._brti_sigmas(None,.003)==(None,.003)
    assert sp._brti_sigmas([{"source":"wrong"}]*34,.003)==(None,.003)
    assert sp._brti_sigmas([{"source":"cfbenchmarks_brti_authenticated_live",
                    "close":64000.+i*3+(i%2)*20} for i in range(34)],None)[1] is not None
    missing=[dict(x) for x in bars]
    missing[-1]["t"]+=90
    assert sp._brti_sigmas(missing,.003)==(None,.003)
    zeros=[dict(x) for x in bars]
    zeros[-1]["close"]=0
    assert sp._brti_sigmas(zeros,.003)==(None,.003)
    short=market(45)
    assert not sp.forecast(short,expected,bars,NOW)["available"]
    window={"window_end_ts":short["close_ts"],"complete_prefix":True,
            "observed_seconds":15,"expected_seconds":15,
            "observed_mean_usd":64005.}
    partial=sp.forecast(short,expected|{"settlement_window_stats":window},bars,NOW)
    assert partial["available"] and partial["observed_final_minute_seconds"]==15
    for invalid in (None,{},window|{"complete_prefix":False},
                    window|{"window_end_ts":0}):
        assert not sp.forecast(short,expected|{"settlement_window_stats":invalid},bars,NOW)["available"]
    for invalid in (window|{"observed_seconds":True},
                    window|{"observed_seconds":60},
                    window|{"expected_seconds":3},
                    window|{"observed_mean_usd":-1}):
        assert not sp.forecast(short,expected|{"settlement_window_stats":invalid},bars,NOW)["available"]
    empty=window|{"observed_seconds":0,"expected_seconds":0,
                  "observed_mean_usd":None}
    assert sp.forecast(short,expected|{"settlement_window_stats":empty},bars,NOW)["available"]


def test_five_second_rolling_sigma_reconnect_and_source_gaps():
    source=int(NOW)
    assert live._three_minute_five_second_sigma({},source) is None
    window={}
    start=(source//5)*5-185
    for tick in range(start,start+185):
        window[tick]=64000. + (tick-start)*.2 + (tick%5)*.1
    val=live._three_minute_five_second_sigma(window,source)
    assert val is not None and val>0
    window[start+1]=-2.
    window[start+2]=float("nan")
    window[start+3]=0.
    assert live._three_minute_five_second_sigma(window,source) is None
