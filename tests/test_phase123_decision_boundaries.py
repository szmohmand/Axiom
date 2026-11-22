"""BRTI-only Phase 2 decision branches: real inputs, no orders."""
import math
from types import SimpleNamespace

import pytest

from app import axiom_brain as brain
from app.orderbook import normalize_orderbook


NOW=1_800_000_000.


def candles(n=65, last=100., direction=None):
    base=int(NOW//60)*60-n*60
    out=[]
    for i in range(n):
        p=100.0 + .002*math.sin(i)
        out.append({"t":base+i*60,"open":p,"close":p,
                    "high":p+.02,"low":p-.02,
                    "source":brain.BRTI_SOURCE,"volume":None})
    if direction=="UP":
        out[-1].update(open=100.,close=100.4,high=100.42,low=99.99)
    elif direction=="DOWN":
        out[-1].update(open=100.,close=99.6,low=99.58,high=100.01)
    return out


def fives(n=13):
    base=int(NOW//300)*300-n*300
    return [{"t":base+i*300,"open":100.,"close":100.,
             "high":100.1,"low":99.9,
             "source":brain.BRTI_SOURCE,"volume":None} for i in range(n)]


def market(seconds=450,target=100.48):
    return {"ticker":"KXBTC15M-COVER-BRAIN","target":target,
            "close_ts":NOW+seconds,"seconds_left":seconds}


def book(yes=".30",no=".68",t=NOW,size="5"):
    return normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[[yes,size]],"no_dollars":[[no,size]]}},
        market()["ticker"],t)


def ref(spot=100.4, sigma=.0006):
    return {"status":"STREAMING","authenticated_stream_verified":True,
            "source_ts_ms":int(NOW*1000),
            "axiom_received_at_ms":int(NOW*1000),
            "latest_value_usd":str(spot),
            "brti_sigma_5s_3m":sigma}


def flow(direction="UP"):
    return {"available":True,"confirmed_direction":direction,
            "CVD_norm_90s":.5,"cvd_90s_span":85,
            "trade_count_90s":60,"taker_buy_share_90s":.8,
            "taker_sell_share_90s":.2,
            "delta_venue":None,"delta_venue_pct":None,"synthetic_price":None,
            "depth_depletion":{"coinbase":{
                "bid":{"ratio_to_normal":.8,"below_half_for_15s":False},
                "ask":{"ratio_to_normal":.7,"below_half_for_15s":False}}},
            "OBI_spot":.4,"D_spot":10}


class Tape:
    def __init__(self, **kwargs):
        self.data={"mid_jump_20s":None,
            "implied_sigma_quartile_24h":.002,
            "implied_history_ready":True}
        self.data.update(kwargs)
    def snapshot(self, *_):
        return self.data


@pytest.fixture
def brain_ready(monkeypatch):
    monkeypatch.setattr(brain,"brti_settlement_forecast",
                        lambda *args:{"available":True,"prob_above":.94,
                            "prob_below":.94,"method":"test_brti_t",
                            "volatility_1m":.002})
    monkeypatch.setattr(brain,"_et_windows",lambda *_:(False,False))
    monkeypatch.setattr(brain,"_regime",lambda *_:"SQUEEZE")
    monkeypatch.setattr(brain,"_implied_minute_sigma",lambda *_:.0004)
    return lambda *args,**kwargs:brain.decide(*args,**kwargs)


def test_wait_paths_from_bad_contract_fair_window_structure_book_and_flow(brain_ready,monkeypatch):
    call=brain_ready
    assert call(None,ref(),[],[],book(),flow(),NOW)["action"]=="WAIT"
    monkeypatch.setattr(brain,"brti_settlement_forecast",
                        lambda *args:{"available":False,"reason":"Incomplete authenticated source"})
    out=call(market(),ref(),candles(),fives(),book(),flow(),NOW)
    assert out["reason"]=="Incomplete authenticated source"
    monkeypatch.setattr(brain,"brti_settlement_forecast",
                        lambda *args:{"available":True,"prob_above":.94,
                            "prob_below":.94,"method":"test_brti_t",
                            "volatility_1m":.002})
    monkeypatch.setattr(brain,"_et_windows",lambda *_:(True,False))
    assert call(market(),ref(),candles(),fives(),book(),flow(),NOW)["kill_switch_triggered"]
    monkeypatch.setattr(brain,"_et_windows",lambda *_:(False,False))
    for seconds in (90,800):
        out=call(market(seconds),ref(),candles(),fives(),book(),flow(),NOW)
        assert out["reason"]=="Outside 3-12 minute entry window"
    assert "contiguous" in call(market(),ref(),candles(15),[],book(),flow(),NOW)["reason"]
    bad=candles()
    bad[-1]["source"]="coinbase"
    assert call(market(),ref(),bad,fives(),book(),flow(),NOW)["action"]=="WAIT"
    assert "book" in call(market(),ref(),candles(),fives(),book(t=NOW-60),flow(),NOW)["reason"]
    assert "not healthy" in call(market(),ref(),candles(),fives(),book(),{},NOW)["reason"]
    assert call(market(),ref(spot=0),candles(),fives(),book(),flow(),NOW)["action"]=="WAIT"


def test_compression_breakout_iv_ceiling_ratio_and_direction_guards(brain_ready,monkeypatch):
    call=brain_ready
    basis=candles(direction="UP")
    kwargs={"tape":Tape()}
    candidate=call(market(),ref(),basis,fives(),book(),flow(),NOW,**kwargs)
    assert candidate["action"]=="BUY_YES",candidate
    assert candidate["invalidation_rule"]["type"]=="BRTI_CLOSE_BACK_INSIDE_RANGE"
    assert candidate["R_sigma"]>1.65
    low=call(market(),ref(sigma=None),basis,fives(),book(),flow(),NOW,**kwargs)
    assert low["action"]=="WAIT"
    low=call(market(),ref(),basis,fives(),book(),flow(),NOW,tape=Tape(
        implied_sigma_quartile_24h=None,implied_history_ready=True))
    assert low["action"]=="WAIT"
    low=call(market(),ref(),basis,fives(),book(),flow(),NOW,tape=Tape(
        implied_history_ready=False,implied_sigma_quartile_24h=None))
    assert low["iv_guard"]=="cold_start_ceiling"
    monkeypatch.setattr(brain,"_implied_minute_sigma",lambda *_:.004)
    too_wide=call(market(),ref(),basis,fives(),book(),flow(),NOW,**kwargs)
    assert too_wide["action"]=="WAIT"
    monkeypatch.setattr(brain,"_implied_minute_sigma",lambda *_:.0004)
    empty_flow=flow()
    empty_flow["depth_depletion"]={}
    assert call(market(),ref(),basis,fives(),book(),empty_flow,NOW,**kwargs)["action"]=="WAIT"
    low_span=flow()
    low_span["cvd_90s_span"]=10
    assert call(market(),ref(),basis,fives(),book(),low_span,NOW,**kwargs)["action"]=="WAIT"
    low_trade=flow()
    low_trade["trade_count_90s"]=1
    assert call(market(),ref(),basis,fives(),book(),low_trade,NOW,**kwargs)["action"]=="WAIT"
    monkeypatch.setattr(brain,"_implied_minute_sigma",lambda *_:.001)
    low_ratio=call(market(),ref(sigma=.00001),basis,fives(),book(),flow(),NOW,**kwargs)
    assert low_ratio["action"]=="WAIT"
    monkeypatch.setattr(brain,"_implied_minute_sigma",lambda *_:.0004)
    uncertain=flow()
    uncertain["taker_buy_share_90s"]=.5
    uncertain["taker_sell_share_90s"]=.5
    assert call(market(),ref(),basis,fives(),book(),uncertain,NOW,**kwargs)["action"]=="WAIT"
    down=flow("DOWN")
    down["taker_buy_share_90s"]=.15
    down["taker_sell_share_90s"]=.85
    down_out=call(market(target=99.52),ref(spot=99.6),
                  candles(direction="DOWN"),fives(),
                  book(yes=".70",no=".30"),down,NOW,**kwargs)
    assert down_out["action"]=="BUY_NO",down_out


def test_twap_and_sweep_edge_candidate_filters(brain_ready,monkeypatch):
    call=brain_ready
    monkeypatch.setattr(brain,"_et_windows",lambda *_:(False,True))
    f=flow()
    f.update(CVD_norm_5m=.6,rho_trade=.4,cvd_5m_span=270)
    out=call(market(target=100.4),ref(),candles(),fives(),book(),f,NOW)
    assert out["action"]=="BUY_YES",out
    assert out["setup_type"]=="US_SESSION_TWAP_DRIFT"
    assert out["regime"]=="SQUEEZE"
    # Warmup regime still admits this shorter-history setup.
    short=call(market(target=100.4),ref(),candles(35),fives(7),book(),f,NOW)
    assert short["action"]=="BUY_YES"
    for changes in ({"rho_trade":None},{"cvd_5m_span":0},
                    {"CVD_norm_5m":.1},{"CVD_norm_5m":None}):
        assert call(market(target=100.4),ref(),candles(),fives(),book(),
                    {**f,**changes},NOW)["action"]=="WAIT"
    assert call(market(target=90.),ref(),candles(),fives(),book(),f,NOW)["action"]=="WAIT"
    monkeypatch.setattr(brain,"_et_windows",lambda *_:(False,False))
    monkeypatch.setattr(brain,"_regime",lambda *_:"CHOP")
    jumpflow=flow()
    jumpflow.update(delta_venue=.2,delta_venue_pct=.002,
                    synthetic_price=100.4,outlier_venue="coinbase",
                    venue_midpoints={"coinbase":100.6,"kraken":100.4,"bitstamp":100.39},
                    depth_depletion={"coinbase":{
                        "ask":{"ratio_to_normal":.4,"below_half_for_15s":True},
                        "bid":{"ratio_to_normal":.4,"below_half_for_15s":True}}})
    fade=call(market(),ref(),candles(),fives(),
              book(yes=".70",no=".30"),jumpflow,NOW,
              tape=Tape(mid_jump_20s=.2))
    assert fade["action"]=="BUY_NO",fade
    assert fade["setup_type"]=="SINGLE_VENUE_SWEEP_FADE"
    for jump,patched in ((.05,{}),(.2,{"delta_venue_pct":None}),
                         (.2,{"delta_venue_pct":.0001}),
                         (.2,{"synthetic_price":102.}),
                         (.2,{"outlier_venue":"missing"}),
                         (-.2,{})):
        assert call(market(),ref(),candles(),fives(),
                    book(yes=".70",no=".30"),{**jumpflow,**patched},NOW,
                    tape=Tape(mid_jump_20s=jump))["action"]=="WAIT"
    little=flow()
    little.update(jumpflow)
    little["depth_depletion"]={"coinbase":{
        "ask":{"ratio_to_normal":.4,"below_half_for_15s":False},
        "bid":{"ratio_to_normal":.4,"below_half_for_15s":False}}}
    assert call(market(),ref(),candles(),fives(),book(yes=".70",no=".30"),
                little,NOW,tape=Tape(mid_jump_20s=.2))["action"]=="WAIT"
    low=flow()
    low.update(jumpflow)
    low.update(venue_midpoints={"coinbase":100.2},synthetic_price=100.4)
    assert call(market(),ref(),candles(),fives(),book(),low,NOW,
                tape=Tape(mid_jump_20s=-.2))["action"] in ("WAIT","BUY_YES")
    # No candidate may assume the top ask is executable without one contract.
    assert call(market(),ref(),candles(),fives(),
                book(yes=".70",no=".30",size=".3"),jumpflow,NOW,
                tape=Tape(mid_jump_20s=.2))["action"]=="WAIT"
    assert call(market(),ref(),candles(),fives(),
                book(yes=".40",no=".40"),jumpflow,NOW,
                tape=Tape(mid_jump_20s=.2))["action"]=="WAIT"
    monkeypatch.setattr(brain,"brti_settlement_forecast",
                        lambda *a:{"available":True,"prob_above":.99,
                                  "prob_below":.20,"method":"test_brti_t",
                                  "volatility_1m":.002})
    assert call(market(),ref(),candles(),fives(),
                book(yes=".70",no=".30"),jumpflow,NOW,
                tape=Tape(mid_jump_20s=.2))["action"]=="WAIT"


def test_short_history_invalid_bars_and_tape_fade_warmup(brain_ready,monkeypatch):
    monkeypatch.setattr(brain,"_et_windows",lambda *_:(False,False))
    monkeypatch.setattr(brain,"_regime",lambda *_:"CHOP")
    f=flow()
    f.update(delta_venue=.2,delta_venue_pct=.002,
             synthetic_price=100.4,outlier_venue="coinbase",
             venue_midpoints={"coinbase":100.6},
             depth_depletion={"coinbase":{
                "ask":{"below_half_for_15s":True,"ratio_to_normal":.4}}})
    out=brain_ready(market(),ref(),candles(32),fives(6),
                    book(yes=".70",no=".30"),f,NOW,
                    tape=Tape(mid_jump_20s=.2))
    assert out["action"]=="BUY_NO"
    assert out["regime"]=="WARMING"
