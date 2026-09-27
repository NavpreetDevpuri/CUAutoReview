# Trajectories and taxonomy

The trajectory viewer presents the task and step evidence saved with a run. Opening a trajectory only reads saved records; it does not start another run.

## Inspect a trajectory

Open a task from its dataset or run to see its recorded instruction, outcome, steps, screenshots, and review summary. Use the step controls or task list to move through the recorded sequence. A missing source screenshot is distinguished from an image fetch error; a missing review field does not imply success or failure.

- On a phone, open **All steps** to see the full step list, then select a step to return to its evidence.
- Flag rows separate the problem number, label, relationship to earlier steps, review and model. Each review keeps its own problem numbers.
- Open a task or review by clicking its card. Checkboxes select reviews for comparison; other buttons retain their own action.

## Source screenshots and model evidence

The evidence summary separates four facts. **Source** image IDs mark steps whose authorized task revision references a screenshot; the image may still be unavailable or unreadable. **Supplied** IDs mark images whose bytes were attached to a model request. **Omitted** IDs mark source references not sent, for example because of an evidence limit or unavailable artifact. **Cited** IDs mark frame references included in the review output. A supplied image is not proof the model examined it, and a citation is the model's claim rather than independent confirmation that the image supports the conclusion. Historical live CLI reviews were text-only; the local Gemini CLI transport check confirms image delivery but does not establish visual accuracy.

Reviewer feedback is appended to the selected task and, when chosen, the selected step. Feedback records who added it and when. It does not rewrite the source task or the saved review.

## Propose and publish taxonomy changes

The taxonomy page separates proposals from approved labels. Reviewers and managers can add proposal revisions and feedback. Consolidation creates a candidate snapshot for human review. A candidate is not published when it is created; an administrator must review and approve it. Approval checks the candidate version and content hash so the exact reviewed snapshot is the one published.

Published taxonomy releases are versioned. Runs keep the release pinned when they are created, which preserves the context used for their reviews.
