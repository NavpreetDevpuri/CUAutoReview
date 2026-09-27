#!/usr/bin/env python3
"""Import three disjoint demo datasets and soft-archive only known old fixtures."""
from __future__ import annotations
import json
import urllib.request
from pathlib import Path
from seed_demo import Client, MANIFEST, ROOT
BASE='http://127.0.0.1:8000'
FIXTURE_PREFIXES=('Acceptance ', 'Acceptance ZIP ', 'Unknown outcome check ', 'Batch completion check ')
RUN_PREFIXES=('Acceptance ', 'Acceptance replay ', 'Fixed acceptance ', 'Unknown outcome waits ', 'Batch completion saved replay ')
def main():
 m=json.loads(MANIFEST.read_text()); account=next(a for a in m['accounts'] if a['key']=='admin'); c=Client(BASE)
 c.call('POST','/auth/login',{key:account[key] for key in ('email','password')})
 existing=c.call('GET','/datasets?include_archived=true&per_page=500')['items']
 manifest=json.loads((ROOT/'platform/demo-data/manifest.json').read_text())
 report={'datasets':[],'archived_dataset_ids':[],'archived_run_ids':[],'new_inference_calls':0}
 for item in manifest['datasets']:
  dataset=next((d for d in existing if d['name']==item['name']),None)
  if not dataset: dataset=c.call('POST','/datasets',{'name':item['name'],'description':f"Distinct public OSWorld tasks for {item['name'].lower()}. Pinned historical rollouts with source scores; human failure labels are not supplied."})
  if dataset.get('archived'): c.call('POST',f"/datasets/{dataset['id']}/restore")
  request=urllib.request.Request(BASE+f"/api/datasets/{dataset['id']}/import-zip",data=(ROOT/item['zip']).read_bytes(),method='POST',headers={'Content-Type':'application/zip','Origin':BASE})
  with c.opener.open(request,timeout=90) as response: imported=json.load(response)
  c.call('PUT',f"/datasets/{dataset['id']}/shares",{'workspace_shared':True,'users':[],'teams':[{'target_id':team['id'],'role':'reviewer' if team['name']=='Demo Reviewers' else 'viewer'} for team in m['teams']]})
  tasks=c.call('GET',f"/datasets/{dataset['id']}")['tasks']
  report['datasets'].append({**item,'id':dataset['id'],'tasks':[{'task_id':t['task_id'],'task_definition_id':t.get('task_definition_id') or t.get('definition_id') or t['id'],'title':t.get('title')} for t in tasks], 'import':{k:imported.get(k) for k in ('created','revised','unchanged')}})
  print(f"{item['name']}: {len(tasks)} tasks",flush=True)
 for dataset in existing:
  if dataset['name'].startswith(FIXTURE_PREFIXES) or dataset['name'] in ('Saved POC examples','Example ZIP walkthrough'):
   c.call('POST',f"/datasets/{dataset['id']}/archive")
   report['archived_dataset_ids'].append(dataset['id'])
 runs=c.call('GET','/runs?include_archived=true&per_page=500')['items']
 for run in runs:
  if (run['name'].startswith(RUN_PREFIXES) or run['name']=='Retained POC replay') and run['status'] not in ('running','queued'):
   c.call('POST',f"/runs/{run['id']}/archive")
   report['archived_run_ids'].append(run['id'])
 catalog=c.call('GET','/catalog'); demoids={d['id'] for d in report['datasets']}; tasks=[t for t in catalog['tasks'] if t['dataset_id'] in demoids]
 assert len(tasks)==8 and len({t['task_id'] for t in tasks})==8
 report['verified_unique_task_count']=8
 (ROOT/'platform/demo-data/import-report.json').write_text(json.dumps(report,indent=2)+'\n')
 print('Verified eight unique tasks. Historical fixtures were archived, not deleted.',flush=True)
if __name__=='__main__': main()
