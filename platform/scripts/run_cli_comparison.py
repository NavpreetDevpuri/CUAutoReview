#!/usr/bin/env python3
"""One-time no-inference preflight and one Gemini + one Codex comparison.

Provider credentials come from platform/.env, or the --provider-env file, and
only selected keys are passed to Docker Compose as process environment. Keys
are never printed or persisted. The default dataset/task IDs identify the
recorded local experiment; fresh workspaces must pass their own --dataset-id
and --task-id. No comparison inference runs without --run.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT / 'platform/.env'
ACCOUNT_FILE = PROJECT / 'platform/.local/test-account.json'
REPORT_DIR = PROJECT / 'platform/docs/evidence/live-runs'
BASE = os.getenv('CUAUTOREVIEW_URL', 'http://127.0.0.1:8000')
DATASET_ID = '7878c36d-88c6-44b8-9114-894c6e86b948'
TASK_ID = '06fe7178-4491-4589-810f-2e2bc9502122'
COMPOSE = ['docker', 'compose', '-f', 'platform/compose.yaml']


def parse_provider_keys(path: Path) -> dict[str, str]:
    wanted = {'OPENAI_API_KEY', 'CODEX_API_KEY', 'GEMINI_API_KEY'}
    values: dict[str, str] = {}
    pattern = re.compile(r'^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$')
    for raw in path.read_text(encoding='utf-8').splitlines():
        match = pattern.match(raw)
        if not match or match.group(1) not in wanted:
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        else:
            value = value.split('#', 1)[0].strip()
        if value:
            values[key] = value
    return values


def run(command: list[str], *, env: dict[str, str] | None = None, timeout: int = 60,
        diagnostic: bool = False) -> str:
    result = subprocess.run(command, cwd=PROJECT, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        if diagnostic:
            detail = (result.stderr or result.stdout).strip()[:1000]
            raise RuntimeError(f"Command failed ({Path(command[0]).name}, exit {result.returncode}): {detail}")
        # Docker Compose receives provider keys; never echo its output on failure.
        raise RuntimeError(f"Command failed ({Path(command[0]).name}, exit {result.returncode}); details withheld")
    return result.stdout


class Api:
    def __init__(self):
        import http.cookiejar
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body=None, *, timeout=40):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + '/api' + path, data=data, method=method,
            headers={'Content-Type': 'application/json', 'Origin': BASE})
        try:
            with self.opener.open(req, timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw and 'json' in response.headers.get('Content-Type', '') else raw
        except urllib.error.HTTPError as exc:
            # Error bodies contain no secrets; retain enough status to diagnose configuration.
            body = exc.read()[:600].decode('utf-8', errors='replace')
            raise RuntimeError(f"API {method} {path} failed ({exc.code}): {body}") from None


def gemini_models(key: str) -> list[dict]:
    url = 'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000'
    request = urllib.request.Request(url, headers={'x-goog-api-key': key})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Gemini model metadata request failed with HTTP {exc.code}; no inference was sent") from None
    models = data.get('models', [])
    if not isinstance(models, list):
        raise RuntimeError('Gemini model metadata response was not a list')
    return [m for m in models if isinstance(m, dict)]


def preflight() -> str:
    cli_env = ['-e', 'HOME=/tmp', '-e', 'TMPDIR=/tmp']
    codex_version = run(COMPOSE + ['exec', '-T', *cli_env, 'cli-worker', 'codex', '--version'], diagnostic=True).strip()
    gemini_version = run(COMPOSE + ['exec', '-T', *cli_env, 'cli-worker', 'gemini', '--version'], diagnostic=True).strip()
    if '0.157.0' not in codex_version:
        raise RuntimeError(f'Codex version mismatch: {codex_version}')
    if '0.61.0' not in gemini_version:
        raise RuntimeError(f'Gemini version mismatch: {gemini_version}')
    codex_root_help = run(COMPOSE + ['exec', '-T', *cli_env, 'cli-worker', 'codex', '--help'], diagnostic=True)
    codex_help = run(COMPOSE + ['exec', '-T', *cli_env, 'cli-worker', 'codex', 'exec', '--help'], diagnostic=True)
    gemini_help = run(COMPOSE + ['exec', '-T', *cli_env, 'cli-worker', 'gemini', '--help'], diagnostic=True)
    codex_global_flags = ('--no-daemon', '--ask-for-approval')
    missing = [flag for flag in codex_global_flags if flag not in codex_root_help]
    if missing:
        raise RuntimeError(f'Codex root help missing expected global flags: {missing}')
    codex_flags = ('--ignore-user-config', '--ignore-rules',
        '--ephemeral', '--skip-git-repo-check', '--sandbox', '--cd', '--model', '--json',
        '--color', '--output-schema', '--output-last-message')
    missing = [flag for flag in codex_flags if flag not in codex_help]
    if missing:
        raise RuntimeError(f'Codex help missing expected flags: {missing}')
    gemini_flags = ('--admin-policy', '--prompt', '--model', '--approval-mode', '--output-format', '--skip-trust')
    missing = [flag for flag in gemini_flags if flag not in gemini_help]
    if missing:
        raise RuntimeError(f'Gemini help missing expected flags: {missing}')
    container_policy = run(COMPOSE + ['exec', '-T', *cli_env, 'cli-worker', 'python', '-c',
        "import os,tomllib; p=tomllib.load(open('/etc/cuautoreview/gemini-deny-all.toml','rb')); assert p['rule']==[{'toolName':'*','decision':'deny','priority':999,'denyMessage':'Tools are disabled for bounded trajectory review.'}]; base='/workspace/platform/backend/app'; assert all(os.stat(base+'/'+n).st_uid==0 for n in ('gemini-empty-defaults.json','gemini-empty-settings.json')); print('ok')"], diagnostic=True)
    if container_policy.strip() != 'ok':
        raise RuntimeError('Container Gemini policy validation failed')
    return json.dumps({'codex_version': codex_version, 'gemini_version': gemini_version,
        'codex_global_flags': list(codex_global_flags), 'codex_exec_flags': list(codex_flags),
        'gemini_expected_flags': list(gemini_flags),
        'deny_all_policy': 'verified'}, sort_keys=True)


def wait_job(api: Api, batch_id: str, backend: str, timeout=190) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = api.call('GET', '/jobs?per_page=500')['items']
        selected = [job for job in jobs if job.get('batch_id') == batch_id]
        if len(selected) == 1 and selected[0].get('status') in ('completed', 'failed', 'cancelled'):
            return selected[0]
        if len(selected) > 1:
            raise RuntimeError(f'{backend} produced an unexpected job count; the application will not retry')
        time.sleep(1)
    jobs = api.call('GET', '/jobs?per_page=500')['items']
    selected = [job for job in jobs if job.get('batch_id') == batch_id]
    return selected[0] if len(selected) == 1 else {'status': 'unknown', 'error': 'Poll deadline elapsed; the application will not retry'}


def start_one(api: Api, backend: str, model: str, suffix: str) -> dict:
    config = {'timeout_seconds': 120, 'max_output_tokens': 4096, 'max_images': 0}
    if backend == 'codex':
        config['codex_base_url'] = 'https://us.api.openai.com/v1'
    dataset = api.call('GET', f'/datasets/{DATASET_ID}')
    selected_task = next((item for item in dataset.get('tasks', [])
                          if item.get('task_id') == TASK_ID or item.get('id') == TASK_ID), None)
    task_definition_id = (selected_task or {}).get('task_definition_id')
    if not task_definition_id:
        raise RuntimeError(f'Imported task {TASK_ID} was not found in dataset {DATASET_ID}; no run was started')
    run = api.call('POST', '/runs', {'name': f'CLI comparison {backend} {suffix}',
        'description': f'One-shot model comparison for imported task {TASK_ID}; one invocation per backend.',
        'task_definition_ids': [task_definition_id], 'workflow_revision_id': 'trajectory_review@1',
        'execution': {'backend': backend, 'model': model, 'reasoning': 'low',
            'budget_usd': 0.50, 'configuration': config}})
    run_id = run['id']
    api.call('POST', f"/runs/{run_id}/start", {'confirm_budget': True, 'expected_budget_usd': 0.50})
    job = wait_job(api, run_id, backend)
    task = api.call('GET', f"/runs/{run_id}/tasks/{TASK_ID}")
    latest = (task.get('review_history') or [])[-1] if task.get('review_history') else None
    return {'backend': backend, 'model': model, 'run_id': run_id,
        'task_id': TASK_ID, 'job': job, 'review': task.get('review'),
        'review_history_entry': latest, 'status': job.get('status')}


def main():
    global DATASET_ID, TASK_ID
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider-env', type=Path, default=DEFAULT_ENV_FILE,
                        help='Local env file from which only OPENAI_API_KEY, CODEX_API_KEY and GEMINI_API_KEY are read.')
    parser.add_argument('--dataset-id', default=DATASET_ID,
                        help='Imported dataset ID in your workspace; default belongs to the recorded local experiment.')
    parser.add_argument('--task-id', default=TASK_ID,
                        help='Source task ID in the selected dataset; default belongs to the recorded local experiment.')
    parser.add_argument('--codex-model', default='gpt-6-sol')
    parser.add_argument('--gemini-model', default='gemini-3.8-flash',
                        help='Exact Gemini model ID; must appear in metadata with generateContent support.')
    parser.add_argument('--prepare', action='store_true',
                        help='Recreate app/workers with selected provider keys, run no-inference preflight, and exit.')
    parser.add_argument('--skip-activation', action='store_true',
                        help='Run after a separate --prepare step; do not recreate services again.')
    parser.add_argument('--run', action='store_true', help='Execute exactly one Gemini and one Codex request after checks.')
    args = parser.parse_args()
    DATASET_ID, TASK_ID = args.dataset_id, args.task_id
    keys = parse_provider_keys(args.provider_env)
    if not keys.get('GEMINI_API_KEY') or not (keys.get('CODEX_API_KEY') or keys.get('OPENAI_API_KEY')):
        raise RuntimeError('Explicit Gemini and Codex/OpenAI keys are not both present; values withheld')
    # Compose inherits only the three explicitly selected key names plus the opt-in.
    env = os.environ.copy()
    for name in ('CODEX_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'ANTHROPIC_API_KEY',
                 'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS', 'AZURE_OPENAI_API_KEY'):
        env.pop(name, None)
    env.update(keys)
    env['ALLOW_HOSTED_INFERENCE'] = 'true'
    env['CUAUTOREVIEW_CODEX_BASE_URL'] = 'https://us.api.openai.com/v1'

    if args.prepare or (args.run and not args.skip_activation):
        # No provider request occurs during activation; this only updates container environment.
        run(COMPOSE + ['up', '-d', '--no-build', '--force-recreate', 'app', 'worker', 'cli-worker'],
            env=env, timeout=180)
    checks = preflight()
    if args.prepare:
        print(json.dumps({'preflight': json.loads(checks), 'credentials_present': True,
                          'inference_sent': False, 'services_recreated': ['app', 'worker', 'cli-worker']}, indent=2))
        return
    if not args.run:
        print(json.dumps({'preflight': json.loads(checks), 'credentials_present': True,
                          'inference_sent': False}, indent=2))
        return

    api = Api()
    creds = json.loads(ACCOUNT_FILE.read_text(encoding='utf-8'))
    api.call('POST', '/auth/login', {'email': creds['email'], 'password': creds['password']})
    providers = api.call('GET', '/providers')['items']
    caps = {item['id']: item for item in providers}
    for backend in ('codex', 'gemini_cli'):
        if not caps.get(backend, {}).get('execution_enabled') or not caps[backend].get('configured'):
            raise RuntimeError(f'{backend} is not available/configured after the opt-in restart')
    if not caps.get('model_api', {}).get('configured'):
        raise RuntimeError('model_api is not configured after the opt-in restart')

    listed = gemini_models(keys['GEMINI_API_KEY'])
    candidates = [m for m in listed if 'generateContent' in (m.get('supportedGenerationMethods') or [])]
    def short_name(item): return str(item.get('name', '')).removeprefix('models/')
    exact = next((m for m in candidates if short_name(m) == args.gemini_model), None)
    if exact is None:
        raise RuntimeError(f'Requested Gemini model {args.gemini_model!r} was not listed with generateContent; no inference was sent')
    gemini_model = short_name(exact)
    codex_model = args.codex_model
    suffix = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report = {'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'task': {'dataset_id': DATASET_ID, 'task_id': TASK_ID},
        'preflight': json.loads(checks), 'models_metadata_only': {'gemini': gemini_model,
            'gemini_supported_methods': exact.get('supportedGenerationMethods')},
        'budget': {'configured_usd_per_run': 0.50, 'kind': 'estimate_only', 'hard_cap': False,
                   'timeout_seconds': 120, 'max_output_tokens_configured': 4096,
                   'max_images': 0, 'automatic_retries': 0, 'retry_policy_scope': 'application'},
        'runs': []}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = REPORT_DIR / f'cli-model-comparison-{suffix}.json'
    def save_report():
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    save_report()
    # Sequential and exactly one start per backend. Failures are captured; never auto-retry.
    for backend, model in (('gemini_cli', gemini_model), ('codex', codex_model)):
        result = start_one(api, backend, model, suffix)
        report['runs'].append(result)
        save_report()
        if result['status'] not in ('completed', 'failed', 'cancelled'):
            break
    print(json.dumps({'report_path': str(target), 'task_id': TASK_ID,
        'runs': [{'backend': r['backend'], 'model': r['model'], 'status': r['status'],
                  'run_id': r.get('run_id'), 'job_id': r['job'].get('id'), 'usage': r['job'].get('usage'),
                  'error': r['job'].get('error')} for r in report['runs']]}, indent=2))

if __name__ == '__main__':
    main()
