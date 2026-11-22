"""Read-only Kalshi and Coinbase REST providers. No account credentials or orders."""
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote as urlquote
import requests
from .engine import normalize_candles, market_snapshot, numeric, utc_timestamp
from .orderbook import normalize_orderbook

KALSHI = 'https://external-api.kalshi.com/trade-api/v2'
COINBASE = 'https://api.exchange.coinbase.com'

# Both forecasting and scalp engines already support >=31 genuine 1m bars.
# Coinbase Exchange may legitimately omit a bar; never synthesize or stretch it.
# This recovery trims only to the most recent TRUE contiguous interval, and
# only when enough consecutive real observations remain for all engines.
MIN_REAL_ONE_MINUTE_BARS = 31
PREFERRED_ONE_MINUTE_BARS = 61
ADVANCED_ONE_MINUTE_BARS = 75


def contiguous_real_candle_suffix(candles, min_bars=MIN_REAL_ONE_MINUTE_BARS, preferred_bars=PREFERRED_ONE_MINUTE_BARS):
    """Return (usable, quality) without fabricating a missing market candle.

    Preserve the exact original data on the normal fully continuous path.
    A positive whole-minute gap can be isolated from the more recent true
    sequence. Non-minute cadence, duplicate or reversed timestamps cannot.
    Never return a shortened sequence that fails existing model minima.
    """
    recent = candles[-preferred_bars:]
    quality = {'status': 'FULL', 'bars_available': len(candles),
               'bars_used': min(len(candles), preferred_bars), 'source': 'coinbase_exchange_real_1m',
               'missing_candles_filled': 0}
    if len(recent) < min_bars:
        quality.update(status='INSUFFICIENT', bars_used=len(candles))
        return candles, quality
    gaps = []
    for i in range(1, len(recent)):
        seconds = recent[i]['t'] - recent[i-1]['t']
        if seconds == 60:
            continue
        if seconds < 120 or seconds % 60:
            quality.update(status='INVALID_CADENCE')
            return candles, quality
        gaps.append((i, seconds))
    if not gaps:
        if len(recent) < PREFERRED_ONE_MINUTE_BARS:
            quality.update(status='SHORT_BUT_CONTIGUOUS')
        return candles, quality
    last_gap_start = gaps[-1][0]
    suffix = recent[last_gap_start:]
    missing = sum(seconds // 60 - 1 for _, seconds in gaps)
    quality['source_gap_minutes'] = missing
    if len(suffix) < min_bars:
        quality.update(status='GAP_TOO_RECENT', bars_used=0,
                       recent_valid_bars=len(suffix))
        return candles, quality
    quality.update(status='RECOVERED_REAL_CONTIGUOUS', bars_used=len(suffix),
                   recent_valid_bars=len(suffix))
    return suffix, quality


class LiveProvider:
    def __init__(self):
        self.candle_quality = None
        self.price_source_at = None
        self.price_received_at = None
        self._five_minute_cache = []
        self._five_minute_cache_at = 0.0
        self.session = requests.Session()
        self.session.headers.update({'User-Agent':'ResearchBot/0.1 (read-only market data)', 'Accept':'application/json'})
    def get(self, url, params=None):
        response = self.session.get(url, params=params, timeout=9)
        response.raise_for_status()
        return response.json()
    def market(self, now=None):
        now = time.time() if now is None else now
        params={'series_ticker':'KXBTC15M','status':'open','limit':200,
                'min_close_ts':int(now),'mve_filter':'exclude'}
        def eligible(payload):
            markets=[]
            for obj in payload.get('markets', []):
                try:
                    # An upcoming listing isn't the currently trading window.
                    if obj.get('status') not in ('open', 'active', None):
                        continue
                    opened=utc_timestamp(obj.get('open_time'))
                    if opened is not None and opened > now:
                        continue
                    m=market_snapshot(obj, now)
                    if 0 < m['seconds_left'] <= 900: markets.append(m)
                except (AttributeError, TypeError, ValueError):
                    pass
            # Never reuse an expired contract or invent a future strike.
            return min(markets,key=lambda m:m['seconds_left']) if markets else None
        # A newly opened contract may be briefly absent from Kalshi's
        # published list OR the listing endpoint may transiently return 503.
        # Permit exactly one bounded retry in the first 90s of a REAL 15m
        # boundary. Outside that interval preserve the original HTTP error.
        # Never reuse an expired ticker, infer a strike or fabricate a book.
        rollover = 0 <= (now % 900) <= 90 and abs(time.time()-now) < 30
        try:
            active=eligible(self.get(f'{KALSHI}/markets',params))
        except requests.HTTPError as exc:
            status=exc.response.status_code if exc.response is not None else None
            if not rollover or status not in (404,429,500,502,503,504):
                raise
            active=None
        if active:
            return active
        if rollover:
            time.sleep(.4)
            try:
                active=eligible(self.get(f'{KALSHI}/markets',params))
            except requests.RequestException:
                # No inferred fallback if the published primary source fails.
                return None
            if active:
                return active
        # The /markets index can lag an active 15-minute event. Query Kalshi's
        # independent event listing ONLY for a genuinely current live poll,
        # and accept only its published open BTC15M nested market records.
        if abs(time.time()-now) < 30:
            try:
                payload=self.get(f'{KALSHI}/events',
                                 {'series_ticker':'KXBTC15M','status':'open',
                                  'with_nested_markets':'true','limit':100})
                nested=[market for event in payload.get('events',[])
                        if isinstance(event,dict) and event.get('series_ticker')=='KXBTC15M'
                        for market in event.get('markets',[])]
                return eligible({'markets':nested})
            except requests.RequestException:
                return None
        return None
    def orderbook(self, market, now=None):
        """Request ALL available aggregated levels (depth=0), no account key.

        This is a single REST snapshot, not a WebSocket history and not
        visibility into individual user orders or live fills.
        """
        if not isinstance(market, dict) or not str(market.get('ticker','')).startswith('KXBTC15M-'):
            raise ValueError('Full depth requires a valid BTC15m market')
        ticker=market['ticker']
        if '/' in ticker or '?' in ticker or '#' in ticker:
            raise ValueError('Invalid order-book ticker')
        # Optional depth must never consume the 9-second critical data
        # timeout; bound its additional latency to 2 seconds.
        response=self.session.get(f'{KALSHI}/markets/{urlquote(ticker,safe="")}/orderbook',
                                  params={'depth':0}, timeout=2)
        response.raise_for_status()
        raw=response.json()
        # Timestamp after successful GET: no false claim about exchange event time.
        # True local receipt AFTER successful network response, never the
        # poll-start timestamp passed from the main worker.
        received=time.time()
        return normalize_orderbook(raw,ticker,received)
    def price(self):
        raw = self.get(f'{COINBASE}/products/BTC-USD/ticker')
        p = numeric(raw.get('price'))
        if p is None or p <= 0: raise ValueError('Invalid Coinbase BTC price')
        self.price_source_at = utc_timestamp(raw.get('time'))
        self.price_received_at = time.time()
        if self.price_source_at is not None and (self.price_source_at > self.price_received_at+2 or
                                                  self.price_received_at-self.price_source_at > 90):
            raise ValueError('Coinbase last trade is stale or future-dated')
        return p
    def candles(self):
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=85)
        data = self.get(f'{COINBASE}/products/BTC-USD/candles', {
            'start': start.isoformat(), 'end': now.isoformat(), 'granularity':60,
        })
        real_bars = normalize_candles(data)
        usable, quality = contiguous_real_candle_suffix(real_bars,
                   preferred_bars=ADVANCED_ONE_MINUTE_BARS)
        self.candle_quality = quality
        return usable
    def timeframe_candles(self, now=None):
        """Real Coinbase 5m OHLCV for 30m/1h/2h BTC structure.

        Uses only EXCHANGE COMPLETED 5m candles and their native UTC slots.
        Does not manufacture gaps or resample 61m into a fake two-hour chart.
        One bounded public market-data GET per 90 seconds.
        """
        clock=time.time() if now is None else float(now)
        if self._five_minute_cache and 0<=clock-self._five_minute_cache_at<90:
            return list(self._five_minute_cache)
        end=datetime.now(timezone.utc)
        if now is not None:
            end=datetime.fromtimestamp(clock,timezone.utc)
        start=end-timedelta(minutes=740)
        raw=self.get(f'{COINBASE}/products/BTC-USD/candles',{
            'start':start.isoformat(),'end':end.isoformat(),'granularity':300,
        })
        bars=normalize_candles(raw)
        complete=[b for b in bars if b['t']%300==0 and
                  b['t']+300<=clock and b.get('volume',0)>=0]
        if not complete:
            return []
        # A missing bar is not silently replaced with the last known price.
        k=1
        while k<len(complete) and complete[-k]['t']-complete[-k-1]['t']==300:
            k+=1
        self._five_minute_cache=complete[-k:]
        self._five_minute_cache_at=clock
        return list(self._five_minute_cache)

    def settlement(self, ticker):
        if not ticker.startswith('KXBTC15M-') or '/' in ticker: raise ValueError('Bad ticker')
        t = urlquote(ticker, safe='')
        for path in (f'/markets/{t}', f'/historical/markets/{t}'):
            try:
                data = self.get(f'{KALSHI}{path}')
                m = data.get('market') or {}
                result = str(m.get('result') or '').lower()
                status=str(m.get('status') or '').lower()
                if result in ('yes','no') and status in ('settled','finalized'):
                    return result
                if status == 'open':
                    # Never grade an open contract, even if a stray result
                    # field appears. Preserve prior ungraded behavior.
                    return None
                # A closed/pending live-market record may lag the historical
                # finalized record. Continue to the historical endpoint
                # instead of prematurely returning None.
                continue
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404: continue
                raise
        return None

class DemoProvider:
    """Offline demonstration with explicitly synthetic prices and results."""
    def __init__(self):
        self.seed = 90000.0
    def market(self, now=None):
        import math
        now = time.time() if now is None else now
        block = int(now // 900)
        end = (block+1)*900
        spot = self._value(now)
        target = self._value(block*900)
        p = max(.02, min(.98, .5 + (spot-target)/650))
        obj = {'ticker':f'KXBTC15M-DEMO-{block}', 'close_time':datetime.fromtimestamp(end,timezone.utc).isoformat(),
               'status':'open','floor_strike':round(target,2),'yes_bid_dollars':f'{max(.01,p-.025):.4f}',
               'yes_ask_dollars':f'{min(.99,p+.025):.4f}', 'no_bid_dollars':f'{max(.01,1-p-.025):.4f}',
               'no_ask_dollars':f'{min(.99,1-p+.025):.4f}', 'title':'DEMO: Synthetic BTC up in 15m?'}
        # Demo tickers are not Kalshi tickers; bypass normal prefix restriction? Valid prefix yes.
        return market_snapshot(obj, now)
    def _value(self, t):
        import math
        return self.seed + 200*math.sin(t/180) + 120*math.sin(t/80) + 25*math.sin(t/13)
    def orderbook(self, market, now=None):
        """Explicitly synthetic aggregated depth for offline demonstration only."""
        from decimal import Decimal
        t=time.time() if now is None else float(now)
        def levels(top):
            if top is None: return []
            p=Decimal(str(top))
            return [[str(p-Decimal('0.01')*i),str(10+15*i)]
                    for i in range(3,-1,-1) if Decimal('0')<p-Decimal('0.01')*i<Decimal('1')]
        payload={'orderbook_fp':{'yes_dollars':levels(market.get('yes_bid')),
                                 'no_dollars':levels(market.get('no_bid'))}}
        out=normalize_orderbook(payload,market['ticker'],t)
        out['source']='synthetic_demo_orderbook'
        out['reason']='SYNTHETIC aggregated depth; not exchange liquidity'
        return out
    def price(self): return round(self._value(time.time()),2)
    def candles(self):
        now = int(time.time()//60)*60
        out=[]
        for i in range(62):
            t=now-(61-i)*60; op=self._value(t); cl=self._value(t+59)
            out.append([t, min(op,cl)-18, max(op,cl)+18, op, cl, 3.5+i/100])
        return normalize_candles(out)
    def settlement(self, ticker):
        if not ticker.startswith('KXBTC15M-DEMO-'): return None
        block = int(ticker.rsplit('-',1)[-1]); end=(block+1)*900
        if time.time() < end+5: return None
        return 'yes' if self._value(end-60)>=self._value(block*900) else 'no'
