# New feature backend regression tests

## Verification

- `python -m py_compile backend/app/main.py backend/tests/test_hierarchy_api.py scripts/check_runs_analytics.py` passed.
- Earlier focused hierarchy suite: **6 passed**; those checks remain part of the full suite below.
- Latest full suite in the final running Docker app: **95 passed**, 6 warnings, in 13.79 seconds. No provider requests were made. [Exact command](TEST-RESULTS.md).
- Earlier focused direct-run permission regression: **1 passed**, 61 deselected; included in the latest full suite.
- The live service check at `scripts/check_runs_analytics.py` passed 7 checks with `provider_calls: 0`. Its report is `runs-analytics-verification.json`; 4 created runs, 2 task definitions, and 2 datasets were soft-archived.
- The live app health endpoint returned `{"status":"ok","queue_mode":"sql_outbox_celery","object_store":"s3"}`. OpenAPI included run aliases for grants, task feedback, task export, and reconcile.
- The running image includes direct-grant analytics, selected/total source counts, task titles and `partial_access` output. The focused in-container permission test verifies these boundaries.

## Regression coverage

`tests/test_hierarchy_api.py` exercises:

- Multi-dataset run creation, pinned workflow snapshot, catalog discovery, user dataset shares, and directory lookup.
- Run source records report included and current task counts per dataset. Dataset detail coverage and each nested run count only that dataset's tasks, even when a run covers multiple datasets.
- Run URL aliases cover grant creation/revocation, task feedback read/write, task export, and status reconciliation.
- Authorization for a multi-source run: access stays denied when only one source dataset is shared; run and compare access succeeds after all source datasets are shared. Hidden dataset analytics selection, viewer management actions, and compare access are denied.
- Review history and aligned compare results. Compare includes `task_id` on the aligned task and each result, plus backend, model, and the full review payload; it returns field differences without a verdict.
- Analytics task counts with explicit run filters. Selecting A and B tasks with an A-only run reports one matched task and one run member, plus two pre-intersection selected task definitions. Selecting an A task with a B-only run reports zero matched tasks, zero members, and an empty row set.
- Draft cancellation and rerun behavior. Reruns create a new draft linked to the source run and preserve its task revision IDs; source history remains readable. Viewers cannot cancel, rerun, configure, archive, or restore runs.
- Archive visibility and restoration for datasets, tasks, and runs. Archived items are hidden by default, visible with `include_archived=true`, and visible normally after restore. Archived task export requires `include_archived=true`.

## API fixes verified

- `/api/analytics/query` reports `counts.task_definitions` as unique matched task-definition rows after filter intersection. The additive `counts.selected_task_definitions` field reports the number of valid task definitions selected before run intersection.
- `/api/analytics/compare` returns the task's stable `task_id` in `aligned` and per-result records.
- Dataset task export accepts `include_archived=true` to allow explicitly requested export of archived tasks or datasets.
- Provider capability reporting includes Codex CLI and Gemini CLI when their execution capability is enabled.
- Directly shared runs appear in catalog and analytics for authorized members, without showing unrelated hidden-dataset tasks. Hidden source cards carry `partial_access` and omit the full dataset task total.
