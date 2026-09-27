#!/usr/bin/env python3
"""Exercise the real local stack without model calls; creates clearly named acceptance data."""
from __future__ import annotations
import copy
import datetime
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASE = os.getenv('CUAUTOREVIEW_URL', 'http://127.0.0.1:8000')
RESULTS = []

class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self, method, path, body=None, expected=200):
        request=urllib.request.Request(BASE+'/api'+path, data=json.dumps(body).encode() if body is not None else None,
            method=method, headers={'Content-Type':'application/json','Origin':BASE})
        try:
            response=self.opener.open(request, timeout=45)
        except urllib.error.HTTPError as exc:
            response=exc
        raw=response.read()
        assert response.status==expected, (method,path,response.status,raw[:600].decode(errors='replace'))
        if raw and 'json' in response.headers.get('Content-Type',''):
            return json.loads(raw)
        return raw

def ok(name):
    RESULTS.append({'check':name,'status':'passed'})
    print('PASS '+name, flush=True)

def main():
    admin=Client()
    account_path=ROOT/'platform/.local/test-account.json'
    if account_path.exists():
        credentials=json.loads(account_path.read_text())
        me=admin.call('POST','/auth/login', {'email':credentials['email'],'password':credentials['password']})
    else:
        credentials={'name':'Local Reviewer','email':'local-reviewer@cuautoreview.test','password':secrets.token_urlsafe(22)}
        me=admin.call('POST','/auth/signup',credentials)
        account_path.write_text(json.dumps(credentials,indent=2)+'\n')
        account_path.chmod(0o600)
    assert me['role']=='admin'
    admin.call('GET','/auth/me')
    ok('Signup/login and first administrator')
    suffix=str(time.time_ns())[-10:]
    viewer=Client()
    person=viewer.call('POST','/auth/signup',{'name':'Acceptance viewer','email':f'acceptance-{suffix}@example.test','password':secrets.token_urlsafe(20)})
    assert person['role']=='viewer'
    presets=admin.call('GET','/presets')['items']
    preset=next(p for p in presets if p['backend']=='saved_replay')
    assert admin.call('GET','/providers')['default_backend']=='saved_replay'
    source=json.loads((ROOT/'poc/runs/latest/run.json').read_text())['tasks']
    dataset=admin.call('POST','/datasets',{'name':'Acceptance '+suffix,'description':'Local verification fixtures. No new inference.'})
    imported=admin.call('POST',f"/datasets/{dataset['id']}/import",{'format':'cuautoreview','tasks':source})
    assert imported['created']==5
    repeated=admin.call('POST',f"/datasets/{dataset['id']}/import",{'format':'cuautoreview','tasks':source})
    assert repeated['unchanged']==5
    viewer.call('GET',f"/datasets/{dataset['id']}/sync-preview",expected=403)
    ok('Import five recorded tasks, repeated import unchanged, source access scoped')
    batch=admin.call('POST','/batches',{'name':'Acceptance replay '+suffix,'dataset_id':dataset['id'],'preset_id':preset['id'],'mode':'appendable'})
    bid=batch['id']; taskid=source[0]['task_id']; path=f'/batches/{bid}/tasks/{taskid}'
    viewer.call('GET',f'/batches/{bid}',expected=403)
    team=admin.call('POST','/teams',{'name':'Acceptance team '+suffix})
    admin.call('POST',f"/teams/{team['id']}/members",{'user_id':person['id']})
    grant=admin.call('POST',f'/batches/{bid}/grants',{'team_id':team['id'],'role':'reviewer'})
    viewer.call('GET',path)
    detail=admin.call('GET',path)
    image=next((s['screenshot_url'] for s in detail['steps'] if s.get('screenshot_url')),None)
    assert image
    viewer.call('GET',image.removeprefix('/api'))
    viewer.call('POST',path+'/feedback',{'text':'Acceptance check: preserve evidence uncertainty.','step_id':str(detail['steps'][0]['step_id'])})
    assert viewer.call('GET',path+'/feedback')
    viewer.call('GET',path+'/export?format=yaml')
    admin.call('DELETE',f"/teams/{team['id']}/members/{person['id']}",expected=204)
    viewer.call('GET',path,expected=403)
    viewer.call('GET',image.removeprefix('/api'),expected=403)
    viewer.call('GET',path+'/export?format=yaml',expected=403)
    ok('Team grant, reviewer feedback/export and immediate revocation on evidence')
    for broken in ('/artifacts/unknown/unrecorded.png','/artifacts/unknown/%2e%2e/secret'):
        admin.call('GET',broken,expected=404)
    ok('Unrecorded artifact and path traversal rejected')
    started=admin.call('POST',f'/batches/{bid}/start',{})
    assert started['jobs_added']==5, started
    deadline=time.monotonic()+55
    while time.monotonic()<deadline:
        jobs=[j for j in admin.call('GET','/jobs')['items'] if j['batch_id']==bid]
        if len(jobs)==5 and all(j['status']=='completed' for j in jobs): break
        if any(j['status']=='failed' for j in jobs): raise AssertionError([(j['status'],j.get('error')) for j in jobs])
        time.sleep(1)
    assert len(jobs)==5 and all(j['status']=='completed' for j in jobs), jobs
    assert all(j['cost_usd']==0 and j['usage']['kind']=='saved_replay' for j in jobs)
    assert {j['review_kind'] for j in jobs}=={'failure_analysis','pass_recovery'}
    finished=admin.call('GET',path)
    history=finished['review_history']
    assert len(history)>=1 and history[-1]['artifact_sha256']
    review_key=history[-1]['artifact_key']; assert review_key
    reviewed_artifact=next(a for a in finished['artifacts'] if a.get('object_key')==review_key)
    stored=admin.call('GET',f"/artifacts/{taskid}/{reviewed_artifact['relative_path']}?member_id={finished['member_id']}")
    assert b'review_kind' in stored
    ok('Real RabbitMQ delivery, five Celery reviews, both routes, immutable S3 YAML and zero new inference cost')
    rerun=admin.call('POST',f'/batches/{bid}/start',{})
    assert rerun['jobs_added']==0
    ok('Repeated start preserves completed results')
    revision=copy.deepcopy(source[0]); revision['revision_note']='Acceptance revised metadata'
    admin.call('POST',f"/datasets/{dataset['id']}/import",{'format':'cuautoreview','tasks':[revision]})
    sync=admin.call('POST',f'/batches/{bid}/sync',{})
    assert sync['added']==1, sync
    again=admin.call('POST',f'/batches/{bid}/sync',{})
    assert again['added']==0, again
    members=admin.call('GET',f'/batches/{bid}/tasks')['items']
    same=[m for m in members if m['task_id']==taskid]
    assert len(same)==2 and len({m['revision_id'] for m in same})==2
    for member in same:
        selected=admin.call('GET',path+'?member_id='+member['member_id'])
        assert selected['member_id']==member['member_id']
    ok('Appendable sync idempotency and immutable source revision selection')
    fixed=admin.call('POST','/batches',{'name':'Fixed acceptance '+suffix,'dataset_id':dataset['id'],'preset_id':preset['id'],'mode':'fixed','task_ids':[taskid]})
    admin.call('POST',f"/batches/{fixed['id']}/sync",{},expected=409)
    ok('Fixed batch rejects sync')
    revision_preset=admin.call('POST','/presets',{'name':preset['name'],'backend':'saved_replay','budget_usd':0,'configuration':{'acceptance':suffix}})
    assert revision_preset['revision']>=2
    after=admin.call('GET',f'/batches/{bid}')
    assert after['preset_revision_id']==batch['preset_revision_id']
    ok('Preset revision does not change existing batch configuration')
    proposal=admin.call('POST','/taxonomy/proposals',{'name':'Acceptance evidence gap '+suffix,'description':'An action has no visible confirmation; review remains uncertain.','kind':'label'})
    candidate=admin.call('POST','/taxonomy/consolidate',{})
    admin.call('POST',f"/taxonomy/proposals/{proposal['id']}/feedback",{'text':'Retain evidence uncertainty; do not equate missing evidence with model failure.'})
    admin.call('POST',f"/taxonomy/candidates/{candidate['id']}/approve",{'expected_hash':candidate['content_hash'],'version':candidate['version']},expected=409)
    rejected=admin.call('POST','/taxonomy/consolidate',{})
    admin.call('POST',f"/taxonomy/candidates/{rejected['id']}/reject",{'reason':'Acceptance rejection check'})
    admin.call('POST',f"/taxonomy/candidates/{rejected['id']}/approve",{'expected_hash':rejected['content_hash'],'version':rejected['version']},expected=409)
    ok('Stale taxonomy feedback and rejected candidate both block approval')
    admin.call('PATCH',f"/users/{person['id']}",{'active':False})
    viewer.call('GET','/auth/me',expected=401)
    ok('Deactivated account loses existing session access')
    summary={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'base_url':BASE,
        'provider_calls':0,'checks':RESULTS,'batch_id':bid,'job_ids':[j['id'] for j in jobs],
        'note':'Functional saved-replay checks, not model quality, scale or production certification.'}
    (ROOT/'platform/verification.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('Saved platform/verification.json')

if __name__=='__main__': main()
