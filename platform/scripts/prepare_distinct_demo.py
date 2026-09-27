#!/usr/bin/env python3
"""Prepare eight distinct public tasks as three ZIP imports; preserve POC evidence."""
from __future__ import annotations
import concurrent.futures
import copy
import importlib.util
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'platform/demo-data'
SOURCE = OUT / 'source'
spec = importlib.util.spec_from_file_location('poc_prepare', ROOT / 'poc/prepare_data.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
NEW = [('chrome','030eeff7-b492-4218-b312-701ec99ee0cc'), ('chrome','06fe7178-4491-4589-810f-2e2bc9502122'), ('gimp','045bf3ff-9077-4b86-b483-a1040a949cff')]
GROUPS = [
 ('office','Office documents', ['0e47de2a-32e0-456c-a366-8c607ef7a9d2','66399b0d-8fda-4618-95c4-bfc6191617e9','6e99a1ad-07d2-4b66-a1ce-ece6d99c20a5']),
 ('web','Web browsing',['368d9ba4-203c-40c1-9fa3-da2f1430ce63',NEW[0][1],NEW[1][1]]),
 ('graphics','Image editing',['b148e375-fe0b-4bec-90e7-38632b0d73c2',NEW[2][1]])]
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 cache=ROOT/'platform/.local/osworld-central.json'
 entries=json.loads(cache.read_text()) if cache.exists() else p.parse_central_directory(p.curl_range(p.CD_START,p.CD_END),p.curl_range(p.EOCD_START,p.EOCD_END))
 tasks={t['task_id']: copy.deepcopy(t) for t in json.loads((ROOT/'poc/data/batch.json').read_text())['tasks']}
 provenance=[]
 for app,tid in NEW:
  folder=SOURCE/tid; folder.mkdir(parents=True,exist_ok=True)
  members=[e for e in entries if e['name'].startswith(f'o3_15steps/{app}/{tid}/') and (e['name'].endswith(('/traj.jsonl','/result.txt')) or e['name'].endswith('.png'))]
  assert sum(e['uncompressed_size'] for e in members)<15_000_000
  prior=json.loads((folder/'provenance.json').read_text()) if (folder/'provenance.json').exists() else {}
  metadata=prior.get('files',{})
  def fetch(entry):
   name=Path(entry['name']).name
   if (folder/name).exists() and name in metadata and p.sha256((folder/name).read_bytes())==metadata[name]['sha256']: return name,metadata[name]
   meta,data=p.extract_member(entry); (folder/name).write_bytes(data); return name,meta
  with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
   metadata.update(dict(pool.map(fetch,members)))
  url=f'https://raw.githubusercontent.com/xlang-ai/OSWorld/{p.TASK_COMMIT}/evaluation_examples/examples/{app}/{tid}.json'
  if not (folder/'task.json').exists(): (folder/'task.json').write_bytes(p.curl_url(url))
  task=json.loads((folder/'task.json').read_text()); rows=p.parse_jsonl((folder/'traj.jsonl').read_bytes()); score=float((folder/'result.txt').read_text().strip())
  shots={int(f.name.split('_',2)[1]):f for f in folder.glob('step_*.png')}
  steps=[]
  for i,row in enumerate(rows,1):
   n=row.get('step_num',row.get('step',i)); n=n if isinstance(n,int) else i
   steps.append({'step_id':str(n),'intent':p.first_text(row,('comment','thought','intent','description')),'action':p.action_text(row.get('action',row.get('response',row))),'observation':p.first_text(row,('observation','obs','result')),'screenshot':str(shots[n].relative_to(ROOT)) if n in shots else None,'evidence_refs':[f'event_{n}']+([f'frame_{n}'] if n in shots else [])})
  tasks[tid]={'task_id':tid,'title':task.get('instruction',tid),'instruction':task.get('instruction',''),'outcome':'passed' if score==1 else 'failed' if score==0 else 'unknown','score':score,'source':{'dataset':'OSWorld-Verified','application':app,'task_id':tid,'agent_model':'o3','archive':p.ARCHIVE_URL,'dataset_commit':p.DATASET_COMMIT,'task_source_commit':p.TASK_COMMIT,'task_definition_url':url},'coverage_notes':['Public recorded rollout; not executed locally.','Final evaluator score is retained; no human failure diagnosis is supplied.','Pinned current task definition is not proven to be the exact historical evaluator.','Video not downloaded. Screenshots retain their recorded step association.'],'steps':steps}
  prov={'task_id':tid,'acquired_at_utc':datetime.now(timezone.utc).isoformat(),'archive':p.ARCHIVE_URL,'archive_bytes':p.ARCHIVE_BYTES,'dataset_commit':p.DATASET_COMMIT,'task_source_commit':p.TASK_COMMIT,'full_archive_checksum_verified_locally':False,'acquisition':'Bounded HTTP ranges; selected members verified with ZIP CRC32, length and SHA256.','files':metadata}
  (folder/'provenance.json').write_text(json.dumps(prov,indent=2)+'\n'); provenance.append(prov)
  print(f'Prepared {app}: {tid}; {len(steps)} steps; score {score}; {len(shots)} screenshots',flush=True)
 records=[]
 for slug,name,ids in GROUPS:
  group=[]; assets={}
  for tid in ids:
   task=copy.deepcopy(tasks[tid])
   for step in task['steps']:
    raw=step.get('screenshot')
    if raw:
     local=ROOT/raw if raw.startswith('platform/') else ROOT/'poc'/raw
     assert local.is_file(),local
     member=f'assets/{tid}/{local.name}'
     step['screenshot']=member; assets[member]=local
   group.append(task)
  manifest={'format':'cuautoreview','tasks':group}
  (OUT/f'{slug}.json').write_text(json.dumps(manifest,indent=2)+'\n')
  with ZipFile(OUT/f'{slug}.zip','w',ZIP_DEFLATED) as archive:
   archive.writestr('dataset.json',json.dumps(manifest))
   for member,local in assets.items(): archive.write(local,member)
  records.append({'slug':slug,'name':name,'task_ids':ids,'task_count':len(ids),'zip':f'platform/demo-data/{slug}.zip'})
 allids=[tid for _,_,ids in GROUPS for tid in ids]; assert len(allids)==len(set(allids))==8
 (OUT/'manifest.json').write_text(json.dumps({'datasets':records,'unique_tasks':8,'no_overlap':True},indent=2)+'\n')
 print('Prepared three disjoint datasets: 3 + 3 + 2 tasks',flush=True)
if __name__=='__main__': main()
