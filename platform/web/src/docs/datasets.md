# Datasets and ZIP imports

Datasets hold task records and their source revisions. A dataset import only saves the task records. It does not create a run, start a review, or make model calls.

## Dataset → task → reviews

Open a dataset to browse its task definitions and saved runs. Open a task to inspect its current source revision, task export, and the run and review history associated with that task. Its source-step viewer keeps saved step IDs visible, calls out missing steps, and uses the available width for screenshot evidence. Choose one review from the current source revision or overlay all current-revision reviews; every flag is labeled with its run and model. Reviews from older revisions remain in the history below and are not overlaid on the current source. A source revision is the imported task content; each run keeps the exact selected revision and its own review history. New imports can create a later revision without changing completed runs.

## Accepted task data

For a ZIP import, put either `dataset.json` or `dataset.yaml` at the archive root. Use the `cuautoreview` format and include a `tasks` array. Each task has a stable `task_id`, a title and instruction, a recorded outcome, and its ordered steps. Outcomes are `passed`, `failed`, or `unknown`. Each step has a stable `step_id`, an action, and an optional screenshot path.

```json
{
  "format": "cuautoreview",
  "tasks": [
    {
      "task_id": "task-1",
      "title": "Example task",
      "instruction": "Complete the requested action.",
      "outcome": "unknown",
      "steps": [
        {
          "step_id": "1",
          "action": "Open the requested page.",
          "screenshot": "assets/task-1/step-1.png"
        }
      ]
    }
  ]
}
```

Screenshots are optional. When included, use PNG, JPEG, or WebP files and reference them by a path inside the ZIP, such as `assets/task-1/step-1.png`. Keep task and step IDs unique within their respective dataset records.

## Main ZIP limits

The ZIP may be up to 32 MB, with at most 128 MB expanded and 1,000 archive entries. Each PNG, JPEG, or WebP screenshot can be up to 10 MB and 16 million decoded pixels. Keep the manifest at the archive root and use relative paths under `assets/` for screenshots. A ZIP preview reports the tasks, screenshots, warnings, and validation errors before import. Confirm the preview to save records; creating a run is a separate action.

## Technical format ceilings

A manifest can contain at most 5,000 tasks, 2,000 steps per task, and 50,000 steps across the archive. Each task record can be up to 512 KB, and the manifest structure can be nested no deeper than 100 levels. These limits apply together with the archive and image limits above.

You can download a [sample task manifest](/examples/dataset.json) or a [sample trajectory ZIP](/examples/trajectory-import.zip). The sample contains synthetic placeholder data and an unknown outcome.

## After import

Open a task from its dataset to inspect its source revision, associated runs, saved reviews, and task-level export. Use **Analyze task** to configure a run for just that task; **View analytics** opens the recorded analytics for the task and its dataset. Share a dataset with the whole workspace or selected users and teams from Dataset access.

When starting a run, select one or more datasets, individual tasks, or tasks already in a run. The run saves that selection as fixed membership across all chosen datasets. Later imports and archive changes do not silently change the selection. Use Sync on a supported appendable run to preview and explicitly admit later source revisions.

Archiving a dataset or task hides it from ordinary selection and list views but keeps its saved history. Use **Show archived** to find it and **Restore** to make it available again. An archived task remains in its existing runs; restoring it affects future selections only.
