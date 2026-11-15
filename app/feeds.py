"""Read-only Kalshi and Coinbase REST providers. No account credentials or orders."""
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote as urlquote
import requests
from .engine import normalize_candles, market_snapshot, numeric

KALSHI = 'https://external-api.kalshi.com/trade-api/v2'
COINBASE = 'https://api.exchange.coinbase.com'

class LiveProvider:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent':'ResearchBot/0.1 (read-only market data)', 'Accept':'application/json'})
    def get(self, url, params=None):
        response = self.session.get(url, params=params, timeout=9)
        response.raise_for_status()
        return response.json()
    def market(self, now=None):
        now = time.time() if now is None else now
        payload = self.get(f'{KALSHI}/markets', {'series_ticker':'KXBTC15M','status':'open','limit':30})
        markets = []
        for obj in payload.get('markets', []):
            try:
                m = market_snapshot(obj, now)
                if m['seconds_left'] > 0: markets.append(m)
            except (TypeError, ValueError):
                pass
        if not markets: return None
        # Prefer current active window with nearest imminent close.
        return sorted(markets, key=lambda m:m['seconds_left'])[0]
    def price(self):
        raw = self.get(f'{COINBASE}/products/BTC-USD/ticker')
        p = numeric(raw.get('price'))
        if p is None or p <= 0: raise ValueError('Invalid Coinbase BTC price')
        return p
    def candles(self):
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=65)
        data = self.get(f'{COINBASE}/products/BTC-USD/candles', {
            'start': start.isoformat(), 'end': now.isoformat(), 'granularity':60,
        })
        return normalize_candles(data)
    def settlement(self, ticker):
        if not ticker.startswith('KXBTC15M-') or '/' in ticker: raise ValueError('Bad ticker')
        t = urlquote(ticker, safe='')
        for path in (f'/markets/{t}', f'/historical/markets/{t}'):
            try:
                data = self.get(f'{KALSHI}{path}')
                m = data.get('market') or {}
                result = str(m.get('result') or '').lower()
                if result in ('yes','no') and str(m.get('status') or '').lower() in ('settled','finalized'):
                    return result
                return None
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
