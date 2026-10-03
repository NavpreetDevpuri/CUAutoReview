#!/usr/bin/env python3
"""Single-batch, bounded Codex review experiment. No platform services needed."""
import argparse
import concurrent.futures
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import jsonschema
import yaml
from label_tools import connect, snapshot
from schemas import REVIEW, REVIEW_V1, REVIEW_V2, REVIEW_SCHEMA_VERSION, DEDUP

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent
PRICES={'gpt-6-luna':(.10,.01,.50),'gpt-6-sol':(2.0,.20,10.0),'gpt-5.6-luna':(.20,.02,1.20),'gpt-5.6-sol':(4.0,.40,20.0)}
CREDITS={'gpt-6-luna':(2.5,.25,12.5),'gpt-6-sol':(50,5,250),'gpt-5.6-luna':(5,.5,30),'gpt-5.6-sol':(100,10,500)}
PRICE_SOURCE='https://developers.openai.com/api/docs/pricing'
DISABLED=('shell_tool','unified_exec','apps','plugins','hooks','browser_use','browser_use_external',
          'computer_use','image_generation','multi_agent','memories','shell_snapshot','skill_search',
          'skill_mcp_dependency_install','sleep_tool','goals','view_image')


# Running model CLI process groups; Ctrl-C must stop them because they run in their own sessions.
CHILDREN=set();CHILDREN_LOCK=threading.Lock()


def now(): return datetime.now(timezone.utc).isoformat()
def portable(text):
    """Record repo- and home-relative paths instead of host-specific absolute ones."""
    return str(text).replace(str(REPO),'.').replace(str(Path.home()),'~')
def stop_process_group(process,grace=5):
    try: os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError: return
    try: process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait()
def terminate_children():
    with CHILDREN_LOCK: processes=list(CHILDREN)
    for process in processes: stop_process_group(process)
def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f'.{uuid.uuid4().hex}.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n');tmp.replace(path)
def write_yaml(path,value): path.write_text(yaml.safe_dump(value,sort_keys=False,allow_unicode=True))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def costs(usage,model):
    prices=PRICES.get(model)
    total=usage.get('input_tokens');cached=usage.get('cached_input_tokens');out=usage.get('output_tokens')
    amount=None if prices is None or None in (total,cached,out) else ((total-cached)*prices[0]+cached*prices[1]+out*prices[2])/1e6
    rates=CREDITS.get(model)
    credits=None if rates is None or None in (total,cached,out) else ((total-cached)*rates[0]+cached*rates[1]+out*rates[2])/1e6
    return {**usage,'estimated_usd':amount,'billing_basis':'API-equivalent estimate, not ChatGPT invoice',
            'estimated_credits':credits,
            'pricing_note':'ChatGPT charge/included allowance unavailable. API comparison excludes unreported cache-write charges; Standard short-context rates checked 2026-09-26.',
            'pricing_source':PRICE_SOURCE,'credit_source':'https://learn.chatgpt.com/docs/pricing#token-rates','model':model}


def codex_command(model,schema,last,cwd,task_file=None,db=None,images=(),reasoning='low'):
    cmd=['codex','--no-daemon','-a','never','exec','--ignore-user-config','--ephemeral',
         '--skip-git-repo-check','-s','read-only','-C',str(cwd),'-m',model,'--json','--color','never',
         '--output-schema',str(schema),'-o',str(last)]
    config={'model_reasoning_effort':reasoning,'model_verbosity':'low','web_search':'disabled',
            'project_doc_max_bytes':0,'model_instructions_file':str(ROOT/'prompts/system.txt'),
            'features.skip_host_skill_discovery':True}
    config.update({f'features.{name}':False for name in DISABLED})
    if db:
        config.update({'mcp_servers.labels.command':sys.executable,
             'mcp_servers.labels.args':[str(ROOT/'label_tools.py'),'--db',str(db),'--task',str(task_file)],
             'mcp_servers.labels.required':True,'mcp_servers.labels.startup_timeout_sec':15})
    for key,value in config.items(): cmd+=['-c',f'{key}={json.dumps(value)}']
    for path in images: cmd+=['-i',str(path)]
    return cmd+['-']


def invoke(model,prompt,schema,outdir,timeout,task_file=None,db=None,images=(),reasoning='low'):
    outdir.mkdir(parents=True,exist_ok=True)
    write_json(outdir/'schema.json',schema);(outdir/'prompt.txt').write_text(prompt)
    work=outdir/'workspace';work.mkdir(exist_ok=True)
    command=codex_command(model,outdir/'schema.json',outdir/'response.json',work,task_file,db,images,reasoning)
    write_json(outdir/'command.json',[portable(arg) for arg in command])
    env=os.environ.copy()
    # Existing Codex auth remains in its normal location; never copy or log credentials.
    started=time.monotonic();error=None
    with (outdir/'agent.jsonl').open('w') as stdout,(outdir/'stderr.log').open('w') as stderr:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,text=True,
                                 env=env,start_new_session=True)
        with CHILDREN_LOCK: CHILDREN.add(process)
        try: process.communicate(prompt,timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_process_group(process)
            error=f'Wall-clock limit {timeout}s reached; no automatic retry.'
        except KeyboardInterrupt:
            stop_process_group(process);raise
        finally:
            with CHILDREN_LOCK: CHILDREN.discard(process)
    for log in ('agent.jsonl','stderr.log'):
        (outdir/log).write_text(portable((outdir/log).read_text()))
    events=[];usage={'input_tokens':None,'cached_input_tokens':None,'output_tokens':None}
    for line in (outdir/'agent.jsonl').read_text().splitlines():
        try: event=json.loads(line)
        except json.JSONDecodeError: continue
        events.append(event)
        if event.get('type')=='turn.completed' and 'usage' in event:
            usage={k:event['usage'].get(k) for k in usage}
        if event.get('type') in ('error','turn.failed'):
            error=json.dumps(event.get('error',event.get('message',event)))
    if process.returncode: error=error or f'Codex exited {process.returncode}; see stderr.log'
    response=None
    if not error:
        try:
            response=json.loads((outdir/'response.json').read_text());jsonschema.validate(response,schema)
        except Exception as exc: error=f'Invalid structured response: {exc}'
    trace=[{'type':'prompt','text':prompt}]
    trace += [{'type':e.get('type','event'),'text':json.dumps(e,ensure_ascii=False)} for e in events]
    return response,trace,costs(usage,model),error,round(time.monotonic()-started,2)


def validate_review(review,task,pool):
    if 'schema_version' not in review:
        version=1
        schema=REVIEW_V1
    elif review['schema_version']==REVIEW_SCHEMA_VERSION:
        version=2
        schema=REVIEW_V2
    else:
        raise ValueError(f'Unsupported review schema version: {review["schema_version"]!r}')
    jsonschema.validate(review,schema)
    ids=[s['step_id'] for s in task['steps']]
    step_order={step_id:index for index,step_id in enumerate(ids)}
    if [s['step_id'] for s in review['steps']] != ids: raise ValueError('Missing, duplicate or reordered step annotations')
    expected='failure_analysis' if task['outcome']=='failed' else 'pass_recovery'
    if review['review_kind']!=expected: raise ValueError('Review route does not match outcome')
    evidence={x for s in task['steps'] for x in s['evidence_refs']}
    label_ids={p['id'] for p in pool['proposals']}
    episodes=review['episodes'];episode_ids=[e['episode_id'] for e in episodes]
    if len(set(episode_ids))!=len(episode_ids): raise ValueError('Duplicate episode ID')
    reject_duplicate_refs(review)
    for step in review['steps']:
        if not set(step['evidence_refs']) <= evidence or not set(step['episode_refs']) <= set(episode_ids):
            raise ValueError('Invalid step evidence/episode reference')
        if step['review_status']=='reviewed' and not step['evidence_refs']:
            raise ValueError(f"Reviewed step {step['step_id']} cites no evidence; use insufficient_evidence")
    for ep in episodes:
        if not set(ep['onset_step_ids'])<=set(ids) or not ep['onset_step_ids']: raise ValueError('Invalid onset')
        earliest_onset=min(step_order[step_id] for step_id in ep['onset_step_ids'])
        refs=ep['evidence_refs']+ep['recovery']['evidence_refs']
        if not set(refs)<=evidence or not ep['evidence_refs']: raise ValueError('Invalid episode evidence')
        if not set(ep['recovery']['step_ids'])<=set(ids): raise ValueError('Invalid recovery steps')
        if any(step_order[step_id]<earliest_onset for step_id in ep['recovery']['step_ids']):
            raise ValueError('Recovery step precedes episode onset')
        if ep['recovery']['status'] in ('recovered','partial') and (not ep['recovery']['step_ids'] or not ep['recovery']['evidence_refs']):
            raise ValueError('Recovery needs a step and evidence')
        if ep['recovery']['status'] in ('not_assessed','none_observed','unknown') and ep['recovery']['step_ids']:
            raise ValueError(f"Recovery status {ep['recovery']['status']} cannot tag recovery steps")
        if ep['label_id'] and ep['label_id'] not in label_ids: raise ValueError('Unknown label proposal ID')
        if task['outcome']=='passed' and ep['outcome_contribution']!='not_applicable': raise ValueError('Passed contribution must be not_applicable')
        if task['outcome']=='failed' and ep['outcome_contribution']=='not_applicable': raise ValueError('Failed contribution cannot be not_applicable')
    if version==2:
        validate_review_v2_links(review,step_order)
    if review['result']=='no_issue_observed' and (episodes or any(s['review_status']!='reviewed' for s in review['steps'])):
        raise ValueError('No-issue result requires reviewed coverage and no episodes')
    if review['result']=='issues_observed' and not episodes:
        raise ValueError('Issues-observed result requires at least one episode')


def reject_duplicate_refs(review):
    """Reject repeated IDs in any reference list (both schema versions)."""
    def reject_duplicates(values,field):
        if len(values)!=len(set(values)):
            raise ValueError(f'Duplicate reference in {field}')

    for step in review['steps']:
        reject_duplicates(step['evidence_refs'],f"step {step['step_id']} evidence_refs")
        reject_duplicates(step['episode_refs'],f"step {step['step_id']} episode_refs")
    for ep in review['episodes']:
        reject_duplicates(ep['onset_step_ids'],f"episode {ep['episode_id']} onset_step_ids")
        reject_duplicates(ep['recovery']['step_ids'],f"episode {ep['episode_id']} recovery.step_ids")
        reject_duplicates(ep['evidence_refs'],f"episode {ep['episode_id']} evidence_refs")
        reject_duplicates(ep['recovery']['evidence_refs'],f"episode {ep['episode_id']} recovery.evidence_refs")


def validate_review_v2_links(review,step_order):
    """Validate problem numbering and required onset/recovery links for schema v2."""
    links_by_step={step_id:set() for step_id in step_order}
    episodes=review['episodes']
    problem_numbers=[ep['problem_number'] for ep in episodes]
    if len(problem_numbers)!=len(set(problem_numbers)):
        raise ValueError('Duplicate problem_number')

    for ep in episodes:
        onset_ids=ep['onset_step_ids']
        recovery_ids=ep['recovery']['step_ids']
        first_observed=min(onset_ids,key=step_order.__getitem__)
        if ep['first_observed_step_id'] not in step_order:
            raise ValueError(f"Unknown first_observed_step_id for {ep['episode_id']}")
        if ep['first_observed_step_id']!=first_observed:
            raise ValueError(f"first_observed_step_id does not match earliest onset for {ep['episode_id']}")

        for step_id in set(onset_ids)|set(recovery_ids):
            links_by_step[step_id].add(ep['episode_id'])

    ordered=sorted(enumerate(episodes),key=lambda pair:(step_order[pair[1]['first_observed_step_id']],pair[0]))
    if [ep['problem_number'] for _,ep in ordered]!=list(range(1,len(episodes)+1)):
        raise ValueError('Problem numbers must be contiguous in first-observed order')

    for step in review['steps']:
        expected=links_by_step[step['step_id']]
        actual=set(step['episode_refs'])
        # Extra known IDs are explicit related/context links, not onset/recovery tags.
        if not expected<=actual:
            raise ValueError(f"Step episode_refs is missing onset/recovery tags at step {step['step_id']}")


def validate_dedup(result,pool):
    jsonschema.validate(result,DEDUP)
    original={p['id'] for p in pool['proposals']}
    mapped=[m['proposal_id'] for m in result['mappings']]
    labels=[l['id'] for l in result['labels']]
    if set(mapped)!=original or len(mapped)!=len(original): raise ValueError('Every proposal must map exactly once')
    if len(set(labels))!=len(labels): raise ValueError('Duplicate canonical label ID')
    if any(m['canonical_label_id'] not in labels for m in result['mappings']): raise ValueError('Unknown canonical label')
    used_labels={m['canonical_label_id'] for m in result['mappings']}
    if set(labels)-used_labels: raise ValueError('Every canonical label must map at least one proposal')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',type=Path,default=ROOT/'data/batch.json')
    p.add_argument('--model',default='gpt-5.6-sol');p.add_argument('--dedup-model',default='gpt-5.6-sol')
    p.add_argument('--reasoning',choices=('low','medium','high'),default='medium')
    p.add_argument('--limit',type=int,default=5);p.add_argument('--parallel',type=int,default=3)
    p.add_argument('--timeout',type=int,default=180);p.add_argument('--max-images',type=int,default=3)
    p.add_argument('--dry-run',action='store_true',help='Validate inputs and estimate scope without model calls')
    args=p.parse_args()
    if not 1<=args.limit<=10 or not 1<=args.parallel<=5 or not 30<=args.timeout<=300 or not 0<=args.max_images<=5:
        p.error('Bounds: 1-10 tasks, 1-5 parallel, 30-300 seconds, 0-5 images/task')
    batch=json.loads(args.batch.read_text());tasks=copy.deepcopy(batch['tasks'][:args.limit])
    if len({t['task_id'] for t in tasks})!=len(tasks): p.error('Distinct tasks required')
    if any(t['outcome'] not in ('failed','passed') for t in tasks): p.error('Resolve unknown evaluator outcomes before review')
    if args.dry_run:
        print(json.dumps({'tasks':len(tasks),'review_model':args.model,'dedup_model':args.dedup_model,
            'max_sessions':len(tasks)+1,'parallel':args.parallel,'max_images_per_task':args.max_images,
            'max_seconds_per_session':args.timeout,'reasoning_effort':args.reasoning,'automatic_retries':0,'hosted_inference':True},indent=2));return
    run_id=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:5]
    run_dir=ROOT/'runs'/run_id;run_dir.mkdir(parents=True)
    # runs/latest is a retained fixture for the viewer and platform seed; only completed runs replace it.
    latest=ROOT/'runs/latest'
    db_path=run_dir/'labels.sqlite';db=connect(db_path);db.close()
    state={'run_id':run_id,'status':'running','started_at':now(),'finished_at':None,'model':args.model,
        'review_schema_version':REVIEW_SCHEMA_VERSION,
        'dedup_model':args.dedup_model,'reasoning_effort':args.reasoning,'batch_id':batch['batch_id'],'notes':batch.get('notes',[]),
        'limits':{'tasks':len(tasks),'parallel':args.parallel,'seconds_per_session':args.timeout,
          'max_images_per_task':args.max_images,'max_helper_calls_per_task':8,'max_proposals_per_task':4,
          'max_sessions':len(tasks)+1,'automatic_retries':0,'hard_dollar_cap':False},
        'prompt_sha256':{x.name:digest(x) for x in (ROOT/'prompts').glob('*.txt')},
        'tasks':tasks,'taxonomy':{'labels':[],'proposals':[],'status':'draft'},'usage':{},
        'notice':'POC only: single batch; full collaborative platform is not implemented.'}
    for t in tasks: t.update(status='queued',review=None,agent_trace=[],error=None)
    lock=threading.Lock()
    def save():
        conn=connect(db_path);pool=snapshot(conn);conn.close()
        state['taxonomy']['proposals']=pool['proposals'];state['taxonomy']['pool_version']=pool['pool_version']
        usages=[t['usage'] for t in tasks if t.get('usage')]
        if state.get('dedup_usage'): usages.append(state['dedup_usage'])
        sums={k:sum(u[k] for u in usages if u.get(k) is not None) for k in ('input_tokens','cached_input_tokens','output_tokens')}
        known=[u['estimated_usd'] for u in usages if u.get('estimated_usd') is not None]
        state['usage']={**sums,'estimated_usd':round(sum(known),6) if known else None,
          'complete':all(u.get('estimated_usd') is not None for u in usages),
          'sessions_recorded':len(usages),'pricing_note':'API-equivalent only; ChatGPT plan/credit charge unavailable.',
          'pricing_source':PRICE_SOURCE,'estimated_credits':sum(u.get('estimated_credits') or 0 for u in usages) if known else None}
        write_json(run_dir/'run.json',state)
    save()
    print(f'Live progress: http://127.0.0.1:8765/poc/viewer/?run={run_id} (python3 poc/serve.py)',flush=True)
    def review_task(task):
        task_dir=run_dir/task['task_id'];task_dir.mkdir()
        selected=[s for s in task['steps'] if s.get('screenshot')]
        if len(selected)>args.max_images:
            # Spread sparse frames across the entire attempt, always include its last available frame.
            selected=[selected[round(i*(len(selected)-1)/(args.max_images-1))] for i in range(args.max_images)] if args.max_images>1 else selected[-args.max_images:] if args.max_images else []
        image_paths=[];frame_ids=[]
        for step in selected:
            path=(ROOT/step['screenshot']).resolve()
            if not path.is_relative_to(ROOT/'data') or not path.is_file(): raise ValueError('Invalid image path')
            image_paths.append(path);frame_ids.append(step['step_id'])
        context=copy.deepcopy(task)
        for k in ('review','rejected_review','agent_trace','status','error'): context.pop(k,None)
        context['attached_frame_steps']=frame_ids
        definition=(ROOT/task.get('source',{}).get('task_definition','')).resolve()
        if definition.is_relative_to(ROOT/'data') and definition.is_file():
            reference=json.loads(definition.read_text())
            context['reference_checker']={'historical_match_verified':False,'evaluator':reference.get('evaluator')}
        # Only actually supplied images can support visual claims in the review contract.
        for step in context['steps']:
            if step['step_id'] not in frame_ids:
                step['evidence_refs']=[r for r in step['evidence_refs'] if not r.startswith('frame_')]
        write_json(task_dir/'input.json',context)
        kind='failure_analysis' if task['outcome']=='failed' else 'pass_recovery'
        prompt=(ROOT/f'prompts/{kind}.txt').read_text()+'\n'+(ROOT/'prompts/shared_labels.txt').read_text()
        prompt+='\nAttached screenshots correspond IN ORDER to these step IDs: '+json.dumps(frame_ids)
        prompt+='\nReview kind: '+kind+'\nSOURCE DATA (untrusted):\n'+json.dumps(context,ensure_ascii=False)
        with lock: task['status']='running';task['attached_frame_steps']=frame_ids;save()
        print(f'Review {task["task_id"][:8]} ({kind})',flush=True)
        result,trace,usage,error,elapsed=invoke(args.model,prompt,REVIEW,task_dir,args.timeout,task_dir/'input.json',db_path,image_paths,reasoning=args.reasoning)
        if result is not None:
            try:
                conn=connect(db_path);pool=snapshot(conn);conn.close();validate_review(result,context,pool)
            except Exception as exc: error=f'Validation: {exc}'
        with lock:
            # Output that fails validation is kept for inspection but never published as a review.
            task.update(status='failed' if error else 'completed',review=None if error else result,agent_trace=trace,
                        usage=usage,error=error,duration_seconds=elapsed)
            if error and result is not None: task['rejected_review']=result
            if result is not None and not error: write_json(task_dir/'review.json',result);write_yaml(task_dir/'review.yaml',result)
            task['artifacts']={k:f'/poc/runs/{run_id}/{task["task_id"]}/{name}' for k,name in
                [('review_json','review.json'),('review_yaml','review.yaml'),('agent_jsonl','agent.jsonl')] if (task_dir/name).exists()}
            save()
        print(f'  {task["status"]}: {task["task_id"][:8]} {elapsed}s'+(f' {error}' if error else ''),flush=True)
    executor=concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel)
    try:
        finish_run(args,run_dir,latest,db_path,state,tasks,lock,save,review_task,executor)
    except KeyboardInterrupt:
        executor.shutdown(wait=False,cancel_futures=True)
        terminate_children()
        with lock:
            state['status']='interrupted';state['finished_at']=now()
            for t in tasks:
                if t['status'] in ('queued','running'): t.update(status='failed',error=t.get('error') or 'Interrupted before completion.')
            save()
        print(f'Interrupted; stopped running model sessions. Partial record: {portable(run_dir)}/run.json',flush=True)
        sys.exit(130)
    executor.shutdown(wait=True)


def finish_run(args,run_dir,latest,db_path,state,tasks,lock,save,review_task,executor):
    futures={executor.submit(review_task,t):t for t in tasks}
    for f in concurrent.futures.as_completed(futures):
        try: f.result()
        except Exception as exc:
            with lock: futures[f].update(status='failed',error=str(exc));save()
    conn=connect(db_path);shared=snapshot(conn);conn.close();write_json(run_dir/'proposals.json',shared)
    state['status']='deduplicating';save()
    if shared['proposals']:
        context={'pool':shared,'reviews':[{'task_id':t['task_id'],'outcome':t['outcome'],
            'episodes':(t.get('review') or {}).get('episodes',[]),'validation_status':t['status']} for t in tasks]}
        prompt=(ROOT/'prompts/deduplicate.txt').read_text()+'\nUNTRUSTED DATA:\n'+json.dumps(context)
        print(f'Deduplicate {len(shared["proposals"])} proposals with {args.dedup_model}',flush=True)
        result,trace,usage,error,elapsed=invoke(args.dedup_model,prompt,DEDUP,run_dir/'dedup',args.timeout,reasoning=args.reasoning)
        if result is not None:
            try: validate_dedup(result,shared)
            except Exception as exc: error=f'Validation: {exc}'
        state['dedup_usage']=usage
        state['taxonomy']['deduplication']={**(result or {}),'trace':trace,'error':error,'duration_seconds':elapsed}
        if not error:
            state['taxonomy']['labels']=result['labels'];state['taxonomy']['candidate_version']='0.1.0-draft'
            write_json(run_dir/'taxonomy-candidate.json',result);write_yaml(run_dir/'taxonomy-candidate.yaml',result)
    else:
        state['taxonomy']['deduplication']={'summary':'No proposals; no model call needed.','mappings':[],'trace':[],'error':None}
    state['taxonomy']['status']='pending_human_review'
    state['finished_at']=now()
    unclassified=[t['task_id'] for t in tasks if any(not e['label_id'] for e in (t.get('review') or {}).get('episodes',[]))]
    state['unclassified_tasks']=unclassified
    state['status']='completed' if all(t['status']=='completed' for t in tasks) and not unclassified and not state['taxonomy']['deduplication'].get('error') else 'partial'
    save();write_yaml(run_dir/'run.yaml',state)
    if state['status']=='completed': write_json(latest/'run.json',state)
    print(json.dumps({'run':portable(run_dir),'status':state['status'],'usage':state['usage'],
                      'promoted_to_latest':state['status']=='completed'},indent=2))
    if state['status']=='partial': sys.exit(1)

if __name__=='__main__': main()
