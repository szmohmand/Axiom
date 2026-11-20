"""Intracontract resale lane, independent of final Kalshi settlement winner."""
import pytest
from app.intracontract import (IntracontractTracker, unavailable, wait,
                               resale_screen, resale_position_review)
from app.orderbook import normalize_orderbook
from test_e2e_synthetic import env

T=1800000000


def data(ts=T,ticker="KXBTC15M-TEST",yes=".38",no=".60",yes_size="35",no_size="35",btc=60000):
    market={"ticker":ticker,"close_ts":T+600,"seconds_left":600,
            "target":60000,"market_mid":.39}
    book=normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[[yes,yes_size]],"no_dollars":[[no,no_size]]}},ticker,ts)
    signals={"available":True,"price_reference":"COINBASE_PROXY_NOT_SETTLEMENT",
             "reference_value":btc,"side":"ABOVE"}
    return market,book,signals


def test_two_snapshots_track_actual_spacing_midpoint_depth_and_btc():
    track=IntracontractTracker()
    m,b,s=data()
    first=track.observe(m,b,s,T)
    assert first["available"] and first["observations"]==1 and first["last_move"] is None
    m,b,s=data(T+5,yes=".40",no=".58",yes_size="40",no_size="30",btc=60010)
    second=track.observe(m,b,s,T+5)
    delta=second["last_move"]
    assert second["observations"]==2
    assert delta["observed_seconds"]==5
    assert delta["yes_midpoint_change"]==pytest.approx(.02)
    assert delta["btc_reference_change_bps"]>1
    assert delta["yes_bid_level_change"]["net_addition_contracts"]==40
    assert delta["yes_bid_level_change"]["net_removal_contracts"]==35
    assert delta["no_bid_level_change"]["net_change_contracts"]==-5
    assert second["max_observed_yes_mid_move"]==pytest.approx(.02)
    assert not second["net_book_change_is_order_events"]
    assert second["funding"]=="NOT_CONNECTED"
    op=resale_screen(m,b,s,second,T+5)
    assert op["action"]=="BUY_CANDIDATE" and op["side"]=="YES"
    assert op["entry_ask"]==pytest.approx(.42)
    assert op["break_even_exit_bid"] > op["entry_ask"]
    assert op["net_profit_verified"] is False and not op["order_placed"]
    assert op["settlement_winner_not_required"] is True


def test_short_falling_btc_midpoint_can_issue_no_resale_watch():
    track=IntracontractTracker()
    m,b,s=data()
    track.observe(m,b,s,T)
    m,b,s=data(T+5,yes=".36",no=".62",btc=59985)
    timeline=track.observe(m,b,s,T+5)
    op=resale_screen(m,b,s,timeline,T+5)
    assert op["side"]=="NO" and op["action"]=="BUY_CANDIDATE"
    assert op["current_sell_bid"]==pytest.approx(.62)


def test_swing_high_and_low_proxies_are_not_real_order_sweeps():
    track=IntracontractTracker()
    for seconds,yes,no in [(0,".38",".60"),(5,".40",".58"),(10,".37",".61"),(15,".41",".57")]:
        m,b,s=data(T+seconds,yes=yes,no=no,btc=60000+seconds)
        out=track.observe(m,b,s,T+seconds)
        if seconds==10:
            assert out["rejection_proxy"]=="YES_UP_SWING_REJECTION_PROXY"
        if seconds==15:
            assert out["rejection_proxy"]=="YES_DOWN_SWING_REJECTION_PROXY"
    assert out["observations"]==4


def test_rejects_stale_books_bad_reference_bad_quote_and_resets_on_rollover():
    track=IntracontractTracker()
    m,b,s=data()
    assert track.observe(m,b,s,T)["available"]
    assert not track.observe(m,b,{**s,"available":False},T)["available"]
    assert not track.observe(m,b,s,T+90)["available"]
    assert not track.observe(m,{**b,"best":{"YES":{"bid":None,"ask":None}}},s,T)["available"]
    assert not track.observe(m,b,{**s,"reference_value":None},T)["available"]
    assert track.observe(m,b,s,T)["observations"]==1
    m2,b2,s2=data(T+5,ticker="KXBTC15M-OTHER")
    assert track.observe(m2,b2,s2,T+5)["observations"]==1
    assert track.observe(m2,b2,s2,T+5)["observations"]==1  # duplicate timestamp doesn't build fake delta
    m3,b3,s3=data(T+70,ticker="KXBTC15M-OTHER")
    assert track.observe(m3,b3,s3,T+70)["observations"]==1  # big gap does not bridge
    assert not unavailable("missing")["available"]
    assert wait("insufficient")["action"]=="WAIT"


def test_mixed_reference_sources_never_infer_btc_move():
    track=IntracontractTracker()
    m,b,s=data()
    track.observe(m,b,s,T)
    m,b,s=data(T+5,yes=".40",no=".58",btc=60005)
    s["price_reference"]="AUTHENTICATED_LIVE_BRTI"
    t=track.observe(m,b,s,T+5)
    assert t["last_move"]["btc_reference_change_bps"] is None
    assert not t["last_move"]["source_same"]
    assert resale_screen(m,b,s,t,T+5)["action"]=="WAIT"


@pytest.mark.parametrize("kind",["missing_timeline","book_stale","no_motion","opposite","near_close","no_depth","wide_spread"])
def test_resale_entry_requires_measured_correlated_motion_time_and_executable_depth(kind):
    tr=IntracontractTracker()
    m,b,s=data()
    first=tr.observe(m,b,s,T)
    m,b,s=data(T+5,yes=".40",no=".58",btc=60010)
    timeline=tr.observe(m,b,s,T+5)
    if kind=="missing_timeline":
        timeline=first
    if kind=="book_stale":
        t=90
    else:
        t=5
    if kind=="no_motion":
        timeline={**timeline,"last_move":{**timeline["last_move"],
                    "yes_midpoint_change":.001}}
    if kind=="opposite":
        timeline={**timeline,"last_move":{**timeline["last_move"],
                    "btc_reference_change_bps":-2}}
    if kind=="near_close":
        m["seconds_left"]=119
    if kind=="no_depth":
        m,b,s=data(T+5,yes=".40",no=".58",yes_size="1",btc=60010)
    if kind=="wide_spread":
        m,b,s=data(T+5,yes=".35",no=".57",btc=60010)
    got=resale_screen(m,b,s,timeline,T+t)
    assert got["action"]=="WAIT"
    assert not got["order_placed"]


@pytest.mark.parametrize("scenario,action",[
    ("gain_and_fade","SELL_CANDIDATE"),("gain_and_rise","HOLD"),
    ("loss_and_opposition","EXIT_REVIEW"),("loss_no_opposition","HOLD")])
def test_depth_based_paper_exit_is_not_a_realized_profit(scenario,action):
    m,b,s=data()
    positive=scenario.startswith("gain")
    losing=not positive
    s["side"]="BELOW" if scenario=="loss_and_opposition" else "ABOVE"
    position={"side":"YES","entry":.20 if positive else .48}
    quote_change=-.03 if scenario=="gain_and_fade" else .02
    timeline={"last_move":{"yes_midpoint_change":quote_change}}
    result=resale_position_review(position,m,b,s,timeline,T)
    assert result["action"]==action
    assert result["net_profit_verified"] is False
    assert result["realized_profit"] is False
    assert result["displayed_exit_depth_complete"]
    assert result["estimated_net_per_paper_contract"] > 0 if positive else result["estimated_net_per_paper_contract"] < 0


def test_paper_exit_missing_position_wrong_ticker_and_unfillable_book():
    m,b,s=data()
    assert resale_position_review(None,m,b,s,None,T)["action"]=="WAIT"
    assert "same-contract" in resale_position_review({"side":"YES","entry":.3},m,b,s,None,T+90)["reason"]
    assert "Invalid paper" in resale_position_review({"side":"WHAT","entry":.3},m,b,s,None,T)["reason"]
    tiny_m,tiny_b,tiny_s=data(yes_size=".5")
    assert "Cannot sell" in resale_position_review({"side":"YES","entry":.3},
                                                     tiny_m,tiny_b,tiny_s,None,T)["reason"]


def test_full_fastapi_poll_api_paper_and_rollover_are_separate_from_final_winner(env):
    main,clock,provider,client,_=env
    main.AUTO_PAPER=False
    clock.now=provider.close-600
    provider.orderbook=lambda market,now=None: data(
        clock.now,ticker=market["ticker"],yes=".38",no=".60",btc=90325)[1]
    start=main.update_once()
    assert start["intracontract"]["available"] and start["intracontract"]["observations"]==1
    assert start["resale_setup"]["action"]=="WAIT"
    clock.now+=5
    provider.price=lambda:90340
    provider.orderbook=lambda market,now=None: data(
        clock.now,ticker=market["ticker"],yes=".40",no=".58",btc=90340)[1]
    second=main.update_once()
    assert second["intracontract"]["observations"]==2
    assert second["resale_setup"]["action"]=="BUY_CANDIDATE"
    assert not second["resale_setup"]["order_placed"]
    assert not second["trade_decision"]["order_placed"]
    payload=client.get("/api/state").json()
    assert payload["intracontract"]["available"]
    assert payload["resale_setup"]["settlement_winner_not_required"]
    assert "resaleIntelligenceSection" in client.get("/").text
    auth={"Authorization":"Bearer synthetic-local-testing-token"}
    assert client.post("/api/paper",json={"side":"YES"},headers=auth).status_code==200
    paper=client.get("/api/state").json()["resale_position_review"]
    assert paper["action"] in ("HOLD","SELL_CANDIDATE","EXIT_REVIEW","WAIT")
    assert not paper["order_placed"]
    provider.ticker="KXBTC15M-E2E-SYNTH-2"
    clock.now+=5
    rollover=main.update_once()
    assert rollover["intracontract"]["observations"]==1
    def fail_price():
        raise RuntimeError("injected Coinbase price outage")
    provider.price=fail_price
    clock.now+=5
    degraded=main.update_once()
    assert not degraded["ok"] and degraded["resale_setup"]["action"]=="WAIT"
    assert not degraded["intracontract"]["available"]
    assert client.get("/api/state").json()["resale_setup"]["action"]=="WAIT"


def test_corrupt_snapshot_analysis_is_localized_and_does_not_touch_settlement(env,monkeypatch):
    main,clock,provider,client,_=env
    main.AUTO_PAPER=False
    clock.now=provider.close-600
    provider.orderbook=lambda market,now=None: data(
        clock.now,ticker=market["ticker"])[1]
    original=main.update_once()
    assert original["ok"] and original["model"]["available"]
    calls=main.ledger.data()["count"]["calls"]
    def broken_history(*args,**kwargs):
        raise ValueError("injected invalid book-history analysis")
    monkeypatch.setattr(main.movement_tracker,"observe",broken_history)
    clock.now+=5
    result=main.update_once()
    assert result["ok"] and result["model"]["available"]
    assert not result["intracontract"]["available"]
    assert result["resale_setup"]["action"]=="WAIT"
    assert not result["resale_setup"]["order_placed"]
    assert result["execution_intelligence"]["order_placed"] is False
    assert main.ledger.data()["count"]["calls"]==calls
