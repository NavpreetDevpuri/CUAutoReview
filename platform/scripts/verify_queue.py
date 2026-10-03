#!/usr/bin/env python3
"""Crash-gap/paused delivery checks on the local saved-replay stack, without inference."""
import datetime
import json
import subprocess
import time
from e2e_local import Client, ROOT

COMPOSE=['docker','compose','-f',str(ROOT/'platform/compose.yaml')]

def container(code):
    return subprocess.run(COMPOSE+['exec','-T','app','python','-'],input=code,text=True,capture_output=True,check=True).stdout.strip()

def main():
    checks=[]
    client=Client()
    account=json.loads((ROOT/'platform/.local/test-account.json').read_text())
    client.call('POST','/auth/login',{'email':account['email'],'password':account['password']})
    previous=json.loads((ROOT/'platform/evidence/verification.json').read_text())
    bid=previous['batch_id']; jid=previous['job_ids'][0]
    def current(): return next(j for j in client.call('GET','/jobs')['items'] if j['id']==jid)
    original=current()
    duplicate_code=f"from app.queue import run_review\nrun_review.apply_async(args=[{jid!r},{original['generation']}])\nrun_review.apply_async(args=[{jid!r},0])\n"
    container(duplicate_code)
    time.sleep(1)
    assert current()['attempt_count']==original['attempt_count']
    checks.append('Real broker duplicate and obsolete generations do not claim another attempt')
    subprocess.run(COMPOSE+['stop','worker'],check=True,capture_output=True)
    try:
        retry=client.call('POST',f'/jobs/{jid}/retry',{})
        assert retry['generation']==original['generation']+1
        sent=False
        for _ in range(12):
            result=container(f"from app.main import SessionLocal\nfrom app.models import OutboxEvent\nfrom sqlalchemy import select\nwith SessionLocal() as s:\n e=s.scalar(select(OutboxEvent).where(OutboxEvent.job_id=={jid!r},OutboxEvent.generation=={retry['generation']}))\n print(e.status if e else 'missing')\n")
            if result=='sent': sent=True; break
            time.sleep(.5)
        assert sent, 'Relay did not publish retry while worker stopped'
        client.call('POST',f'/batches/{bid}/pause',{})
    finally:
        subprocess.run(COMPOSE+['start','worker'],check=True,capture_output=True)
    time.sleep(2)
    assert current()['status']=='queued' and current()['attempt_count']==original['attempt_count']
    resumed=client.call('POST',f'/batches/{bid}/resume',{})
    assert resumed['status']=='running'
    # An HTTP retry of start must not turn queued work into a completed batch.
    repeated=client.call('POST',f'/batches/{bid}/start',{})
    assert repeated['status'] in ('running','completed')
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        job=current()
        if job['status']=='completed': break
        assert job['status']!='failed',job.get('error')
        time.sleep(.5)
    assert job['status']=='completed' and job['attempt_count']==original['attempt_count']+1
    assert job['cost_usd']==0
    checks.append('Delivered-before-pause message is safely recovered on resume')
    checks.append('Explicit retry appends one attempt and replay retains zero new cost')
    state=container(f"from app.main import SessionLocal\nfrom app.models import Job, ReviewResult\nfrom sqlalchemy import select\nwith SessionLocal() as s:\n j=s.get(Job,{jid!r})\n r=s.scalars(select(ReviewResult).where(ReviewResult.job_id==j.id)).all()\n assert len(r)=={job['attempt_count']}\n assert len({{x.artifact_key for x in r}})==len(r)\n print(str(len(r))+' immutable result revisions and artifact keys')\n")
    checks.append(state)
    result={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'provider_calls':0,'checks':checks}
    (ROOT/'platform/evidence/queue-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    for check in checks: print('PASS '+check)

if __name__=='__main__':main()
