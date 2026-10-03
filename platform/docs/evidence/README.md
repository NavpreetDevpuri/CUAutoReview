# Verification evidence

Machine-written reports from the verification scripts in [`platform/scripts`](../../scripts). Each script overwrites its own report when rerun. [TEST-RESULTS.md](../TEST-RESULTS.md) explains what each check covers and its limits; a report existing here is not proof that a scenario currently passes.

| Report | Written by |
|---|---|
| [verification.json](verification.json) | `e2e_local.py`: real-service scenarios with saved trajectories |
| [queue-verification.json](queue-verification.json) | `verify_queue.py`: pause, duplicate delivery and retry against the real broker |
| [zip-import-verification.json](zip-import-verification.json) | `check_zip_import.py` |
| [batch-completion-verification.json](batch-completion-verification.json) | `check_batch_completion.py` |
| [runs-analytics-verification.json](runs-analytics-verification.json) | `check_runs_analytics.py` |
| [docker-quickstart-verification.json](docker-quickstart-verification.json) | `verify_docker_quickstart.py`, run in the seed container after each seed |
| [demo-verification.json](demo-verification.json) | Demo seed and role-login checks for the earlier five-task batch |
| [batch-status-repair.json](batch-status-repair.json), [responsive-ui-verification-20260927.json](responsive-ui-verification-20260927.json) | One-off recorded checks referenced from TEST-RESULTS.md |
| [new-features-backend-tests.md](new-features-backend-tests.md) | Historical notes on the backend tests added with runs, sharing and analytics |
