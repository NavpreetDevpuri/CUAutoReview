# Roles and teams

Workspace roles, dataset sharing, and run access are separate controls. A team organizes workspace members; dataset shares control access to source tasks, while run grants control access to the run and its results.

## Workspace roles

- **Administrator** manages workspace users and roles, reviews taxonomy candidates for publication, and has workspace-wide management access.
- **Manager** manages workspace datasets, presets, teams, and runs. Managers can grant run access and manage job retries.
- **Reviewer** can contribute reviewer feedback and taxonomy proposals. To open task trajectories in a run, a reviewer needs reviewer access to the dataset and run, directly or through a team.
- **Viewer** can read run details and task lists shared with them. Viewer access is read-only; reviewer actions require reviewer access.

An administrator can manage team membership and change workspace roles on the Teams page. Managers can create teams and manage runs. Workspace roles do not replace dataset sharing or run grants. Removing a user from a team or changing a workspace role does not automatically create access to a dataset or run.

## Teams and run access

Administrators can create a team and add existing workspace users. Team membership alone does not expose datasets or runs. Share a dataset with selected users or teams from its Dataset access panel. Use run grants when access should apply only to a specific run. Reviewer access allows task trajectories and reviewer actions; viewer access is read-only.

Run access is scoped to an individual run. Review its access settings to see which users and teams can open its results.
