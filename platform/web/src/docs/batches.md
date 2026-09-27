# Runs, results, and progress

A run pins a fixed task selection, workflow revision, execution configuration, and the access grants used for that work. Later dataset changes do not silently replace tasks already selected by a run.

Selections can include several datasets, selected tasks, or tasks from an existing run. Membership is recorded when the run is created, so changes to a source dataset do not alter the selection. Each task keeps its source revision alongside the run's result and reviews.

## Create and start a run

Choose datasets, existing runs, or individual tasks, then select the review workflow and execution setup. The **workflow** supplies the review instructions and rubric; the **execution** settings choose the harness/backend, model, reasoning level, and budget used to carry out those instructions. A run records the actual workflow prompt separately from the execution snapshot. Before hosted inference starts, review the planned total, which includes the configured per-attempt allowance through the maximum retry count.

Creating a run does not erase or reuse results from an earlier run. Re-running a cancelled, completed, or failed run creates a new run ID with the selected tasks copied into its own membership. The earlier run and its reviews remain available.

## Read results and status

Progress counts describe processing state, such as completed, active, queued, retrying, and failed jobs. Evaluator outcome counts describe the source benchmark result; saved/missing review counts describe whether a review artifact exists. These are separate facts: a task can have a recorded pass or failure outcome when processing failed, and a completed review job does not establish that its assessment was correct. Run task totals, source outcome totals, processing-state totals, review counts, and model invocation attempt/retry counts have different denominators and should not be added together. Missing evidence is not a zero or a passing result.

Open a run to inspect task-level results and its pinned workflow and execution snapshots. Depending on its state, managers can pause, resume, cancel, or sync an appendable run. A job allows up to four total attempts: retryable failures can trigger automatic retries, and managers can retry failed or completed jobs while attempts remain. Run summaries label attempts beyond the first as additional attempts, including both automatic and manager-requested retries. Each additional attempt is a separate potential provider charge.

## Archive and restore

Archiving a run removes it from the default Runs list and future selection menus while retaining its task results and reviews. Turn on **Show archived** to open it, then restore it when it should be selectable again. Restoring a run does not change its pinned task membership or start processing.

## Analytics and comparison

Open [Analytics](/analytics) to filter recorded results by one or more datasets, runs, and task definitions. The selection is reflected in the URL with repeatable parameters such as `?dataset=ID&run=ID&task=DEFINITION_ID`; filters can be bookmarked or shared. Archived records are excluded by default.

Analytics can compare two saved review results. Select two reviews for the same task and exact source revision; reviews of different revisions are not aligned for comparison. [Compare](/compare) shows differences in their recorded steps and problem episodes, and lets you flag a disagreement for human review. Wording differences alone do not establish that either review is wrong.

## Legacy batch links

Older `/batches` links remain available and open the same run records. New links and navigation use `/runs`.

## Models and budgets

- Choose a harness, then choose from its searchable model list. The list comes from a provider metadata snapshot for this workspace; it does not guarantee remaining quota.
- A saved execution preset can fill these settings. Review the model and budget before starting.
- Hosted settings start at a positive planning allowance. If prices are unknown, the initial allowance is $0.10 per task, not a measured quote. Saved replay is free.
- The configured task allowance applies per attempt. The planned total includes the maximum attempts, up to four times the per-attempt allowance for each reviewable task. This is a planning estimate, not a hard provider billing cap; a failed or lost response may still incur a charge, and provider-internal reconnects are not included. The run records usage when a harness reports it; unknown costs remain unknown.
- Stage instructions are separate from execution settings. The reviewer also receives the shared evidence rules, output schema and selected task.
