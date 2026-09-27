#!/usr/bin/env python3
"""A deliberately tiny stdio MCP server: read shared drafts, append proposals."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS proposals
        (id INTEGER PRIMARY KEY, task_id TEXT, episode_id TEXT, name TEXT, description TEXT,
        kind TEXT, target_label_id TEXT, base_version TEXT, status TEXT, evidence TEXT, created_at TEXT,
        UNIQUE(task_id, episode_id, name, description, kind, target_label_id))''')
    db.row_factory = sqlite3.Row
    return db


def snapshot(db):
    rows = []
    for row in db.execute('SELECT * FROM proposals ORDER BY id'):
        item = dict(row)
        item['id'] = f"p{item['id']:03d}"
        item['type'] = item.pop('kind')
        item['evidence_refs'] = json.loads(item.pop('evidence'))
        rows.append(item)
    return {'pool_version': f'v{len(rows)}', 'approved_release': '0.0.0',
            'approved_labels': [], 'proposals': rows}


def propose(db, task, args):
    allowed = {x for s in task['steps'] for x in s['evidence_refs']}
    for key in ('name','description','episode_id','type','target_label_id','base_version'):
        if not isinstance(args.get(key), str) or len(args[key]) > 700:
            raise ValueError(f'Invalid {key}')
    if not args['name'].strip() or args['type'] not in ('new','update'):
        raise ValueError('Provide a name and type exactly "new" or "update"; type is the edit operation, not a failure category')
    if not isinstance(args.get('evidence_refs'),list) or not args['evidence_refs'] or not set(args['evidence_refs']) <= allowed:
        raise ValueError('Cite existing evidence IDs')
    with db:
        db.execute('BEGIN IMMEDIATE')
        current = snapshot(db)
        if args['type']=='update' and args['target_label_id'] not in {p['id'] for p in current['proposals']}:
            raise ValueError('Update target not in current pool')
        if sum(p['task_id']==task['task_id'] for p in current['proposals']) >= 4:
            raise ValueError('Four proposal limit reached; reuse existing labels')
        status = 'draft' if args['base_version']==current['pool_version'] else 'stale_base'
        db.execute('''INSERT OR IGNORE INTO proposals
            (task_id,episode_id,name,description,kind,target_label_id,base_version,status,evidence,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (task['task_id'],args['episode_id'],args['name'],args['description'],args['type'],
             args['target_label_id'],args['base_version'],status,json.dumps(args['evidence_refs']),
             datetime.now(timezone.utc).isoformat()))
    fresh = snapshot(db)
    item = next(p for p in fresh['proposals'] if p['task_id']==task['task_id'] and
                p['episode_id']==args['episode_id'] and p['name']==args['name'] and
                p['description']==args['description'] and p['type']==args['type'] and
                p['target_label_id']==args['target_label_id'])
    return {'proposal': item, 'pool_version': fresh['pool_version'],
            'note': 'Draft only. Concurrent duplicates are reconciled after all reviews.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--task',required=True)
    a=p.parse_args();db=connect(a.db);task=json.load(open(a.task));calls=0
    properties={k:{'type':'string'} for k in ('name','description','episode_id','type','target_label_id','base_version')}
    properties['type']={'type':'string','enum':['new','update'],'description':'Edit operation: new label or update proposal. Never a mechanism/category name.'}
    properties['evidence_refs']={'type':'array','items':{'type':'string'}}
    tools=[{'name':'list_labels','description':'Read latest shared draft labels and pool_version. Call before analysis and again before final output.',
            'inputSchema':{'type':'object','properties':{},'additionalProperties':False},
            'annotations':{'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False}},
           {'name':'propose_label','description':'Append a new/updated draft label. Returns ID; never publishes or overwrites a release. Maximum four per task.',
            'inputSchema':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False},
            'annotations':{'readOnlyHint':False,'destructiveHint':False,'openWorldHint':False}}]
    for line in sys.stdin:
        request={}
        try:
            if len(line)>100000: raise ValueError('Request too large')
            request=json.loads(line)
            if 'id' not in request: continue
            method=request.get('method');params=request.get('params',{})
            if method=='initialize':
                result={'protocolVersion':params.get('protocolVersion','2024-11-05'),
                        'capabilities':{'tools':{}},'serverInfo':{'name':'cuautoreview-labels','version':'0.1.0'}}
            elif method=='tools/list': result={'tools':tools}
            elif method=='ping': result={}
            elif method=='tools/call':
                calls+=1
                if calls>8: raise ValueError('Helper call limit reached; finish with available evidence')
                name=params['name']
                value=snapshot(db) if name=='list_labels' else propose(db,task,params.get('arguments',{})) if name=='propose_label' else None
                if value is None: raise ValueError('Unknown tool')
                result={'content':[{'type':'text','text':json.dumps(value)}],'isError':False}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
            response={'jsonrpc':'2.0','id':request['id'],'result':result}
        except Exception as exc:
            response={'jsonrpc':'2.0','id':request.get('id'),'result':{'content':[{'type':'text','text':str(exc)}],'isError':True}}
        print(json.dumps(response),flush=True)

if __name__=='__main__': main()
