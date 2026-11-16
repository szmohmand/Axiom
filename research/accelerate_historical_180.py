"""Research-only persistent HTTP, adaptive public-IP pacing and bounded batches."""
import argparse,collections,email.utils,json,os,pathlib,random,time
import requests
from research import historical_180 as H

class DeadlineReached(RuntimeError):pass

class AdaptiveClient:
    def __init__(self,root,deadline=None,initial_rps=4.0,max_rps=6.0):
        self.session=requests.Session();self.session.headers.update({'User-Agent':'AXIOM-readonly-historical-research/2','Accept':'application/json'})
        self.root=pathlib.Path(root);self.deadline=deadline;self.rps=initial_rps;self.max_rps=max_rps
        self.last=0.0;self.started=time.monotonic();self.success_streak=0
        self.metrics=collections.Counter();self.latencies=[]
    def save(self):
        elapsed=time.monotonic()-self.started
        out={**dict(self.metrics),'elapsed_seconds':elapsed,'current_request_ceiling_rps':self.rps,
             'http_successes_per_second':self.metrics['http_200']/elapsed if elapsed else 0,
             'mean_http_latency_seconds':sum(self.latencies)/len(self.latencies) if self.latencies else None,
             'new_trade_rows_per_second':self.metrics['new_trade_rows']/elapsed if elapsed else 0,
             'pacing_policy':'Public IP budget: measured latency, available rate headers, multiplicative decrease on 429; no account-tier assumption'}
        H.write_json(self.root/'PERFORMANCE.json',out);return out
    def get(self,url,cap=30_000_000):
        for attempt in range(9):
            if self.deadline and time.time()+45>=self.deadline:raise DeadlineReached('Finalization reserve reached; raw cache retained')
            time.sleep(max(0,1/self.rps-(time.monotonic()-self.last)))
            self.last=time.monotonic();self.metrics['http_attempts']+=1
            try:
                t=time.monotonic();response=self.session.get(url,timeout=(10,35));latency=time.monotonic()-t
                self.latencies.append(latency);self.metrics['http_'+str(response.status_code)]+=1
                if response.status_code==200:
                    raw=response.content
                    if len(raw)>cap:raise ValueError('Source response exceeds size bound')
                    self.metrics['http_bytes']+=len(raw);self.success_streak+=1
                    if self.success_streak>=10:
                        self.rps=min(self.max_rps,self.rps+.5);self.success_streak=0
                    remaining=response.headers.get('X-RateLimit-Remaining');cost=response.headers.get('X-RateLimit-Cost')
                    if remaining and cost and float(remaining)<float(cost):
                        wait=float(response.headers.get('X-RateLimit-Reset','0.5'));time.sleep(min(30,max(.25,wait)))
                    if self.metrics['http_200']%10==0:self.save()
                    return raw
                if response.status_code==429:
                    self.rps=max(.25,self.rps*.5);self.success_streak=0
                    delay=float(response.headers.get('Retry-After') or response.headers.get('X-RateLimit-Reset') or min(30,.5*2**attempt))
                elif response.status_code in (500,502,503,504):delay=min(30,.5*2**attempt)
                else:raise RuntimeError('Public GET rejected with HTTP '+str(response.status_code))
            except (requests.Timeout,requests.ConnectionError):
                self.metrics['network_errors']+=1;delay=min(30,.5*2**attempt)
            self.save()
            if attempt==8:raise RuntimeError('Read-only source retries exhausted; raw checkpoints retained')
            time.sleep(max(.25,delay)+random.uniform(0,.2))


def run(root,index,day,offset,limit,quotes,trades,deadline=None,cache_roots=()):
    client=AdaptiveClient(root,deadline)
    original_source=H.PublicSource
    class FastSource(original_source):
        def __init__(self,path,delay=0):super().__init__(path,delay=0,getter=client.get,cache_roots=cache_roots)
        def fetch(self,*args,**kwargs):
            before=self.network_requests
            obj,meta=super().fetch(*args,**kwargs)
            if self.network_requests>before:client.metrics['new_trade_rows']+=len(obj.get('trades',[]))
            return obj,meta
    H.PublicSource=FastSource
    try:
        return H.collect_day(root,index,day,quotes,trades,contract_offset=offset,contract_limit=limit,deadline_epoch=deadline)
    finally:
        H.PublicSource=original_source;client.save();client.session.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--index',required=True);p.add_argument('--day',required=True)
    p.add_argument('--offset',type=int,default=0);p.add_argument('--limit',type=int,default=16);p.add_argument('--deadline',type=float)
    p.add_argument('--cache-root',action='append',default=[]);p.add_argument('--no-quotes',action='store_true');p.add_argument('--no-trades',action='store_true')
    a=p.parse_args();run(a.root,a.index,a.day,a.offset,a.limit,not a.no_quotes,not a.no_trades,a.deadline,a.cache_root)
