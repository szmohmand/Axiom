"""Keep the dashboard contract consistent with the *actual* voting engine.

An enhanced AXIOM forecast uses the arithmetic mean of every available BTC
voter. The older stand-alone baseline still uses a median. Neither Kalshi
quotes nor a high intermodel spread may silently alter the enhanced forecast.
"""
import math
import statistics

from app import ensemble


def completed_candles(now=1800007200, n=75):
    start=int(now//60)*60-n*60
    out=[]
    for i in range(n):
        v=64000+2*i+math.sin(i/3)
        out.append({"t":start+i*60,"open":v-1,"close":v,
                    "high":v+2,"low":v-2,"volume":9+i/10})
    return out


def test_integrated_ensemble_mean_method_and_agreement_share_identical_voters(monkeypatch):
    now=1800007200
    candles=completed_candles(now)
    spot=candles[-1]["close"]
    market={"ticker":"KXBTC15M-DIAGNOSTIC","target":spot+6,
            "close_ts":now+600,"seconds_left":600,"yes_ask":.99}
    # Force a large experimental BTC-only difference to verify disagreement
    # stays visible rather than disabling an otherwise available prediction.
    monkeypatch.setattr(ensemble,"pressure_forecast",
                        lambda *a,**k:{"available":True,"prob_above":.98,
                                      "components":{"btc_taker_cvd_2m":.9},
                                      "combined_z_shift":1.8})
    result=ensemble.engine_pack(spot,market,candles,
                               context={"timeframes":{},"microstructure":{}},
                               now=now)
    assert result["available"] and result["all_signal_integration_active"]
    assert result["method"]=="experimental-equal-weight-mean-consensus"
    members=[e for e in result["engines"]
             if e["name"] in result["active_predictive_models"]]
    assert len(members)==len(result["active_predictive_models"])
    assert all(e["available"] for e in members)
    probabilities=[e["prob_above"] for e in members]
    assert result["prob_above"]==round(statistics.fmean(probabilities),5)
    assert result["agreement"]==sum((p>.5)==(result["prob_above"]>.5)
                                    for p in probabilities)
    assert 0<=result["agreement"]<=len(members)
    assert result["spread"]==round(max(probabilities)-min(probabilities),5)
    assert result["spread"]>.30
    assert result["side"] in ("ABOVE","BELOW")
    # Kalshi market bids, asks, volumes and quotes never vote.
    changed={**market,"market_mid":.01,"yes_ask":.01,"no_ask":.99,
             "book_imbalance":.99}
    assert result==ensemble.engine_pack(spot,changed,candles,
                           context={"timeframes":{},"microstructure":{}},
                           now=now)


def test_standalone_legacy_mode_preserves_median_method():
    now=1800007200
    candles=completed_candles(now)
    spot=candles[-1]["close"]
    market={"ticker":"KXBTC15M-DIAGNOSTIC","target":spot+6,
            "close_ts":now+600,"seconds_left":600}
    baseline=ensemble.engine_pack(spot,market,candles)
    assert baseline["available"]
    assert baseline["all_signal_integration_active"] is False
    assert baseline["method"]=="experimental-median-consensus"
    values=[e["prob_above"] for e in baseline["engines"]
            if e["name"] in baseline["active_predictive_models"]]
    assert baseline["prob_above"]==round(statistics.median(values),5)
