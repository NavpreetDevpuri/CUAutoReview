# POC viewer: human feedback and decisions

Feedback from your local POC reviews, in the order it shaped the viewer. Later decisions supersede earlier experiments.

| Your feedback | Decision | Why |
|---|---|---|
| Fonts are too small. | Use larger body text and readable controls. | Make long reviews easier to scan. |
| It is unclear which labels belong to which steps. | Replace the horizontal step strip with a labeled step sidebar. | Keep the step and its linked problems together. |
| The header takes too much screen space. | Let the whole page scroll; keep only navigation available. | Give the evidence more room. |
| The desktop screenshot should fill the available width. | Use full-width screenshots with explanations below. | Preserve visual detail. |
| Next/previous jumps leave the page in the wrong position. | Align every selected step to the same viewing position. | Compare steps without readjusting scroll. |
| Put task selection in a minimizable sidebar. | Combine tasks and steps in one collapsible sidebar. | Keep navigation close and reclaim width when needed. |
| “Mistake onset” and category names are hard to understand. | Initially use “Problem starts here”; supersede it with “First flagged here” for legacy evidence and “First observed here” for version 2. Keep plain behavior names and original names/IDs under “Recorded label.” | Show what the record supports without conflating first observation with onset or changing historical results. |
| Initially show label meanings on hover and below the screenshot. Later: tooltips keep appearing and are unnecessary. | Remove label tooltips; keep definitions and step-role explanations inline. | Avoid persistent overlays hiding the evidence. |
| “Command entered incorrectly” looks like plain text. | Give categories colored, bordered chips with readable names and IDs. | Make label identity obvious and consistent across views. |
| Multiple failures on one step are unclear. | Show a linked-problem count, separate numbered groups, and a compact summary linking to each explanation. Each problem keeps its own role and recovery status. | A step can recover from one problem while starting another. |
| Numbers and anchors should stay stable as one problem appears across several steps. | Give each episode one task-local problem number in first-observed order; preserve it in every onset, related and recovery group, and link each group and summary to the explicit first anchor. Legacy runs use the earliest explicit onset ID in trace order. | Repeated links must not look like new mistakes or lose the point where review first connected them to the problem. |
| Find a trajectory and judge its recorded status without opening every review. | Search by task name, ID or label. Show evaluator outcome separately from review availability, then recorded problems, unique flagged and recovery steps, problems by label, and labeled step links. One episode is one problem; missing review or episode data reads “Not recorded,” not zero issues confirmed. | Keep source outcome, review coverage and each count's denominator clear while making navigation quick. |
| Show the POC in its real browser context. | Capture the actual Chrome window with URL bar and red POC banner visible, cropped to omit the browser tab strip. | Let readers identify the local POC and its address from the documentation. |

- Problem numbers stay consistent within a task. Category IDs and colors stay consistent within the saved run; color does not indicate severity.
- Only explicit recorded links create markers. Missing evidence stays uncertain; category, step role and recovery remain separate. Raw outputs and historical IDs are unchanged.
- Implementation refinement, not a quoted viewer request: a small sticky **Screen ↑** toolbar action returns to the selected screenshot while the reviewer reads the explanations below it.

## Platform carryover, 27 September 2026

| Human feedback retained | Platform change | Why |
|---|---|---|
| Larger text and more screen space | Readable body text, collapsing navigation, scrolling header and full-width evidence panel | Keep the screenshot central |
| Labels must explain themselves | Colored plain-language chips and visible definitions, marked as draft or approved | Meaning is available without hover |
| Multiple problems on one step | Numbered problems, first anchors, separate flags/recovery/context links | Show which mistake each step belongs to |
| Task selection should be quick | Searchable cards, issue counts, compact step chips and collapsed context | Compare tasks without scanning long histories |
| Step navigation should stay aligned | Next/previous aligns the step toolbar and screenshot, keeping navigation visible and preserving exact member/step links | Avoid losing position or opening another source revision |
| Keep POC and platform distinct | Original POC and screenshots preserved; new platform under `platform/` | Preserve measured evidence and show implementation scope honestly |

- Browser review refinements: prevent step rows from shrinking inside the scrollable list; retain task-wide problem numbers below each screenshot; show readable job usage with raw IDs/data collapsed. These refinements support the feedback above rather than changing saved diagnoses.
