"""Research-only automatic archive reconciliation and missing-group continuation.

No market API calls. Reads immutable Actions archives, validates their digests,
keeps every previous archive reference and schedules only incomplete groups.
"""
import collections,datetime as dt,gzip,hashlib,io,json,os,pathlib,re,subprocess,time,zipfile
from research.historical_180 import iter_jsonl,write_json
REPO='szmohmand/Axiom'

def gh(*args):return subprocess.check_output(['gh',*args],text=True)
def artifacts(run):
    text=gh('api','--paginate',f'repos/{REPO}/actions/runs/{run}/artifacts?per_page=100','--jq','.artifacts[] | @json')
    return [{**json.loads(line),'run_id':int(run)} for line in text.splitlines() if line.strip()]
def read_archive(a):
    raw=subprocess.check_output(['gh','api',f'repos/{REPO}/actions/artifacts/{a["id"]}/zip'])
    expected=a.get('digest','').removeprefix('sha256:')
    if len(raw)!=a['size_in_bytes'] or not expected or hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('Published Actions archive digest mismatch')
    z=zipfile.ZipFile(io.BytesIO(raw))
    return {pathlib.PurePosixPath(n).name:json.loads(z.read(n)) for n in z.namelist() if n.endswith('.json')}

def complete_group(status,expected,offset):
    rows=status.get('contract_results',[]);ids=[r['ticker'] for r in rows]
    return (status.get('collection_completed') and not status.get('limited_validation_sample') and
            status.get('independent_audit',{}).get('independent_complete_population_audit_passed') and
            status.get('contract_offset')==offset and len(ids)==len(set(ids)) and set(ids)==set(expected))

def snapshot(runs,index,state):
    all_art=[]
    for run in runs:all_art.extend(artifacts(run))
    byname={(a['run_id'],a['name']):a for a in all_art}
    for a in all_art:
        name=a['name'];key=str(a['id'])
        if key in state['summaries']:continue
        if name.endswith('_SUMMARY'):
            try:state['summaries'][key]=read_archive(a)
            except (subprocess.CalledProcessError,ValueError,zipfile.BadZipFile) as e:
                print('SUMMARY_RETRY',a['id'],type(e).__name__,flush=True)
    contracts={p.stem.replace('.jsonl',''):list(iter_jsonl(p)) for p in (index/'BY_DAY').glob('*.jsonl.gz')}
    candidates=collections.defaultdict(list);legacy={};performance=[]
    for a in all_art:
        payload=state['summaries'].get(str(a['id']),{});s=payload.get('COLLECTION_STATUS.json')
        if not s:continue
        audit=payload.get('INDEPENDENT_AUDIT.json',{})
        s={**s,'independent_audit':audit};day=s['date_utc'];expected=[m['ticker'] for m in contracts[day]]
        data=byname.get((a['run_id'],a['name'].removesuffix('_SUMMARY')+'_DATA'))
        if not data:continue
        ref={'artifact_id':data['id'],'run_id':a['run_id'],'name':data['name'],'bytes':data['size_in_bytes'],
             'sha256':data['digest'].removeprefix('sha256:'),'url':f'https://github.com/{REPO}/actions/runs/{a["run_id"]}/artifacts/{data["id"]}'}
        if a['name'].startswith('PUBLIC_180_') and s.get('contract_limit') is None:
            ids=[r['ticker'] for r in s['contract_results']]
            if s.get('collection_completed') and audit.get('independent_complete_population_audit_passed') and len(ids)==len(set(ids)) and set(ids)==set(expected):legacy[day]=(s,ref)
        else:
            offset=s.get('contract_offset',0);limit=s.get('contract_limit',16)
            if complete_group(s,expected[offset:offset+limit],offset):candidates[day].append((offset,s,ref))
        if payload.get('PERFORMANCE.json'):performance.append({'artifact_id':a['id'],**payload['PERFORMANCE.json']})
    days={};missing=[]
    reuse=json.loads((index/'REUSE_MANIFEST.json').read_text())
    for day,markets in sorted(contracts.items()):
        if day in legacy:
            s,ref=legacy[day];days[day]={'complete':True,'contracts':len(markets),'trades':sum(r.get('trade_ticks',0) for r in s['contract_results']),'quotes':sum(r.get('quote_rows',0) for r in s['contract_results']),'sources':[ref]};continue
        parts={}
        for offset,s,ref in candidates[day]:parts[offset]=(s,ref)
        needed=list(range(0,len(markets),16));absent=[offset for offset in needed if offset not in parts]
        if not absent:
            days[day]={'complete':True,'contracts':len(markets),'trades':sum(r.get('trade_ticks',0) for s,_ in parts.values() for r in s['contract_results']),
                       'quotes':sum(r.get('quote_rows',0) for s,_ in parts.values() for r in s['contract_results'])+reuse.get('august_quote_rows',{}).get(day,0),'sources':[ref for _,ref in parts.values()]}
        else:
            days[day]={'complete':False,'contracts':len(markets),'verified_groups':len(parts),'missing_offsets':absent}
            for offset in absent:
                latest=[a for a in all_art if a['name'].endswith(f'{day}_GROUP_{offset//16:02d}_DATA')]
                seed=max(latest,key=lambda a:a.get('created_at','')) if latest else None
                missing.append({'day':day,'offset':offset,'quotes':day not in reuse.get('august_quote_rows',{}),'trades':True,
                                'seed_id':seed['id'] if seed else 0,'seed_sha':seed.get('digest','').removeprefix('sha256:') if seed else '',
                                'seed_bytes':seed['size_in_bytes'] if seed else 0})
    completed=sum(r['complete'] for r in days.values());now=dt.datetime.now(dt.timezone.utc).isoformat()
    report={'as_of_utc':now,'runs':runs,'completed_days':completed,'remaining_days':180-completed,
            'completed_contracts':sum(r['contracts'] for r in days.values() if r['complete']),
            'actual_verified_trades':sum(r.get('trades',0) for r in days.values() if r['complete']),
            'quote_rows_in_completed_days':sum(r.get('quotes',0) for r in days.values() if r['complete']),
            'public_contract_quote_trade_collection_complete':completed==180,'complete_all_requested_fields':False,
            'limitations':['Historical L2 depth and date-specific fee effectiveness remain unverified','Minute candles are not continuously executable quotes','Full BRTI coverage/gap audit remains separate and is not rerun'],
            'days':days,'performance':performance,'preserved_artifacts':[{k:a.get(k) for k in ['id','name','size_in_bytes','digest','run_id']} for a in all_art],
            'library_transfer_status':'PENDING','library_destination':'/BTC Historical Research/'}
    state['runs']=runs;write_json(pathlib.Path('monitor/MASTER_COLLECTION.json'),report)
    write_json(pathlib.Path('monitor/MISSING_GROUPS.json'),missing);write_json(pathlib.Path('monitor/STATE.json'),state)
    print('VERIFIED_PROGRESS',completed,'of 180 days;',report['completed_contracts'],'contracts;',report['actual_verified_trades'],'trades;',len(missing),'missing groups',flush=True)
    return report,missing

def main():
    pathlib.Path('monitor').mkdir(exist_ok=True)
    state=json.load(open('previous/STATE.json')) if pathlib.Path('previous/STATE.json').exists() else {'summaries':{},'runs':[]}
    fast=json.loads(gh('run','list','--repo',REPO,'--workflow','axiom-180day-fast16.yml','--limit','1','--json','databaseId'))[0]['databaseId']
    runs=list(dict.fromkeys([43808575205,43817684448,fast,*state['runs']]))
    deadline=time.monotonic()+40*60
    while True:
        report,missing=snapshot(runs,pathlib.Path('contract_index'),state)
        if report['public_contract_quote_trade_collection_complete']:
            # Only stop redundant legacy reads after ALL 180 canonical dates are independently complete.
            stopped=[]
            for prior in [43808575205,43817684448]:
                status=json.loads(gh('run','view',str(prior),'--repo',REPO,'--json','status'))['status']
                if status!='completed':
                    subprocess.run(['gh','run','cancel',str(prior),'--repo',REPO],check=True)
                    stopped.append(prior)
            report['redundant_runs_stop_requested_after_complete_canonical_coverage']=stopped
            report['stop_reason']='Every target contract/transaction population already has an independently validated retrievable canonical archive; prior uploaded artifacts are retained.'
            write_json(pathlib.Path('monitor/MASTER_COLLECTION.json'),report)
            break
        statuses=[json.loads(gh('run','view',str(r),'--repo',REPO,'--json','status'))['status'] for r in runs if r!=43808575205]
        if all(s=='completed' for s in statuses):
            attempts=state.get('continuation_attempts',0)
            if missing and attempts<4:
                legacy_jobs=json.loads(gh('run','view','43808575205','--repo',REPO,'--json','jobs'))['jobs']
                active_legacy={re.search(r'\((\d{4}-\d{2}-\d{2})',j['name'])[1] for j in legacy_jobs if j['status']=='in_progress' and j['name'].startswith('daily (')}
                groups=[g for g in missing if g['day'] not in active_legacy][:256]
                if not groups:
                    time.sleep(120);continue
                # Resume only incomplete groups, using their latest preserved original-response cache.
                subprocess.run(['gh','workflow','run','axiom-180day-group-resume.yml','--repo',REPO,'--ref','research/historical-data-completion-2026-11-16','--json'],input=json.dumps({'groups':json.dumps(groups),'index_run':str(fast)}),text=True,check=True)
                time.sleep(10)
                new=json.loads(gh('run','list','--repo',REPO,'--workflow','axiom-180day-group-resume.yml','--limit','1','--json','databaseId'))[0]['databaseId']
                runs.append(new);state['continuation_attempts']=attempts+1;state['runs']=runs;write_json(pathlib.Path('monitor/STATE.json'),state)
            else:break
        if time.monotonic()>=deadline:break
        time.sleep(120)
if __name__=='__main__':main()
