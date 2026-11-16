"""Publish audited coverage without labeling incomplete source history complete."""
import datetime as dt,json,pathlib,sys,collections,os
from research.historical_180 import write_json,BEGIN,END
root=pathlib.Path(sys.argv[1]);summarydir=pathlib.Path(sys.argv[2]);out=pathlib.Path(sys.argv[3]);out.mkdir(parents=True,exist_ok=True)
prior=pathlib.Path('previous_master/MASTER_PUBLIC_180.json')
days=json.loads(prior.read_text()).get('daily_reports',{}) if prior.exists() else {}
for p in summarydir.rglob('COLLECTION_STATUS.json'):
    r=json.loads(p.read_text());days[r['date_utc']]=r
reuse=json.loads((root/'REUSE_MANIFEST.json').read_text());plan=json.loads((root/'DAY_PLAN.json').read_text())
failed=[]
for p in plan:
    r=days.get(p['day'],{})
    if not r.get('collection_completed') or not r.get('independent_audit',{}).get('independent_complete_population_audit_passed') or r.get('limited_validation_sample'):
        failed.append(p)
artifacts=[];ap=pathlib.Path('current_artifacts.jsonl')
if prior.exists():artifacts.extend(json.loads(prior.read_text()).get('artifacts',[]))
if ap.exists():
    for line in ap.read_text().splitlines():
        a=json.loads(line);a['url']=f"https://github.com/szmohmand/Axiom/actions/runs/{os.environ['GITHUB_RUN_ID']}/artifacts/{a['id']}";artifacts.append(a)
report={'target_dates':[BEGIN.isoformat(),(END-dt.timedelta(days=1)).isoformat()],
        'public_collection_completed':not failed,'complete_180day_dataset':False,
        'reason_complete_dataset_not_asserted':'BRTI alignment, date-specific fees and execution/depth availability require separate source audits',
        'failed_or_missing_days':[p['day'] for p in failed],'daily_reports':days,'reuse':reuse,'artifacts':artifacts,
        'actual_new_trade_ticks':sum(sum(c.get('trade_ticks',0) for c in r.get('contract_results',[])) for r in days.values()),
        'new_quote_rows':sum(sum(c.get('quote_rows',0) for c in r.get('contract_results',[])) for r in days.values()),
        'library_destination':'/BTC Historical Research/','library_transfer_status':'PENDING'}
write_json(out/'MASTER_PUBLIC_180.json',report);write_json(out/'NEXT_PLAN.json',failed)
(out/'README_START_HERE.md').write_text('180-day public contract, quote and trade archive index. Check MASTER_PUBLIC_180.json before using any daily archive. Only days with complete source pagination AND independent audit count as complete collection. This does not prove executable fills or historical L2. Missing historical fees/depth are not synthesized. Original source response bytes and native event timestamps are retained. Library transfer is pending; the user will arrange placement.\n')
import csv
with (out/'COVERAGE_MATRIX.csv').open('w') as f:
    w=csv.writer(f);w.writerow(['date_utc','source_collection_complete','independent_audit_passed','new_quote_rows','reused_quote_rows','new_trade_ticks','failure_count'])
    for i in range(180):
        d=(BEGIN+dt.timedelta(days=i)).isoformat();r=days.get(d,{});cs=r.get('contract_results',[])
        w.writerow([d,r.get('collection_completed',False),r.get('independent_audit',{}).get('independent_complete_population_audit_passed',False),sum(c.get('quote_rows',0) for c in cs),reuse['august_quote_rows'].get(d,0)+reuse.get('thirty_day_quote_rows',{}).get(d,0),sum(c.get('trade_ticks',0) for c in cs),len(r.get('failed_contracts',[]))])
print(json.dumps({k:v for k,v in report.items() if k not in ['daily_reports','artifacts','reuse']}))
