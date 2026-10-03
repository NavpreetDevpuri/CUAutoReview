# Platform UX feedback

Concise record of requested changes and the reason for each. The earlier viewer history remains in [POC feedback](../poc/VIEWER-FEEDBACK.md).

| Feedback | Change | Why |
|---|---|---|
| Upload tasks and screenshots together | Optional ZIP on dataset creation and later imports; JSON remains available | Avoid separate task and image setup |
| Explain the accepted structure | Inline archive tree and example manifest, downloadable ZIP, detailed user guide | Make the format discoverable before upload |
| Show useful import problems | Task/image preview, file-specific errors, warnings, explicit confirmation | Catch broken data before saving; missing visual evidence stays explicit |
| Let users choose light or dark | Sun/moon control on sign-in and beside the account; saved browser preference | Readable pages, forms, status chips and code in either mode |
| Put user docs at bottom left | Help and guides, Markdown topics, heading index, React Markdown and GFM rendering | Keep task guidance inside the product and easy to maintain |
| 100% done still says running | Flush and reconcile final worker state, quietly refresh batch progress | Show the persisted completion state without restarting work |
| Preserve the right screenshot after an update | Pin dataset links to source revision and batch links to member | New evidence opens correctly while historical evidence stays intact |
| Keep narrow layouts readable | Contain table scrolling; simplify the top bar; clarify the collapsed navigation control | Preserve access to task actions without stretching the page |
| Support keyboard upload | Use a native button for the file picker | Enter and Space can open file selection |

Uploads and validation never start review jobs. New taxonomy releases still need explicit approval. These improvements apply to the local platform; the original POC stays separate.

| Further feedback | Change | Why |
|---|---|---|
| Batches sound like datasets | Runs for analysis; Dataset → Task → Reviews hierarchy | Separate source data from repeated model experiments |
| Start replay runs immediately | Configuration dialog for scope, workflow, harness, model, evidence and budget | Make the action and cost visible before starting |
| Cancelled run is a dead end | Run again creates a configurable successor with preserved source revisions | Keep history immutable and make recovery understandable |
| Presets hide which prompts execute | Workflow prompts and routing shown separately from execution settings | Make the review method inspectable |
| Only card titles open | Whole dataset/run cards are links | Make clicking and opening a new tab predictable |
| Need individual task runs and history | Single-task analysis, all reviews, related runs, export and archive | Support both focused review and bulk work |
| Need people as well as teams | Search name/email; share with users, teams or workspace viewers | Avoid copying user IDs and simplify collaboration |
| Need useful cross-run analytics | Full-screen searchable dataset/run/task cards, selection counts, URL filters | Show the scope clearly and keep it editable |
| Models can disagree | Same-source comparison, aligned steps, both full reviews, shared feedback note | Preserve disagreement for a human decision |
| Every demo dataset repeats the same five tasks | Three disjoint datasets with 3/3/2 public tasks; old fixtures archived | Keep the demo representative without deleting test evidence |
| Labels and actions wrap awkwardly | Single-line action labels with consistent icon spacing | Improve scanning and keep controls recognisable |
| Is the blank screenshot a bug? | Explicit missing-frame state; source step 2 has no retained frame | Separate absent evidence from viewer loading failures |
| Dataset tasks should open as trajectories | Step sidebar, selected evidence, run-attributed flags, other reviews below | Keep the task's evidence central while allowing review comparison |
| Show which run produced each flag | Review selector and per-flag run/model context; align only matching source revisions | Avoid blending independent diagnoses or comparing different source data |
| Choose from available models | Searchable dropdown backed by a safe provider metadata snapshot | Avoid typing invalid IDs; show discovery separately from successful execution |
| Why is the budget zero? | Label replay as free; start hosted settings with a positive allowance | Explain zero cost honestly without leaving a paid configuration unusable |
| A completed run can contain failures | Show Finished with errors wherever terminal job failures are present | Completion measures finished processing, not successful reviews |
| Presets should be useful while starting | Optional saved execution shortcut alongside a separate prompt workflow | Reuse settings without hiding which model or prompts will run |

| Final usability checks | Change | Why |
|---|---|---|
| Next/previous can move beyond the visible sidebar | Keep the selected step visible inside the step list | Preserve orientation without moving the evidence panel again |
| Comparison choices can leak into another task | Clear selections and filters when task or revision changes; show a ready message after two choices | Prevent comparing the previous task by mistake |
| A model flag can overstate the evidence | Identify flags as model assessments and keep the review status visible | The live comparison exposed an unsupported recovery claim; feedback preserves it for adjudication |
| Failed job still says review pending | Show Review failed and No review produced | Distinguish terminal errors from queued work |
| Bulk run breadcrumb names only one source | Multi-dataset runs navigate through Runs without claiming a single parent dataset | Keep the hierarchy truthful |
| Source screenshots look like proof of review | Distinguish source, supplied, omitted and cited image step IDs; explain that citations are model claims | A saved frame may not reach a model, and a citation does not independently verify visual inspection |
| Retries can multiply the configured allowance | Show processing attempts, additional attempts and planned allowance including the retry maximum | Make the per-attempt estimate and possible repeated inference cost visible |

| Latest human feedback | Change | Why |
|---|---|---|
| Screenshots visible, but reviewer says none supplied | Attach screenshots to both native CLI reviewers; retain source/sent/cited metadata | Separate delivery defects from genuine uncertainty |
| Cannot see review and flag totals before opening a task | Correct API-backed totals with expandable per-model and per-run breakdowns | Find reviewed tasks without trial and error |
| Framework failure and review failure look the same | Separate original OSWorld score, review processing and review assessment | A failed task can have a successfully completed review |
| Finished with errors does not explain what failed | Show plain-language reason, affected job and attempt history | Make malformed output and infrastructure errors actionable |
| Repeated processing failures need retries | Initial attempt plus up to three retries; keep every attempt and cost | Recover transient/output failures without changing valid diagnoses |
| Run-to-task breadcrumb can open a missing page | Use the pinned task definition and its actual dataset | Keep navigation correct for multi-dataset runs |
| Step assessment counts look like screenshot coverage | Show model-reported assessments beside separate source, sent and cited image counts | Explain evidence gaps without implying that visible screenshots are missing |
| Job details omit the model or imply unknown cost is zero | Read the pinned execution settings; label incomplete cost totals as known subtotals | Preserve model attribution and honest cost accounting |
| Giant wrapped flag pills obscure problem and reviewer identity | Fixed columns for problem number and label; separate aligned relation, review and model rows | Compare steps quickly without parsing a long dotted sentence |
| Fonts and spacing feel oversized | Explicit 14px body text, restrained heading sizes, smaller corners and consistent spacing | Keep information readable and visually balanced |
| Phone layout leaves too little room for evidence | Mobile navigation drawer, full-screen step picker, stacked cards and wrapping controls | Keep screenshots accessible without squeezing desktop columns |
| Only card titles respond to clicks | Whole navigation cards use real links; selection cards toggle once; secondary actions stay independent | Support mouse, keyboard, touch and opening a new tab |
| Focus effects hide step text | Step cards use a clear focus outline without a large ripple; collapsed navigation keeps its contents inside the rail | Preserve readable flags during keyboard navigation |

## Independent audit follow-up: 27 September 2026

[Opus report and verified decisions](../reviews/claude-audit-actions.md). These are audit suggestions checked against the user's earlier UX requirements, not new human feedback.

| Observation | Change | Reason |
|---|---|---|
| Identical labels repeat for several reviews | Group exact displayed label/relationship text; keep each review's problem number, model and frame input | Reduce repetition without implying one shared diagnosis or consensus |
| Full run names make each step too tall | Put the full review-to-run mapping in a visible **Review names** disclosure, outside step buttons | Preserve provenance without repeating timestamped names on every step |
| Screenshot visible in UI looks like model input | Per-step **Frame sent**, **Frame not sent** or **Delivery unknown**, with explicit legacy text-only status | Source availability, delivery and citations are different facts |
| Workspace totals look like demo or unique-task totals | Label **Task selections**, explain repeats and retained/archive scope | One source can appear in many runs |
| Runtime shows unavailable health fields | Render the actual queue/provider/storage configuration and identify it as configuration | Do not infer broker health from configured delivery |
| Problem, step and review counts are ambiguous | Define episodes versus explicitly flagged steps, show latest review per run and correct plurals | One episode can span several steps; repeated reviews are not unique failures |

Verified with the focused grouping/evidence tests, frontend build and desktop/mobile browser checks. [Desktop](screenshots/audit-grouped-flags-20260927.jpg) · [mobile](screenshots/audit-mobile-flags-20260927.jpg). No diagnosis was regenerated or historical label renamed.
