"""Single-process web server + live background research/paper-trading worker."""
from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import csv
import io
import math
import os
import threading
import time
import traceback
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from .feeds import LiveProvider, DemoProvider
from .engine import scalp_signal
from .ensemble import engine_pack, execution_screen
from .market_structure import BTCFlowTracker, timeframes
from .contract_repricing import ContractRepricingModel, unavailable as unavailable_contract_repricing
from .storage import Ledger
from .settlement_research import shadow_forecast_from_candles, unavailable as unavailable_research_shadow
from .candlestick_context import read_candlestick_context, unavailable as unavailable_candle_context
from .candlestick_challenger import derive_candlestick_challenger, unavailable as unavailable_candle_challenger
from .orderbook import unavailable as unavailable_book
from .execution_evidence import examine_liquidity
from .brti_live import BRTITracker, run_worker as brti_reference_worker
from .settlement_probability import forecast as brti_settlement_forecast
from .axiom_brain import ConstituentFlow, MarketTape, decide as axiom_decide, start_flow_workers
from .paper_exits import evaluate_exit
from .decision_signals import derive_signals, unavailable as unavailable_signals, execution_decision
from .intracontract import (IntracontractTracker, unavailable as unavailable_timeline,
                            wait as wait_resale, resale_screen, resale_position_review)
from .binance_telemetry import BinanceTelemetry, spot_worker as binance_spot_worker
from .lag_intelligence import BinanceKalshiLagTracker, wait as wait_binance_lag
from .depth_intelligence import (analyze_opportunities, execution_guidance,
                                  unavailable_opportunity, unavailable_execution)

ROOT = Path(__file__).parent
DEMO = os.environ.get('DEMO_MODE', '0') == '1'
AUTO_PAPER = os.environ.get('AUTO_PAPER', '0') == '1'
POLL_SECONDS = max(5, int(os.environ.get('POLL_SECONDS', '15')))
DATA_PATH = os.environ.get('DATA_PATH', str(ROOT.parent/'data'/'bot.sqlite3'))
ADMIN_TOKEN = os.environ.get('BOT_ADMIN_TOKEN','')
BRTI_LIVE_ENABLED = (not DEMO and os.environ.get('BRTI_LIVE_ENABLED','1') == '1')
BINANCE_INTELLIGENCE_ENABLED = False  # Phase 1: no Binance connection or active input
# Opt-in shadow grading ONLY: no voting, execution, or historical rewriting.
CANDLESTICK_SHADOW_GRADING_ENABLED = os.environ.get('CANDLESTICK_SHADOW_GRADING_ENABLED','0') == '1'
brti_tracker = BRTITracker(enabled=BRTI_LIVE_ENABLED)
flow_tracker = ConstituentFlow()
market_tape = MarketTape()
binance_telemetry = BinanceTelemetry(enabled=BINANCE_INTELLIGENCE_ENABLED)
provider = DemoProvider() if DEMO else LiveProvider()
ledger = Ledger(DATA_PATH)
state_lock = threading.RLock()
movement_tracker = IntracontractTracker()
binance_lag_tracker = BinanceKalshiLagTracker()
market_flow_tracker = BTCFlowTracker()
contract_repricing_tracker = ContractRepricingModel()
state = {'mode':'DEMO' if DEMO else 'LIVE','last_attempt':None,'last_success':None,
         'market':None,'spot':None,'model':None,'engines':[],'scalp':None,'opportunity':None,'candles':[],
         'research_shadow':unavailable_research_shadow('No completed research observation yet'),
         'candlestick_context':unavailable_candle_context('Awaiting fresh completed BTC candles'),
         'candlestick_challenger':unavailable_candle_challenger('Awaiting independent ensemble and candle context'),
         'orderbook':unavailable_book(None,'No aggregated market depth yet'),
         'depth_opportunity':unavailable_opportunity('No independently evaluated depth yet'),
         'execution_intelligence':unavailable_execution('No independently evaluated depth yet'),
          'btc_signals':unavailable_signals('Awaiting fresh market inputs'),
          'trade_decision':execution_decision(None,None,None,None,None,time.time()),
          'intracontract':unavailable_timeline('Waiting for consecutive price snapshots'),
          'resale_setup':wait_resale('Waiting for observed intracontract moves'),
          'binance_intelligence':binance_telemetry.snapshot(),
          'binance_kalshi_delay':wait_binance_lag('Awaiting real Binance and Kalshi quotes'),
          'higher_timeframes':timeframes([],time.time()),
          'market_microstructure':{'available':False,'reason':'Awaiting genuine BTC exchange trade flow'},
          'contract_repricing':unavailable_contract_repricing('Waiting for observed quotes'),
         'errors':{},'paper_auto_enabled':AUTO_PAPER,'watch':None,'candle_quality':None,
         'warmup':{'status':'STARTING'},'paper_exit':None,'status':'STARTING',
         'settlement':{'status':'NOT_CHECKED','last_attempt':None,'last_success':None,
                       'checked':0,'failed':0}}
shutdown = threading.Event()
# Failed settlement lookups are retained by ticker. A successful market poll cannot
# accidentally erase them, and a successful retry clears only that ticker's error.
settlement_failures = {}
last_grading_ticker = None  # round-robin cursor to prevent settlement queue starvation


def _error_message(exc):
    return f'{type(exc).__name__}: {str(exc)[:160]}'


def _refresh_status_locked():
    """Recompute operational status from the *combined* source and grading state.

    Called with state_lock held after each poll, grade, and worker failure.
    Synthetic DEMO is a mode label, not a blanket declaration of health.
    """
    if 'worker' in state['errors']:
        state['status'] = 'ERROR'
    elif state['errors']:
        state['status'] = 'DEGRADED'
    elif state['last_attempt'] is None:
        state['status'] = 'STARTING'
    elif state.get('forecast_warming') and not DEMO and state['market'] is not None and state['spot'] is not None:
        # BRTI transport/contract health is distinct from the 31-minute model
        # warmup. Service is healthy, but every prediction and paper entry WAITs.
        state['status'] = 'LIVE'
    elif (state['market'] is None or state['spot'] is None or
          not state['model'] or not state['model'].get('available') or
          len(state['candles']) < 31):
        state['status'] = 'DEGRADED'
    else:
        state['status'] = 'DEMO' if DEMO else 'LIVE'


def _view_locked(now):
    """Return a consistent read snapshot for both health and dashboard APIs.

    The worker may have stopped updating without raising an exception. In that
    case the last successful snapshot is NOT healthy indefinitely.
    """
    data = dict(state)
    data['errors'] = dict(state['errors'])
    data['settlement'] = dict(state['settlement'])
    data['live_briti'] = brti_tracker.snapshot()
    if DEMO:
        data['binance_intelligence'] = binance_telemetry.snapshot(now)
    attempted = state['last_attempt']
    data['heartbeat_age_seconds'] = None if attempted is None else max(0, round(now-attempted, 2))
    stale_limit = max(60, 3*POLL_SECONDS)
    if attempted is not None and now-attempted > stale_limit:
        data['errors']['worker_stale'] = f'Last market update is more than {stale_limit} seconds old'
    if data['status'] in ('LIVE','DEMO') and data['errors']:
        data['status'] = 'DEGRADED'
    data['ok'] = data['status'] in ('LIVE','DEMO') and not data['errors']
    if not DEMO:
        # No legacy shadow, Nison, Binance, repricing or extra execution
        # advisory paths run in live production, including degraded state.
        if not data['ok']:
            data['opportunity']={'side':'WAIT','edge':None,'entry_price':None,
                                 'reason':'Missing healthy authenticated BRTI'}
            data['depth_opportunity']=unavailable_opportunity('No healthy live BRTI/book')
            data['trade_decision']={'action':'WAIT','side':None,
                                     'order_placed':False,'read_only':True,
                                     'reason':'Live BRTI or Kalshi input unavailable'}
            data['execution_intelligence']=unavailable_execution('No healthy live BRTI/book')
        if 'worker_stale' in data['errors']:
            data['orderbook']=unavailable_book(
                data['market'].get('ticker') if data['market'] else None,
                'Worker stale; depth invalid')
            data['model']={'available':False,'side':'WAIT','prob_above':None,
                           'reason':'Market worker stale','engines':[]}
            data['engines']=[]
        return data
    if not data['ok']:
        # Previous opportunity quotes must not look actionable during an
        # outage even if they were calculated before the failure became known.
        data['opportunity'] = {'side':'WAIT','edge':None,'entry_price':None,
                               'reason':'System not healthy; paper opportunities paused'}
        data['depth_opportunity'] = unavailable_opportunity('System unhealthy; no depth-based entry advice')
        data['execution_intelligence'] = unavailable_execution('System unhealthy; no execution guidance')
        data['trade_decision'] = execution_decision(None,None,None,None,None,now)
        data['candlestick_context'] = unavailable_candle_context('Operational health degraded')
        data['candlestick_challenger'] = unavailable_candle_challenger('Operational health degraded')
        data['intracontract'] = unavailable_timeline('Operational health degraded')
        data['resale_setup'] = wait_resale('Operational health degraded')
        data['contract_repricing'] = unavailable_contract_repricing('Operational health degraded')
        data['binance_kalshi_delay'] = wait_binance_lag('Operational health degraded',data['binance_intelligence'])
    if 'worker_stale' in data['errors']:
        data['contract_repricing'] = unavailable_contract_repricing('Market worker stale')
        data['orderbook'] = unavailable_book(data['market'].get('ticker') if data['market'] else None,
                                               'Market worker stale; cached book invalid')
        data['research_shadow'] = unavailable_research_shadow('Market update worker is stale')
        # Preserve prior historical rows but never advertise a cached direction
        # as a current signal if the worker has stopped updating.
        data['model'] = {'available':False,'side':'WAIT','prob_above':None,
                         'prob_below':None,'reason':'Market update worker is stale'}
        data['engines'] = []
        data['opportunity'] = {'side':'WAIT','edge':None,'entry_price':None,
                               'reason':'Market updates stale; entries suspended'}
        data['scalp'] = {'side':'WAIT','entry':None,'stop':None,'target':None,
                         'reason':'Market updates stale; scalp suspended','atr':None}
    return data



def _brti_only_update_once(now):
    """Phase 3 live path: one BRTI brain and independent paper-exit processing."""
    errors = {}
    try:
        market = provider.market(now)
        if market:
            brti_tracker.observe_market(market, at_ms=int(now*1000))
        else:
            errors["kalshi"] = "No active Kalshi BTC15M contract"
    except Exception as exc:
        market = None
        errors["kalshi"] = _error_message(exc)

    try:
        reference = brti_tracker.snapshot(now_ms=int(now*1000))
        if reference.get("status") != "STREAMING":
            spot, candles = None, []
            errors["brti_stream"] = "Authenticated CF Benchmarks BRTI stream unavailable"
        else:
            value = reference.get("latest_value_usd")
            spot = float(value) if value is not None else None
            candles = reference.get("btc_1m_candles") or []
            if spot is None or not math.isfinite(spot) or spot <= 0:
                spot = None
                errors["brti_stream"] = "Invalid authenticated CF Benchmarks BRTI index value"
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        reference = {"status": "UNAVAILABLE", "reason": _error_message(exc)}
        spot, candles = None, []
        errors["brti_stream"] = "Invalid authenticated BRTI snapshot"

    five = reference.get("btc_5m_candles") or []
    book = unavailable_book(market.get("ticker") if market else None, "No current Kalshi depth")
    if market:
        reader = getattr(provider, "orderbook", None)
        if callable(reader):
            try:
                book = reader(market, now)
            except Exception as exc:
                book = unavailable_book(market["ticker"], _error_message(exc))
    # The received Kalshi book may postdate the poll-start clock by up to 2s.
    signal_now = max(now, float(book.get("received_at") or now))
    flow = flow_tracker.snapshot(signal_now)
    decision = {"action": "WAIT", "setup_type": "NONE", "fair_prob": None,
                "entry_price": None, "take_profit": None,
                "invalidation_rule": None, "invalidation_price": None,
                "kill_switch_triggered": False, "exit_signal": None,
                "side": None, "prob_above": None, "prob_below": None,
                "forecast_available": False, "order_placed": False,
                "read_only": True, "reason": "Awaiting authenticated BRTI and Kalshi"}
    position = None
    paper_exit = None
    # Close existing paper positions even when independent forecasting or
    # constituent buffers are warming. One authenticated BRTI source only;
    # early resale requires actual current displayed one-contract bid depth.
    if market:
        try:
            position = ledger.open_paper(market["ticker"])
            if position:
                suggestion = evaluate_exit(position, market, reference, candles,
                                           book, flow, signal_now)
                if suggestion:
                    paper_exit = ledger.close_paper(
                        market["ticker"], suggestion["exit_price"],
                        suggestion["exit_reason"], signal_now)
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            errors["paper_exit"] = _error_message(exc)
        except Exception as exc:
            errors["ledger_write"] = _error_message(exc)
    if market and spot is not None and not errors:
        try:
            market_tape.observe(market, book, spot, signal_now)
            # Independent exit engine owns exits. Do not use the old advisory
            # SELL_CANDIDATE as an execution state.
            decision = axiom_decide(
                market, reference, candles, five, book, flow, signal_now,
                tape=market_tape, open_side=None)
        except (KeyError, TypeError, ValueError, OverflowError, ArithmeticError) as exc:
            errors["forecast"] = _error_message(exc)
    # Never open a second position for the same ticker, even on an exit poll.
    if position:
        decision.update(action="WAIT", side=None, entry_price=None,
                        take_profit=None, invalidation_rule=None,
                        reason=("Paper position closed: " + paper_exit["exit_reason"]
                                if paper_exit else "Paper position already open"),
                        exit_signal=paper_exit)

    available = bool(decision["forecast_available"])
    # An incomplete genuine BRTI buffer is warmup, not a failing HTTP worker.
    warming = bool(market and spot is not None and not errors and
                   reference.get("status") == "STREAMING" and not available)
    tape_status = market_tape.snapshot(market, signal_now) if market else {}
    flow_ready = flow.get("available") is True
    rolling_ready = (len(five) >= 12 and
                     reference.get("brti_sigma_5s_3m") is not None and
                     flow_ready and flow.get("cvd_60_span", 0) >= 45)
    warmup = {
        "status": "WARMING" if warming or not available or not rolling_ready else "READY",
        "brti_fair_ready": available,
        "brti_1m_bars": len(candles),
        "brti_5m_bars": len(five),
        "brti_5s_3m_ready": reference.get("brti_sigma_5s_3m") is not None,
        "constituent_venues": flow.get("venues", []),
        "flow_60s_ready": flow_ready and flow.get("cvd_60_span", 0) >= 45,
        "flow_90s_ready": flow_ready and flow.get("cvd_90s_span", 0) >= 75,
        "flow_5m_ready": flow_ready and flow.get("cvd_5m_span", 0) >= 240,
        "kalshi_iv_24h_ready": tape_status.get("implied_history_ready") is True,
        "brti_feed_status": reference.get("status", "UNAVAILABLE"),
    }
    side = "ABOVE" if decision["action"] == "BUY_YES" else (
           "BELOW" if decision["action"] == "BUY_NO" else "WAIT")
    voter = {"name": "axiom_brti_settlement", "available": available,
             "prob_above": decision.get("prob_above"),
             "prob_below": decision.get("prob_below"),
             "side": side, "method": decision.get("model_method"),
             "independent": True, "calibrated": False}
    model = {"available": available, "prob_above": decision.get("prob_above"),
             "prob_below": decision.get("prob_below"), "side": side,
             "reason": decision.get("reason"), "engines": [voter] if available else [],
             "method": "single-axiom-brain-brti-student-t",
             "active_predictive_models": ["axiom_brti_settlement"] if available else [],
             "agreement": 1 if available else None, "calibrated": False}
    with state_lock:
        persistent_faults = any(k in state["errors"] for k in
                                ("settlement", "settlement_worker",
                                 "ledger_read", "ledger_connection"))
    if errors or persistent_faults:
        decision.update(action="WAIT", setup_type="NONE", side=None,
                        entry_price=None, take_profit=None, invalidation_price=None,
                        invalidation_rule=None, fair_prob=None,
                        kill_switch_triggered=True, reason="Live input or ledger unavailable")
        model["side"] = "WAIT"
        if model["engines"]:
            model["engines"][0]["side"] = "WAIT"
    chosen = decision["action"] in ("BUY_YES", "BUY_NO")
    op = {"side": decision["side"] if chosen else "WAIT",
          "entry_price": decision.get("entry_price"),
          "edge": (round(decision["fair_prob"]-decision["entry_price"], 5)
                   if chosen else None), "reason": decision["reason"]}
    depth = unavailable_opportunity(decision["reason"])
    if chosen:
        depth.update(status="CANDIDATE", side=decision["side"],
                     selected={"side": decision["side"],
                               "entry_price": decision["entry_price"],
                               "setup_type": decision["setup_type"]})
    inactive = {"status": "DISABLED", "available": False, "action": "WAIT",
                "order_placed": False, "read_only": True}
    watch = None
    if market and available and not errors and not persistent_faults:
        try:
            with ledger.atomic_cycle():
                ledger.observed(market, model, spot, now)
                ledger.engine_snapshots(market, model, now)
                ledger.first_call(market, model, spot, now,
                                  hold_seconds=10, poll_gap=max(40, 3*POLL_SECONDS))
                if AUTO_PAPER and chosen and position is None:
                    # Snapshot-sized one-contract paper ask, never a real order.
                    paper_market = dict(market)
                    paper_market["yes_ask" if decision["side"] == "YES" else "no_ask"] = (
                        decision["entry_price"])
                    try:
                        ledger.trade(paper_market, decision["side"], now,
                                     decision["fair_prob"], "AUTO_PAPER",
                                     take_profit=decision.get("take_profit"),
                                     invalidation_rule=decision.get("invalidation_rule"))
                    except ValueError:
                        pass
                watch = ledger.watch_info(market["ticker"])
        except Exception as exc:
            errors["ledger_write"] = _error_message(exc)
            decision.update(action="WAIT", setup_type="NONE", side=None,
                            entry_price=None, take_profit=None, invalidation_price=None,
                            invalidation_rule=None, fair_prob=None,
                            kill_switch_triggered=True, reason="Ledger write failed")
            chosen = False
            op = {"side": "WAIT", "edge": None, "entry_price": None,
                  "reason": "Ledger write failed"}
            depth = unavailable_opportunity("Ledger write failed")
    if errors:
        ledger.reset_watches()
    with state_lock:
        for component in ("settlement", "settlement_worker", "ledger_read", "ledger_connection"):
            if component in state["errors"]:
                errors[component] = state["errors"][component]
        state.update({"last_attempt": now, "market": market, "spot": spot,
                      "candles": candles[-75:], "model": model,
                      "engines": model["engines"],
                      "price_source": "CF_BENCHMARKS_BRTI",
                      "forecast_warming": warming,
                      "candle_quality": reference.get("candle_quality"),
                      "warmup": warmup, "paper_exit": paper_exit,
                      "orderbook": book, "opportunity": op,
                      "depth_opportunity": depth, "trade_decision": decision,
                      "execution_intelligence": {
                          "action": decision["action"], "side": decision.get("side"),
                          "entry_price": decision.get("entry_price"),
                          "take_profit": decision.get("take_profit"),
                          "invalidation_price": decision.get("invalidation_price"),
                          "invalidation_rule": decision.get("invalidation_rule"),
                          "kill_switch_triggered": decision.get("kill_switch_triggered"),
                          "exit_signal": paper_exit or decision.get("exit_signal"),
                          "order_placed": False, "read_only": True,
                          "reason": decision["reason"]},
                      "btc_signals": {
                          "available": available, "side": model["side"],
                          "prob_above": model["prob_above"],
                          "price_reference": "CF_BENCHMARKS_BRTI",
                          "reference_value": spot},
                      "higher_timeframes": timeframes(five, now),
                      "market_microstructure": flow,
                      "scalp": inactive, "research_shadow": inactive,
                      "candlestick_context": inactive,
                      "candlestick_challenger": inactive,
                      "intracontract": inactive, "resale_setup": inactive,
                      "contract_repricing": inactive,
                      "binance_intelligence": inactive,
                      "binance_kalshi_delay": inactive,
                      "errors": errors, "watch": watch,
                      "paper_auto_enabled": AUTO_PAPER})
        _refresh_status_locked()
        if state["status"] in ("LIVE", "DEMO"):
            state["last_success"] = now
        return _view_locked(now)


def update_once(now=None):
    now = time.time() if now is None else now
    if not DEMO:
        return _brti_only_update_once(now)
    errors={}; market=None; spot=None; candles=[]
    try:
        market=provider.market(now)
        if market is None:
            errors['kalshi']='No active Kalshi BTC15M market available'
    except Exception as e:
        errors['kalshi']=_error_message(e)
    # Live execution returned above; this path is synthetic demo only.
    brti_now = None
    try:
        spot=provider.price()
        if spot is None or not isinstance(spot,(float,int)) or not math.isfinite(spot) or spot<=0:
            errors['coinbase_ticker']='Missing or invalid synthetic BTC spot'; spot=None
    except Exception as e:
        errors['coinbase_ticker']=_error_message(e)
    try:
        candles=provider.candles()
        if not isinstance(candles,list) or len(candles)<31:
            errors['coinbase_candles']='Fewer than 31 synthetic candles available'; candles=[]
        else:
            recent=candles[-61:]
            timestamps=[c['t'] for c in recent]
            if (any(not isinstance(t,(int,float)) or not math.isfinite(t) for t in timestamps)
                    or any(b-a != 60 for a,b in zip(timestamps,timestamps[1:]))):
                errors['coinbase_candles']='Candles are missing, duplicated or not one-minute intervals'; candles=[]
            elif timestamps[-1] > now+60:
                errors['coinbase_candles']='Candles timestamped in the future'; candles=[]
    except Exception as e:
        errors['coinbase_candles']=_error_message(e); candles=[]
    model={'available':False,'side':'WAIT','prob_above':None,'reason':'No active market or input data'}
    signals=unavailable_signals('Market/price/candles unavailable or invalid')
    trade_decision=execution_decision(None,None,None,None,None,now)
    scalp=scalp_signal(candles,spot)
    # Capture exchange trade BEFORE requesting Kalshi book: source ordering
    # is essential to detect candidate stale quotes, never inferred from
    # after-the-fact midpoint comparisons.
    binance_before_book=binance_telemetry.snapshot(time.time())
    book=unavailable_book(market.get('ticker') if market else None,
                          'No active market or validated full depth yet')
    if market is not None:
        book_reader=getattr(provider,'orderbook',None)
        if callable(book_reader):
            try:
                book=book_reader(market,now)
            except Exception as e:
                # Depth failure affects depth intelligence, not independent
                # forecast, ledger, settlement, or BTC spot scalping.
                book=unavailable_book(market['ticker'],_error_message(e))
        else:
            book=unavailable_book(market['ticker'],'Provider has no full-depth API')
    # BTC-only predictive features. Kalshi book/quotes remain in the
    # separate entry/exit/price-evaluation path BELOW the forecast.
    # No forecasting function sees Kalshi bids, asks, midpoints, walls or
    # book-derived price delay as predictive inputs.
    higher=timeframes([],now)
    if market is not None:
        reader=getattr(provider,'timeframe_candles',None)
        if callable(reader):
            try:
                higher=timeframes(reader(),time.time())
            except Exception:
                higher=timeframes([],now)
    try:
        flow=market_flow_tracker.observe(binance=binance_before_book,
                                         now=time.time())
    except (TypeError,ValueError,ArithmeticError,KeyError,IndexError):
        flow={'available':False,'reason':'Flow feature calculation unavailable',
              'directional_components':{}}
    advanced_context={'timeframes':higher,'microstructure':flow}
    depth_op=unavailable_opportunity('Independent forecast or depth not available')
    depth_exec=unavailable_execution('No verified live order-book opportunity')
    op={'side':'WAIT','edge':None,'entry_price':None,'reason':'No healthy market forecast'}
    watch=None
    # Experimental research candidate is a shadow output only. Its state never
    # enters the ensemble, opportunity evaluation, ledger, or paper decisions.
    research_shadow = unavailable_research_shadow('Market or source candles unavailable')
    if market is not None and not errors:
        try:
            research_shadow = shadow_forecast_from_candles(candles,
                {k:market[k] for k in ('ticker','target','seconds_left','close_ts')
                 if k in market}, now)
        except Exception:
            # An optional research probe cannot interrupt the production poll.
            research_shadow = unavailable_research_shadow('Research model calculation failed')
    # Nison-style market-pressure context uses ONLY fully completed 1m bars.
    # Optional feature failures never degrade the active trading safeguards.
    candle_context = unavailable_candle_context('Missing valid completed BTC candles')
    if candles and not errors:
        try:
            candle_context = read_candlestick_context(candles, now)
        except (TypeError, ValueError, ArithmeticError, KeyError, IndexError):
            candle_context = unavailable_candle_context('Candle feature computation unavailable')
    candle_challenger = unavailable_candle_challenger('No ensemble forecast yet')
    with state_lock:
        # Older unresolved settlement/ledger faults are independent of this
        # market poll. Preserve predictions, but suspend new paper decisions.
        persistent_faults = any(k in state['errors'] for k in
                                ('settlement','settlement_worker','ledger_read','ledger_connection'))
    if market:
        # Contract strike and expiration are valid prediction questions;
        # contract YES/NO QUOTES ARE NOT. Restrict model inputs at the caller.
        forecast_contract={k:market[k] for k in
                           ('ticker','target','seconds_left','close_ts')
                           if k in market}
        try:
            signals=derive_signals(forecast_contract,spot,candles,now,
                brti=brti_now,
                spot_received_at=None if not DEMO else getattr(provider,'price_received_at',None),
                spot_source_at=None if not DEMO else getattr(provider,'price_source_at',None))
        except (ArithmeticError,TypeError,ValueError,KeyError):
            signals=unavailable_signals('BTC feature calculation rejected invalid inputs')
            errors['btc_signals']='BTC feature calculation rejected invalid inputs'
        model=engine_pack(spot,forecast_contract,candles,signals=signals,
                          context=advanced_context,now=now)
        try:
            candle_challenger = derive_candlestick_challenger(candle_context,model)
        except (TypeError, ValueError, ArithmeticError, KeyError, IndexError):
            candle_challenger = unavailable_candle_challenger('Candle candidate computation unavailable')
        # Genuine 1m BRTI bars must accumulate after boot; unlike a broken
        # exchange feed, this is a healthy transport with an unavailable
        # predictor. Never make demo mode or missing data look like a forecast.
        warming=(not DEMO and not errors and brti_now is not None
                 and brti_now.get('status')=='STREAMING'
                 and spot is not None and 0 <= len(candles)<31
                 and not model.get('available'))
        if not model.get('available') and not errors and not warming:
            errors['forecast']=model.get('reason','Model unavailable')
        if not errors and not persistent_faults:
            try:
                # The book has a *receipt* time after the initial quote/spot
                # reads; do not label genuine fresh depth as future-dated.
                depth_now=max(now,float(book.get('received_at') or now))
                depth_op=analyze_opportunities(model,market,book,depth_now,signals=signals)
                depth_exec=execution_guidance(depth_op,model,market,book,depth_now)
            except Exception as e:
                # Optional, non-executable execution intelligence cannot break
                # the original ledger or turn an unknown depth into BUY.
                depth_op=unavailable_opportunity('Depth analysis failed: '+_error_message(e))
                depth_exec=unavailable_execution('Depth analysis failed')
        if not errors and not persistent_faults:
            trade_decision=execution_decision(signals,model,market,book,depth_op,
                                      max(now,float(book.get('received_at') or now)))
        if not errors and model.get('available'):
            if not persistent_faults:
                op=execution_screen(model,market)
            else:
                op['reason']='Paper entries suspended while settlement or ledger health is degraded'
            # A poll is one consistent ledger event. If any later write fails,
            # none of this poll's observation, snapshots, watch, or paper entry
            # may survive. Ledger also serializes concurrent manual writes.
            with ledger.atomic_cycle():
                ledger.observed(market,model,spot,now)
                if CANDLESTICK_SHADOW_GRADING_ENABLED:
                    ledger.engine_snapshots(market,model,now,candle_challenger)
                else:
                    ledger.engine_snapshots(market,model,now)
                ledger.first_call(market,model,spot,now,hold_seconds=10,poll_gap=max(40,3*POLL_SECONDS))
                if AUTO_PAPER and op['side'] in ('YES','NO'):
                    try:
                        ledger.trade(market,op['side'],now,
                                     model['prob_above'] if op['side']=='YES' else model['prob_below'], 'AUTO_RESEARCH')
                    except ValueError:
                        pass
                watch=ledger.watch_info(market['ticker'])
    # Independent, read-only Binance-first detector using actual spot trades.
    # Public provider outages fail WAIT.
    if market and not errors and not persistent_faults and model.get('available'):
        try:
            binance_lag=binance_lag_tracker.observe(market,book,binance_before_book,
                model,max(now,float(book.get('received_at') or now)))
        except (ValueError,TypeError,ArithmeticError,KeyError):
            binance_lag_tracker.reset()
            binance_lag=wait_binance_lag('Malformed Binance/Kalshi market pair',binance_before_book)
    else:
        binance_lag_tracker.reset()
        binance_lag=wait_binance_lag('Missing healthy synchronized market inputs',binance_before_book)
    # Quote repricing belongs ONLY to the execution/valuation lane, after
    # independent BTC forecast and ledger writes. Never feed its result back
    # into engine_pack, BTC probability, or settlement model weights.
    contract_repricing=unavailable_contract_repricing('Awaiting healthy contract and quote')
    if market and not errors and not persistent_faults and model.get('available'):
        try:
            contract_repricing=contract_repricing_tracker.observe(
                market,book,model,signals,
                max(now,float(book.get('received_at') or now)),btc_flow=flow)
        except (KeyError,TypeError,ValueError,ArithmeticError,IndexError):
            contract_repricing=unavailable_contract_repricing('Quote repricing learner failed')
    else:
        contract_repricing_tracker.pending=None
    # Read-only intracontract intelligence, after transactional ledger writes.
    if market and not errors and not persistent_faults and model.get('available'):
        try:
            observed_at=max(now,float(book.get('received_at') or now))
            intracontract=movement_tracker.observe(market,book,signals,observed_at)
            resale_setup=resale_screen(market,book,signals,intracontract,observed_at)
        except (ValueError,TypeError,ArithmeticError,KeyError):
            movement_tracker.reset()
            intracontract=unavailable_timeline('Invalid quote-history observation')
            resale_setup=wait_resale('Invalid quote-history observation')
    else:
        movement_tracker.reset()
        intracontract=unavailable_timeline('No healthy market/forecast cycle')
        resale_setup=wait_resale('No healthy market/forecast cycle')
    if errors:
        # A missing poll must break the ten-second first-call confidence hold;
        # otherwise a short feed outage can be counted as sustained evidence.
        ledger.reset_watches()
    with state_lock:
        # Keep unresolved grading failures visible, even across good feed polls.
        for component in ('settlement','settlement_worker','ledger_read','ledger_connection'):
            if component in state['errors']:
                errors[component] = state['errors'][component]
        state.update({'last_attempt':now,
            'market':market,'spot':spot,'candles':candles[-75:], 'model':model,'scalp':scalp,
            'forecast_warming':(not DEMO and not errors and market is not None
                 and brti_now is not None and brti_now.get('status')=='STREAMING'
                 and spot is not None and 0 <= len(candles)<31
                 and not model.get('available')),
            'price_source':'SYNTHETIC_DEMO' if DEMO else 'CF_BENCHMARKS_BRTI',
            'opportunity':op,'engines':model.get('engines',[]),'errors':errors,'watch':watch,
             'research_shadow':research_shadow,
             'candlestick_context':candle_context,
             'candlestick_challenger':candle_challenger,
             'orderbook':book,'depth_opportunity':depth_op,
             'execution_intelligence':depth_exec,
             'btc_signals':signals,'trade_decision':trade_decision,
             'intracontract':intracontract,'resale_setup':resale_setup,
              'contract_repricing':contract_repricing,
             'binance_intelligence':binance_before_book,'binance_kalshi_delay':binance_lag,
             'higher_timeframes':higher,'market_microstructure':flow,
            'candle_quality':((brti_now or {}).get('candle_quality') if not DEMO
                              else ({'status':'UNAVAILABLE',
                                     'reason':errors['coinbase_candles']}
                                    if 'coinbase_candles' in errors else
                                    getattr(provider,'candle_quality',None)))})
        _refresh_status_locked()
        if state['status'] in ('LIVE','DEMO'):
            state['last_success'] = now
        return _view_locked(now)


def grade_once(settlement_provider=None):
    source = settlement_provider if settlement_provider is not None else provider
    global last_grading_ticker
    now=time.time()
    attempted=[]
    try:
        tickers=ledger.unresolved(50, after_ticker=last_grading_ticker)
        last_grading_ticker=tickers[-1] if tickers else None
    except Exception as e:
        # Even enumerating unresolved contracts can fail (for example, database
        # downtime). It is a grading failure, never an empty/healthy queue.
        with state_lock:
            settlement_failures['__ledger__'] = 'Cannot list unresolved contracts: ' + _error_message(e)
            _record_settlement_locked(now, attempted, pending=None)
        return
    with state_lock:
        settlement_failures.pop('__ledger__', None)
        if not tickers:
            settlement_failures.clear()
    for ticker in tickers:
        attempted.append(ticker)
        try:
            # The provider returns None while settlement is legitimately pending.
            # We never substitute the Coinbase spot result for an official label.
            result=source.settlement(ticker)
            if result is not None:
                if result not in ('yes','no'):
                    raise ValueError('Provider returned an invalid official result')
                ledger.grade(ticker,result,now)
        except Exception as e:
            with state_lock:
                settlement_failures[ticker] = _error_message(e)
        else:
            with state_lock:
                settlement_failures.pop(ticker,None)
    # One last database read distinguishes genuinely pending results from
    # contracts which have all been graded successfully in this batch.
    try:
        pending=bool(ledger.unresolved(1))
    except Exception as e:
        pending=None
        with state_lock:
            settlement_failures['__ledger__']='Cannot confirm remaining settlement queue: ' + _error_message(e)
    with state_lock:
        _record_settlement_locked(now, attempted, pending)


def _record_settlement_locked(now, attempted, pending):
    """Publish grading errors atomically without destroying feed/worker errors."""
    count=len(settlement_failures)
    if count:
        ticker,reason=next(iter(settlement_failures.items()))
        state['errors']['settlement'] = f'{count} settlement check(s) failed; {ticker}: {reason}'
    else:
        state['errors'].pop('settlement',None)
    previous_success=state['settlement']['last_success']
    if not count:
        previous_success=now
    state['settlement']={
        'status':'ERROR' if count else ('PENDING' if pending else ('CHECKED' if attempted else 'IDLE')),
        'last_attempt':now,'last_success':previous_success,
        'checked':len(attempted),'failed':count,
    }
    _refresh_status_locked()


def worker():
    """Market polling must not wait for slow official-settlement lookups."""
    while not shutdown.is_set():
        try:
            update_once()
        except Exception as e:
            with state_lock:
                state['status']='ERROR'; state['errors']['worker']=f'{type(e).__name__}: {str(e)[:200]}'
        shutdown.wait(POLL_SECONDS)


def grading_worker():
    """Grade on a separate worker and (in live mode) separate HTTP session.

    A settlement backlog may contain many slow API lookups; it cannot block
    the price/forecast loop. The ledger's RLock serializes database writes.
    """
    settlement_provider = LiveProvider() if isinstance(provider, LiveProvider) else provider
    try:
        while not shutdown.wait(4*POLL_SECONDS):
            try:
                grade_once(settlement_provider)
            except Exception as e:
                with state_lock:
                    state['errors']['settlement_worker']=_error_message(e)
                    _refresh_status_locked()
            else:
                with state_lock:
                    state['errors'].pop('settlement_worker',None)
                    _refresh_status_locked()
    finally:
        if settlement_provider is not provider:
            settlement_provider.session.close()


@asynccontextmanager
async def lifespan(_app):
    shutdown.clear()
    market_thread=threading.Thread(target=worker, name='research-data-worker',daemon=True)
    grading_thread=threading.Thread(target=grading_worker, name='research-settlement-worker',daemon=True)
    market_thread.start()
    grading_thread.start()
    brti_thread = None
    flow_threads = []
    if BRTI_LIVE_ENABLED:
        brti_thread = threading.Thread(target=brti_reference_worker,
            args=(brti_tracker,shutdown),name='read-only-live-brti-worker',daemon=True)
        brti_thread.start()
        flow_threads = start_flow_workers(flow_tracker, shutdown)
    yield
    shutdown.set()
    market_thread.join(timeout=3)
    grading_thread.join(timeout=3)
    if brti_thread is not None:
        brti_thread.join(timeout=3)
    for thread in flow_threads:
        thread.join(timeout=3)

app=FastAPI(title='AXIOM Multi-Engine BTC Research Bot',version='2.0.0',lifespan=lifespan, docs_url=None,redoc_url=None)

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/health')
def health():
    try:
        ledger.healthcheck()
    except Exception as e:
        ledger_error=_error_message(e)
    else:
        ledger_error=None
    with state_lock:
        if ledger_error:
            state['errors']['ledger_connection']=ledger_error
        else:
            state['errors'].pop('ledger_connection',None)
        _refresh_status_locked()
        snapshot=_view_locked(time.time())
    return JSONResponse({'ok':snapshot['ok'],'status':snapshot['status'],
        'mode':snapshot['mode'],'last_attempt':snapshot['last_attempt'],
        'last_success':snapshot['last_success'],
        'heartbeat_age_seconds':snapshot['heartbeat_age_seconds'],
        'errors':snapshot['errors'],'settlement':snapshot['settlement'],
        'live_briti':snapshot['live_briti'],
        'binance_intelligence':snapshot['binance_intelligence'],
        'binance_kalshi_delay':snapshot.get('binance_kalshi_delay')},
        status_code=200 if snapshot['ok'] else 503,headers={'Cache-Control':'no-store'})

@app.get('/api/state')
def get_state():
    now=time.time()
    try:
        ledger_rows=ledger.data()
        scores=ledger.engine_scores()
    except Exception as e:
        # Return an explicit, machine-readable outage instead of HTTP 500 with
        # an apparently healthy /health endpoint or fabricated empty history.
        with state_lock:
            state['errors']['ledger_read']=_error_message(e)
            _refresh_status_locked()
            d=_view_locked(now)
        d['execution_evidence']=examine_liquidity(d.get('orderbook'), d.get('market'),now)
        d['engine_scores']={'status':'UNAVAILABLE','samples':None,'scores':[]}
        d['ledger_available']=False
        d['manual_paper_available']=False
        d['server_time']=now
        return JSONResponse(d,status_code=503,headers={'Cache-Control':'no-store'})
    with state_lock:
        state['errors'].pop('ledger_read',None)
        _refresh_status_locked()
        d=_view_locked(now)
    d.update(ledger_rows)
    # Optional review of ONE paper contract, never a real Kalshi account.
    # The existing paper ledger represents one contract per row; user holdings
    # and real order/fill history are NOT available to AXIOM.
    d['paper_position_execution']=unavailable_execution('No open matching simulated position')
    d['resale_position_review']=wait_resale('No matching simulated position')
    active=d.get('market')
    if DEMO and active and d.get('ok'):
        for trade in d.get('trades',[]):
            if trade.get('ticker')==active['ticker'] and trade.get('status')=='OPEN':
                try:
                    d['resale_position_review']=resale_position_review(trade,active,
                        d.get('orderbook'),d.get('btc_signals'),d.get('intracontract'),now)
                    d['paper_position_execution']=execution_guidance(
                        d.get('depth_opportunity'),d.get('model'),active,d.get('orderbook'),now,
                        position={'side':trade['side'],'contracts':1.0})
                except Exception:
                    d['resale_position_review']=wait_resale('Paper-position resale check unavailable')
                    d['paper_position_execution']=unavailable_execution('Paper position depth review unavailable')
                break
    d['execution_evidence']=examine_liquidity(d.get('orderbook'), d.get('market'),now)
    d['engine_scores']=scores
    d['ledger_available']=True
    d['server_time']=now
    # A token alone is not permission to record a position against stale or
    # broken market data. The UI and paper endpoint share the same readiness rule.
    d['manual_paper_available']=bool(ADMIN_TOKEN) and d['ok'] and bool(d.get('market')) and bool((d.get('model') or {}).get('available'))
    d['disclaimer']=('Experimental models and gross simulated trading only. SYNTHETIC DEMO BTC spot is NOT the BRTI settlement index. No real orders.'
                    if DEMO else
                    'Phase 3 BRTI-only fair value and USD constituent confirmations; one-contract early-exit paper P&L from live Kalshi depth or official settlement. No real orders.')
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

class PaperRequest(BaseModel):
    side: str

@app.post('/api/paper')
def paper(req:PaperRequest, authorization:str|None=Header(default=None)):
    if not ADMIN_TOKEN: raise HTTPException(403,'Manual paper trading disabled; configure BOT_ADMIN_TOKEN')
    if authorization != f'Bearer {ADMIN_TOKEN}': raise HTTPException(401,'Incorrect admin token')
    with state_lock:
        snapshot=_view_locked(time.time())
        m=snapshot.get('market'); ts=snapshot.get('last_attempt')
    if (not snapshot['ok'] or not (snapshot.get('model') or {}).get('available')
            or not m or not ts or time.time()-ts > max(50,3*POLL_SECONDS)):
        raise HTTPException(409,'Market snapshot unhealthy, unavailable or stale')
    ask=m.get('yes_ask' if req.side.upper()=='YES' else 'no_ask')
    bid=m.get('yes_bid' if req.side.upper()=='YES' else 'no_bid')
    if req.side.upper() in ('YES','NO') and (ask is None or bid is None or ask < bid):
        raise HTTPException(409,'Invalid or crossed contract quote')
    if m['seconds_left'] < 20 or m['close_ts'] < time.time()+20:
        raise HTTPException(409,'Contract too close to close')
    side=req.side.upper()
    probability=(snapshot.get('model') or {}).get(
        'prob_above' if side=='YES' else 'prob_below')
    target=(max(.60,min(.85,probability))
            if isinstance(probability,(float,int)) and math.isfinite(probability)
            else None)
    live_signal=snapshot.get('trade_decision') or {}
    rule=(live_signal.get('invalidation_rule')
          if live_signal.get('side')==side else None)
    try:
        entry=ledger.trade(m,side,time.time(),source='MANUAL_PAPER',
                           take_profit=target,invalidation_rule=rule)
    except ValueError as e:
        raise HTTPException(409,str(e))
    return entry

@app.get('/api/export/{kind}')
def export(kind:str,authorization:str|None=Header(default=None)):
    if not ADMIN_TOKEN or authorization != f'Bearer {ADMIN_TOKEN}':
        raise HTTPException(401,'Export requires BOT_ADMIN_TOKEN')
    try: headers,rows=ledger.export(kind)
    except ValueError: raise HTTPException(404,'Unknown dataset')
    buf=io.StringIO(); w=csv.writer(buf); w.writerow(headers); w.writerows(rows)
    return Response(content=buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{kind}.csv"'})
