"""Read-only preservation inventory and disjoint ownership plan for acceleration."""
import datetime as dt,json,pathlib,re,sys
from research.historical_180 import write_json
index=pathlib.Path(sys.argv[1]);jobs=json.load(open(sys.argv[2]))['jobs'];artifacts=[json.loads(l) for l in open(sys.argv[3]) if l.strip()];out=pathlib.Path(sys.argv[4]);out.mkdir(parents=True,exist_ok=True)
byname={a['name']:a for a in artifacts};done=[];active=[]
for j in jobs:
 m=re.match(r'daily \((\d{4}-\d{2}-\d{2})',j['name'])
 if not m:continue
 d=m[1]
 if j['conclusion']=='success' and 'PUBLIC_180_'+d+'_DATA' in byname and 'PUBLIC_180_'+d+'_SUMMARY' in byname:done.append(d)
 if j['status']=='in_progress':active.append(d)
cutoff=(dt.date.fromisoformat(max(active))+dt.timedelta(days=1)).isoformat() if active else min(r['day'] for r in json.load(open(index/'DAY_PLAN.json')) if r['day'] not in done)
plan=[r for r in json.load(open(index/'DAY_PLAN.json')) if r['day']>=cutoff and r['day'] not in done]
# Preserve all active legacy jobs, while accelerating disjoint future dates.
pilot=plan[:4]+plan[-4:] if len(plan)>8 else plan
pilot=list({p['day']:p for p in pilot}.values());ordered=pilot+[p for p in plan if p['day'] not in {r['day'] for r in pilot}]
write_json(out/'PRESERVED_ARTIFACTS.json',artifacts)
write_json(out/'OWNERSHIP.json',{'legacy_run_id':43808575205,'legacy_reserved_before':cutoff,'completed_legacy_dates':done,'active_legacy_dates_preserved':active,'optimized_dates':[p['day'] for p in plan],'pilot_dates':[p['day'] for p in pilot]})
write_json(out/'PLAN.json',ordered);write_json(out/'PILOT.json',pilot)
with open(__import__('os').environ['GITHUB_OUTPUT'],'a') as f:
 f.write('pilot='+json.dumps(pilot,separators=(',',':'))+'\n');f.write('main='+json.dumps(ordered,separators=(',',':'))+'\n')
print('PRESERVED',len(done),'complete days and',len(artifacts),'artifacts; ACTIVE_LEGACY',active,'OPTIMIZED_DATES',len(plan),'BOUNDARY',cutoff)
