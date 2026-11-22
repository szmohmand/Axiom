"""SQLite event journal. One worker per database (set WEB_CONCURRENCY=1)."""
import sqlite3
import json
from decimal import Decimal, ROUND_CEILING
from contextlib import contextmanager
import threading
import time
import os
import math
from pathlib import Path
from .engine import paper_result

class Ledger:
    def __init__(self, location):
        Path(location).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(location, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA busy_timeout=10000')
        with self.lock:
            self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS watches(
              ticker TEXT PRIMARY KEY, side TEXT, since REAL, last_seen REAL);
            CREATE TABLE IF NOT EXISTS first_calls(
              ticker TEXT PRIMARY KEY, side TEXT NOT NULL, probability REAL NOT NULL,
              created REAL NOT NULL, seconds_left INTEGER NOT NULL, spot REAL,
              target REAL, result TEXT, graded REAL);
            CREATE TABLE IF NOT EXISTS paper_trades(
              id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL UNIQUE,
              side TEXT NOT NULL, entry REAL NOT NULL, created REAL NOT NULL,
              seconds_left INTEGER NOT NULL, model_prob REAL,
              source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
              result TEXT, pnl REAL, graded REAL);
            CREATE TABLE IF NOT EXISTS observations(
              id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, ts REAL NOT NULL,
              spot REAL, target REAL, market_prob REAL, model_prob REAL,
              signal TEXT);
            CREATE INDEX IF NOT EXISTS ix_obs_ts ON observations(ts);
            CREATE TABLE IF NOT EXISTS engine_snapshots(
              ticker TEXT NOT NULL, engine TEXT NOT NULL, checkpoint TEXT NOT NULL,
              ts REAL NOT NULL, seconds_left INTEGER NOT NULL,
              prob_above REAL NOT NULL, market_prob REAL,
              result TEXT, graded REAL,
              PRIMARY KEY(ticker,engine,checkpoint)
            );
            CREATE INDEX IF NOT EXISTS ix_engine_grades ON engine_snapshots(engine,result);
            ''')
            # In-place, non-destructive migration of legacy paper rows.
            columns = {row[1] for row in self.conn.execute('PRAGMA table_info(paper_trades)')}
            for name, kind in (
                ('take_profit', 'REAL'), ('invalidation_rule', 'TEXT'),
                ('entry_fee', 'REAL'), ('exit_fee', 'REAL'),
                ('exit_price', 'REAL'), ('exit_reason', 'TEXT'),
                ('exited_at', 'REAL'), ('net_pnl', 'REAL'),
                ('fee_model', 'TEXT'),
            ):
                if name not in columns:
                    self.conn.execute(f'ALTER TABLE paper_trades ADD COLUMN {name} {kind}')
            self._commit()
    @contextmanager
    def atomic_cycle(self):
        """Commit a full forecast poll or roll back all of its writes.

        Existing Ledger methods can still be used independently. Holding the
        existing RLock across the transaction also protects against overlapping
        HTTP/worker writes to the same SQLite connection.
        """
        with self.lock:
            if getattr(self, '_atomic_poll', False):
                raise RuntimeError('Nested forecast poll transaction')
            self._atomic_poll = True
            try:
                with self.conn:
                    yield
            finally:
                self._atomic_poll = False

    def _commit(self):
        if not getattr(self, '_atomic_poll', False):
            self.conn.commit()

    def first_call(self, market, model, spot, now, hold_seconds=10, poll_gap=40):
        """Lock first directional 85%-confidence call after continuous observations."""
        ticker=market['ticker']; p=model.get('prob_above'); side=None
        if model.get('available') and model.get('side') != 'WAIT' and p is not None and market['seconds_left']>0:
            if p >= .85: side='ABOVE'
            elif p <= .15: side='BELOW'
        with self.lock:
            if self.conn.execute('SELECT 1 FROM first_calls WHERE ticker=?', (ticker,)).fetchone():
                return None
            prev=self.conn.execute('SELECT * FROM watches WHERE ticker=?', (ticker,)).fetchone()
            if side is None:
                self.conn.execute('DELETE FROM watches WHERE ticker=?', (ticker,))
                self._commit(); return None
            if not prev or prev['side'] != side or now-prev['last_seen'] > poll_gap:
                self.conn.execute('INSERT OR REPLACE INTO watches VALUES (?,?,?,?)', (ticker,side,now,now))
                self._commit(); return None
            self.conn.execute('UPDATE watches SET last_seen=? WHERE ticker=?',(now,ticker))
            if now-prev['since'] >= hold_seconds:
                self.conn.execute('''INSERT INTO first_calls(ticker,side,probability,created,seconds_left,spot,target)
                  VALUES(?,?,?,?,?,?,?)''', (ticker,side, p if side=='ABOVE' else 1-p,now,
                      market['seconds_left'],spot,market.get('target')))
                self.conn.execute('DELETE FROM watches WHERE ticker=?',(ticker,))
                self._commit()
                return {'ticker':ticker,'side':side,'probability':p if side=='ABOVE' else 1-p}
            self._commit(); return None
    def healthcheck(self):
        """Detect unavailable/corrupted ledger tables even without new writes."""
        with self.lock:
            for name in ('first_calls','paper_trades','observations','engine_snapshots'):
                self.conn.execute(f'SELECT 1 FROM {name} LIMIT 1').fetchone()

    def reset_watches(self):
        """Break confidence continuity after missing or failed market inputs.

        A first-call hold is meaningful only across successive healthy polls.
        Completed first calls are immutable and are never affected.
        """
        with self.lock:
            self.conn.execute('DELETE FROM watches')
            self._commit()

    def watch_info(self, ticker):
        with self.lock:
            r=self.conn.execute('SELECT * FROM watches WHERE ticker=?',(ticker,)).fetchone()
            if r: return {'side':r['side'],'held_seconds':max(0,round(time.time()-r['since']))}
            return None
    def observed(self, market, model, spot, now):
        with self.lock:
            self.conn.execute('''INSERT INTO observations(ticker,ts,spot,target,market_prob,model_prob,signal)
                VALUES(?,?,?,?,?,?,?)''',(market['ticker'], now, spot, market.get('target'),
                market.get('market_mid'),model.get('prob_above'),model.get('side')))
            self.conn.execute('DELETE FROM observations WHERE id NOT IN (SELECT id FROM observations ORDER BY id DESC LIMIT 7000)')
            self._commit()
    @staticmethod
    def paper_fee(price):
        """Per one simulated contract: conservative ceil-to-cent taker estimate."""
        if isinstance(price, bool):
            raise ValueError('Invalid paper fill')
        p = Decimal(str(price))
        if not p.is_finite() or not Decimal('0') <= p <= Decimal('1'):
            raise ValueError('Invalid paper fill')
        return float((Decimal('0.07') * p * (1-p) * 100).to_integral_value(
            rounding=ROUND_CEILING) / 100)

    def trade(self, market, side, now, model_probability=None, source='MANUAL',
              take_profit=None, invalidation_rule=None):
        side=side.upper()
        if side not in ('YES','NO'): raise ValueError('Side must be YES or NO')
        if market['seconds_left'] < 20: raise ValueError('Less than 20 seconds remain')
        entry=market.get('yes_ask' if side=='YES' else 'no_ask')
        if entry is None or not .01<=entry<=.99: raise ValueError('No valid current ask available')
        if take_profit is not None and (not isinstance(take_profit,(int,float)) or
                 isinstance(take_profit,bool) or not math.isfinite(take_profit) or
                 not 0 < take_profit <= 1):
            raise ValueError('Invalid take-profit')
        if invalidation_rule is not None and (not isinstance(invalidation_rule,dict)
                or invalidation_rule.get('type') not in (
                'BRTI_CLOSE_BACK_INSIDE_RANGE','BRTI_STRIKE_BAND_OR_CVD_FLIP',
                'BRTI_CONFIRMED_VENUE_EXTENSION')):
            raise ValueError('Invalid BRTI invalidation rule')
        fee=self.paper_fee(entry)
        rule=json.dumps(invalidation_rule,sort_keys=True) if invalidation_rule else None
        with self.lock:
            try:
                c=self.conn.execute('''INSERT INTO paper_trades(
                  ticker,side,entry,created,seconds_left,model_prob,source,
                  take_profit,invalidation_rule,entry_fee,fee_model)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (
                    market['ticker'],side,entry,now,market['seconds_left'],
                    model_probability,source,take_profit,rule,fee,
                    'estimated_taker_7pct_p_times_1_minus_p_ceil_cent'))
                self._commit()
                return {'id':c.lastrowid,'ticker':market['ticker'],'side':side,
                        'entry':entry,'entry_fee':fee,'take_profit':take_profit,
                        'status':'OPEN'}
            except sqlite3.IntegrityError:
                raise ValueError('A paper position already exists for this market')

    def open_paper(self, ticker):
        """Return an immutable SQL observation (independent dictionary copy)."""
        with self.lock:
            row = self.conn.execute(
                "SELECT ticker,side,entry,created,take_profit,invalidation_rule,entry_fee "
                "FROM paper_trades WHERE ticker=? AND status='OPEN' AND result IS NULL",
                (ticker,)).fetchone()
        if not row:
            return None
        item=dict(row)
        item['invalidation_rule'] = (json.loads(item['invalidation_rule'])
                                     if item['invalidation_rule'] else None)
        return item

    def close_paper(self, ticker, exit_price, exit_reason, now):
        """Exactly-once one-contract paper resale; no accounts or real orders."""
        if exit_reason not in ('TAKE_PROFIT','BRTI_INVALIDATION',
                               'CVD_SIGN_FLIP','TIME_STOP'):
            raise ValueError('Unknown paper exit reason')
        if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now):
            raise ValueError('Invalid paper exit timestamp')
        if isinstance(exit_price,bool) or not isinstance(exit_price,(int,float)) or (
                not math.isfinite(exit_price) or not 0 < exit_price < 1):
            raise ValueError('Invalid simulated executable bid')
        with self.lock:
            row=self.conn.execute("SELECT entry,entry_fee,created FROM paper_trades "
                      "WHERE ticker=? AND status='OPEN' AND result IS NULL",(ticker,)).fetchone()
            if row is None:
                return None
            if now < row['created']:
                raise ValueError('Paper exit predates entry')
            fee_entry = (row['entry_fee'] if row['entry_fee'] is not None
                         else self.paper_fee(row['entry']))
            fee_exit=self.paper_fee(exit_price)
            gross=round(exit_price-row['entry'],6)
            net=round(gross-fee_entry-fee_exit,6)
            changed=self.conn.execute("""UPDATE paper_trades SET
                        status='EXITED',exit_price=?,exit_reason=?,exited_at=?,
                        entry_fee=?,exit_fee=?,pnl=?,net_pnl=?,
                        fee_model='estimated_taker_7pct_p_times_1_minus_p_ceil_cent'
                        WHERE ticker=? AND status='OPEN' AND result IS NULL""",
                        (exit_price,exit_reason,now,fee_entry,fee_exit,gross,net,ticker))
            if changed.rowcount != 1:
                return None
            self._commit()
            return {'ticker':ticker,'status':'EXITED','exit_price':exit_price,
                    'exit_reason':exit_reason,'exited_at':now,
                    'gross_pnl':gross,'net_pnl':net,
                    'entry_fee':fee_entry,'exit_fee':fee_exit}

    def unresolved(self, max_rows=30, after_ticker=None):
        """Distinct unresolved tickers, deterministically rotated across batches.

        Repeated LIMIT on an unordered UNION can permanently starve newer
        contracts if older results remain pending. The caller advances a
        ticker cursor after each grading batch; we wrap to the beginning.
        """
        if max_rows < 1:
            return []
        base="""SELECT ticker FROM (
          SELECT ticker FROM first_calls WHERE result IS NULL
          UNION SELECT ticker FROM paper_trades WHERE result IS NULL
          UNION SELECT ticker FROM engine_snapshots WHERE result IS NULL
        ) AS unresolved """
        with self.lock:
            rows=self.conn.execute(base + 'WHERE ticker > ? ORDER BY ticker LIMIT ?',
                                   (after_ticker or '', max_rows)).fetchall()
            tickers=[r['ticker'] for r in rows]
            if after_ticker and len(tickers)<max_rows:
                remainder=self.conn.execute(base + 'WHERE ticker <= ? ORDER BY ticker LIMIT ?',
                                            (after_ticker, max_rows-len(tickers))).fetchall()
                tickers.extend(r['ticker'] for r in remainder)
            return tickers
    def engine_snapshots(self, market, model, now, candlestick_challenger=None):
        """Fixed-time forecasts for head-to-head scoring (same contract/clock).

        Legacy 'market_prob' SQL field holds the participant order-book YES
        quote midpoint, not a Kalshi prediction or objective likelihood.

        Snapshots are written only inside a +/-30s target band. A fixed
        checkpoint is recorded at most once per engine/market; no rewrites.
        Missing engines get no fabricated forecasts.
        """
        sec=market.get('seconds_left',0)
        checkpoints={'14m':840,'10m':600,'5m':300,'1m':60}
        eligible=[label for label,target in checkpoints.items() if abs(sec-target)<=30]
        if not eligible:return 0
        label=min(eligible,key=lambda x:abs(sec-checkpoints[x]))
        rows=[]
        for engine in model.get('engines',[]):
            p=engine.get('prob_above')
            if engine.get('available') and p is not None and 0 < p < 1:
                rows.append((market['ticker'],engine['name'],label,now,sec,p,market.get('market_mid')))
        if model.get('available') and model.get('prob_above') is not None:
            rows.append((market['ticker'],'ensemble',label,now,sec,model['prob_above'],market.get('market_mid')))
        # Optional, opt-in prospective shadow score only. Never alter the
        # preexisting engines, active median, historical grades, or orders.
        if (isinstance(candlestick_challenger, dict) and
                candlestick_challenger.get('available') is True and
                candlestick_challenger.get('name') == 'nison_candlestick_challenger' and
                candlestick_challenger.get('votes_in_ensemble') is False and
                candlestick_challenger.get('can_trigger_paper_or_orders') is False):
            candidate_p = candlestick_challenger.get('prob_above')
            if (not isinstance(candidate_p, bool) and
                    isinstance(candidate_p, (int, float)) and
                    math.isfinite(candidate_p) and 0 < candidate_p < 1):
                rows.append((market['ticker'],'nison_candlestick_challenger',
                             label,now,sec,candidate_p,market.get('market_mid')))
        with self.lock:
            for vals in rows:
                self.conn.execute('INSERT OR IGNORE INTO engine_snapshots (ticker,engine,checkpoint,ts,seconds_left,prob_above,market_prob) VALUES(?,?,?,?,?,?,?)',vals)
            self._commit()
        return len(rows)

    def engine_scores(self):
        """Official-settlement Brier scores versus participant quote midpoints.

        A quote midpoint is a descriptive scoring benchmark, not a Kalshi
        forecasting model or evidence of executable profit.
        """
        import math
        with self.lock:
            rows=[dict(x) for x in self.conn.execute("SELECT engine,checkpoint,prob_above,market_prob,result FROM engine_snapshots WHERE result IN ('yes','no')")]
            total=self.conn.execute('SELECT count(*) FROM engine_snapshots').fetchone()[0]
        by={}
        for r in rows:
            key=(r['engine'],r['checkpoint'])
            t=by.setdefault(key,{'engine':key[0],'checkpoint':key[1], 'n':0,
                'correct':0, 'sum_brier':0., 'sum_market_brier':0.,
                'n_market':0, 'sum_logloss':0.})
            y=1 if r['result']=='yes' else 0
            p=r['prob_above']
            t['n']+=1
            t['correct']+=int((p>=.5)==(y==1))
            t['sum_brier']+=(p-y)**2
            t['sum_logloss']+=-(y*math.log(max(p,1e-9))+(1-y)*math.log(max(1-p,1e-9)))
            market=r['market_prob']
            if market is not None and 0 < market < 1:
                t['n_market']+=1
                t['sum_market_brier']+=(market-y)**2
        scores=[]
        for t in by.values():
            n=t['n']; nm=t['n_market']
            b=t['sum_brier']/n
            base=t['sum_market_brier']/nm if nm else None
            scores.append({'engine':t['engine'],'checkpoint':t['checkpoint'],'n':n,
                'accuracy':round(t['correct']/n,4), 'brier':round(b,5),
                'market_brier':round(base,5) if base is not None else None,
                'brier_improvement':round(base-b,5) if nm==n else None,
                'logloss':round(t['sum_logloss']/n,5),
                'sufficient_sample':n>=30,'validated_alpha':False,
                'benchmark_kind':'participant_order_book_yes_midpoint',
                'market_price_is_kalshi_prediction':False})
        return {'samples':total,'scores':sorted(scores,key=lambda r:(r['checkpoint'],r['engine'])),
                'note':'Order-book midpoints reflect participant quotes, NOT Kalshi predictions. Brier differences are descriptive and NOT validated alpha. Use held-out chronological testing.'}

    def grade(self, ticker, result, now):
        """Grade official outcome without rewriting an already realized resale."""
        if result not in ('yes','no'):
            raise ValueError('Requires Kalshi official yes/no')
        with self.lock, self.conn:
            self.conn.execute('UPDATE first_calls SET result=?, graded=? WHERE ticker=? AND result IS NULL', (result, now, ticker))
            self.conn.execute('UPDATE engine_snapshots SET result=?, graded=? WHERE ticker=? AND result IS NULL', (result, now, ticker))
            row=self.conn.execute("SELECT side,entry,entry_fee,status "
                 "FROM paper_trades WHERE ticker=? AND result IS NULL",
                 (ticker,)).fetchone()
            if row is not None:
                if row['status']=='OPEN':
                    gross=paper_result(row['side'],row['entry'],result)
                    fee=row['entry_fee'] if row['entry_fee'] is not None else self.paper_fee(row['entry'])
                    won=(row['side']=='YES' and result=='yes') or (
                         row['side']=='NO' and result=='no')
                    exit_price=1. if won else 0.
                    self.conn.execute("""UPDATE paper_trades SET
                          result=?,pnl=?,net_pnl=?,status='SETTLED',graded=?,
                          exited_at=?,exit_price=?,exit_reason='OFFICIAL_SETTLEMENT',
                          entry_fee=?,exit_fee=0,
                          fee_model='estimated_taker_7pct_p_times_1_minus_p_ceil_cent'
                          WHERE ticker=? AND status='OPEN' AND result IS NULL""",
                          (result,gross,round(gross-fee,6),now,now,exit_price,fee,ticker))
                elif row['status']=='EXITED':
                    # The settlement label is still valuable for analysis, but
                    # a resale's exit price, realized P&L and time are final.
                    self.conn.execute("UPDATE paper_trades SET result=?,graded=? "
                        "WHERE ticker=? AND status='EXITED' AND result IS NULL",
                        (result,now,ticker))

    def data(self, limit=60):
        with self.lock:
            calls=[dict(x) for x in self.conn.execute('SELECT * FROM first_calls ORDER BY created DESC LIMIT ?', (limit,))]
            trades=[dict(x) for x in self.conn.execute('SELECT * FROM paper_trades ORDER BY created DESC LIMIT ?', (limit,))]
            rows=self.conn.execute('SELECT side,result,probability FROM first_calls WHERE result IS NOT NULL').fetchall()
            settled=[dict(x) for x in self.conn.execute(
                "SELECT pnl FROM paper_trades WHERE status='SETTLED'")]
            closed=[dict(x) for x in self.conn.execute(
                "SELECT status,pnl,net_pnl FROM paper_trades "
                "WHERE status IN ('EXITED','SETTLED')")]
            total=len(rows); correct=sum((x['side']=='ABOVE') == (x['result']=='yes') for x in rows)
            pcount=len(settled); wins=sum(x['pnl']>0 for x in settled)
            gross=sum(x['pnl'] for x in settled)
            realized=sum(x['pnl'] for x in closed)
            realized_net=sum(x['net_pnl'] for x in closed if x['net_pnl'] is not None)
            return {'calls':calls,'trades':trades,
                'stats':{'graded_calls':total,'correct_calls':correct,
                         'first_call_accuracy':round(correct/total,4) if total else None,
                         'settled_paper_trades':pcount,'winning_paper_trades':wins,
                         'paper_win_rate':round(wins/pcount,4) if pcount else None,
                         'gross_paper_pnl':round(gross,4),
                         'closed_paper_trades':len(closed),
                         'early_exit_paper_trades':sum(x['status']=='EXITED' for x in closed),
                         'realized_gross_paper_pnl':round(realized,4),
                         'realized_net_paper_pnl':round(realized_net,4),
                         'paper_fee_note':'Modeled one-contract taker fees; bid/ask paper fills, not executed account trades'},
                'count':{'calls':self.conn.execute('SELECT count(*) FROM first_calls').fetchone()[0],
                         'paper':self.conn.execute('SELECT count(*) FROM paper_trades').fetchone()[0]}}

    def export(self, kind):
        if kind not in ('first_calls','paper_trades','observations','engine_snapshots'): raise ValueError('Invalid export')
        with self.lock:
            cur=self.conn.execute(('SELECT * FROM first_calls ORDER BY created' if kind == 'first_calls' else
                'SELECT * FROM engine_snapshots ORDER BY ts' if kind == 'engine_snapshots' else
                f'SELECT * FROM {kind} ORDER BY id'))
            return [x[0] for x in cur.description], [tuple(row) for row in cur.fetchall()]
