import type { BatchRecord, Episode, ReviewEvidenceProvenance, TaskRecord, TrajectoryStep } from "../../api/types";
import { displayValue } from "../../lib/format";
import { asRecord } from "../../lib/records";

/** Pure helpers that interpret review episodes and step links for the trajectory viewer. */

export type AnyRecord = Record<string, unknown>;
export interface BatchTaskRow extends TaskRecord {
  review_kind?: string;
  review_status?: string;
  reviewed_steps?: number;
  total_steps?: number;
}
export interface TrajectoryResponse {
  batch?: BatchRecord;
  member?: BatchTaskRow & { task?: TaskRecord };
  task?: TaskRecord;
  review?: TaskRecord["review"];
  review_history?: AnyRecord[];
  review_provenance?: ReviewEvidenceProvenance | null;
  artifacts?: AnyRecord[];
  feedback?: AnyRecord[];
  [key: string]: unknown;
}

export function idOf(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}
export function text(value: unknown, fallback = "Not recorded"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(item => text(item)).join(", ");
  const inner = asRecord(value);
  if (typeof inner.text === "string") return inner.text;
  return displayValue(value, fallback);
}
export function outcomeLabel(value: unknown): string {
  if (value === true) return "passed";
  if (value === false) return "failed";
  return text(value, "unknown");
}
export function stepsOf(task?: TaskRecord | null): TrajectoryStep[] {
  return Array.isArray(task?.steps) ? task.steps : [];
}
export function stepId(step: TrajectoryStep): string {
  return idOf(step.step_id ?? step.id);
}
export function reviewFor(row: BatchTaskRow | TaskRecord | undefined): TaskRecord["review"] {
  return row?.review && typeof row.review === "object" ? row.review : undefined;
}
export function episodesOf(review?: TaskRecord["review"]): Episode[] {
  return Array.isArray(review?.episodes) ? review.episodes : [];
}
export function getEpisodeId(episode: Episode): string {
  return idOf(episode.episode_id ?? episode.id);
}
export function stepRefs(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map(item =>
      typeof item === "object" && item !== null
        ? idOf((item as AnyRecord).step_id ?? (item as AnyRecord).id)
        : idOf(item),
    )
    .filter(Boolean);
}
export function refsWithRole(value: unknown): { episodeId: string; role: string }[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap(item => {
    if (typeof item === "string" || typeof item === "number") return [{ episodeId: String(item), role: "" }];
    const ref = asRecord(item);
    const episodeId = idOf(ref.episode_id ?? ref.id);
    return episodeId ? [{ episodeId, role: String(ref.role || "").toLowerCase() }] : [];
  });
}
export function recoveryIds(episode: Episode): string[] {
  const recovery = asRecord(episode.recovery);
  return stepRefs(recovery.step_ids ?? recovery.steps);
}
export function relatedIds(episode: Episode): string[] {
  return stepRefs(episode.related_step_ids ?? episode.related_steps);
}
export function labelFor(episode: Episode): string {
  return text(episode.label_name ?? episode.label_id, "Unlabeled");
}
export const labelTitles: Record<string, string> = {
  "Repeated mis-targeted UI activation": "Repeated clicks do not activate the target",
  "Wrong UI target activated": "Wrong control activated",
  "Repeated ineffective modal dismissal": "Dialog remains open after dismissal attempts",
  "Online resource blocked by proxy or network path": "Online resource cannot be reached",
  "Malformed command-entry key sequence": "Command entered incorrectly",
  "Retrieved information does not match requested scope": "Result does not match the requested information",
  "Numeric entry appended in wrong field": "Text entered in the wrong field",
  "Required dialog action left incomplete": "Dialog left unfinished",
  "Repeated intended-control activation miss": "Repeated clicks do not activate the target",
  "Unintended control activation": "Wrong control activated",
  "Persistent modal after dismissal attempts": "Dialog stays open after attempts to close it",
  "Network-path resource blockage": "Network error blocks the page",
  "Malformed command-entry sequence": "Command entered incorrectly",
  "Retrieved scope mismatch": "Result does not match the requested information",
  "Entry into still-focused wrong field": "Text entered in the wrong field",
  "Dialog abandoned before correction and confirmation": "Dialog left unfinished",
};
export function displayedLabel(name: string): string {
  return labelTitles[name] || name;
}
export function resolveEpisodeLabel(episode: Episode, labels: AnyRecord[], proposals: AnyRecord[]) {
  const episodeLabelId = idOf(episode.label_id);
  const pinned = labels.find(item => episodeLabelId && String(item.id) === episodeLabelId);
  const recordedName = labelFor(episode);
  const draft =
    proposals.find(item => episodeLabelId && String(item.label_id || item.id || item.proposal_id) === episodeLabelId) ||
    proposals.find(item => String(item.name || "") === recordedName);
  const revision = asRecord(draft?.latest_revision);
  const name = String(pinned?.name || draft?.name || revision.name || recordedName);
  const pinnedDescription =
    typeof pinned?.description === "string" && pinned.description.trim() ? pinned.description : undefined;
  const draftDescription = episode.label_description || draft?.description || revision.description;
  return {
    id: String(pinned?.id || episode.label_id || draft?.id || ""),
    rawName: recordedName,
    displayName: displayedLabel(name),
    definition: pinnedDescription || draftDescription,
    definitionSource: pinnedDescription
      ? "Pinned taxonomy definition"
      : draftDescription
        ? "Recorded draft definition (not approved)"
        : "Definition",
  };
}
export function labelDefinitionText(resolved: ReturnType<typeof resolveEpisodeLabel>): string {
  return resolved.definition
    ? `${resolved.definitionSource}: ${text(resolved.definition)}`
    : "Not recorded in the pinned taxonomy or draft proposals.";
}
export function taskSummary(task: TaskRecord) {
  const review = reviewFor(task);
  const hasEpisodeData = Boolean(review && Array.isArray(review.episodes));
  const episodes = episodesOf(review);
  const flagged = new Set<string>();
  const recovery = new Set<string>();
  episodes.forEach(episode => {
    stepRefs(episode.onset_step_ids).forEach(id => flagged.add(id));
    recoveryIds(episode).forEach(id => recovery.add(id));
  });
  const labelGroups = new Map<string, { id: string; label: string; count: number }>();
  for (const episode of episodes) {
    const original = labelFor(episode);
    if (original === "Unlabeled") continue;
    const id = idOf(episode.label_id);
    const key = id || original;
    const group = labelGroups.get(key) || { id, label: displayedLabel(original), count: 0 };
    group.count += 1;
    labelGroups.set(key, group);
  }
  const labels = [...labelGroups.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  return {
    episodes,
    problemCount: hasEpisodeData ? episodes.length : null,
    flaggedCount: hasEpisodeData ? flagged.size : null,
    recoveryCount: hasEpisodeData ? recovery.size : null,
    labelCount: hasEpisodeData ? labels.length : null,
    labels,
  };
}
export function taskOutcome(row: TaskRecord): unknown {
  return row.outcome ?? row.evaluator_outcome ?? asRecord(row.source).outcome;
}
export function taskKey(row: TaskRecord): string {
  return idOf(row.task_id ?? row.id);
}
export function reviewAssessmentLabel(row: TaskRecord, review = reviewFor(row)): string {
  if (review) return String(review.result || (episodesOf(review).length ? "Issues recorded" : "No issues recorded"));
  const summary = asRecord(row.review_summary);
  if (Number(summary.review_count || 0) > 0) return "Assessment recorded";
  if (String(row.processing_status || row.status || "").toLowerCase() === "failed")
    return "Not available: review processing failed";
  return "Not recorded";
}
export function reviewProcessingLabel(row: TaskRecord): string {
  return `Review processing: ${String(row.processing_status || row.status || "not started").replaceAll("_", " ")}`;
}

export function firstProblemAnchor(task: TaskRecord, episode: Episode): string {
  if (
    String(task.review?.schema_version) === "2" &&
    episode.first_observed_step_id !== undefined &&
    episode.first_observed_step_id !== null
  )
    return String(episode.first_observed_step_id);
  const onset = new Set(stepRefs(episode.onset_step_ids));
  return (task.steps || []).map(stepId).find(id => onset.has(id)) || stepRefs(episode.onset_step_ids)[0] || "";
}
export function taskProblemLinks(task: TaskRecord, episode: Episode): { id: string; role: string }[] {
  const anchor = firstProblemAnchor(task, episode);
  const observedAnchor =
    String(task.review?.schema_version) === "2" &&
    episode.first_observed_step_id !== undefined &&
    episode.first_observed_step_id !== null;
  const onset = stepRefs(episode.onset_step_ids);
  const links: { id: string; role: string }[] = [];
  if (observedAnchor && anchor && !onset.includes(anchor)) links.push({ id: anchor, role: "First observed here" });
  for (const id of onset)
    links.push({
      id,
      role:
        id === anchor
          ? observedAnchor
            ? "First observed here"
            : "First flagged here"
          : observedAnchor
            ? "Also observed here"
            : "Also flagged here",
    });
  for (const id of recoveryIds(episode)) links.push({ id, role: "Recovery step" });
  const episodeId = getEpisodeId(episode);
  for (const step of task.steps || []) {
    const id = stepId(step);
    if (!id || id === anchor || onset.includes(id) || recoveryIds(episode).includes(id)) continue;
    if (refsWithRole(step.episode_refs).some(ref => ref.episodeId === episodeId))
      links.push({ id, role: "Related step" });
  }
  const seen = new Set<string>();
  return links.filter(link => {
    const key = `${link.id}/${link.role}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function roleBadgeLabel(kind: string, observedAnchor: boolean): string {
  if (kind === "first") return observedAnchor ? "First observed here" : "First flagged here";
  if (kind === "onset") return observedAnchor ? "Also observed here" : "Also flagged here";
  if (kind === "recovery") return "Recovery step";
  return "Related step";
}

export interface StepRole {
  episodeId: string;
  number: number;
  kind: "first" | "onset" | "recovery" | "related";
  firstObserved: boolean;
}
export function rolesForStep(
  id: string,
  trajectory: TrajectoryStep[],
  episodes: Episode[],
  review: TaskRecord["review"],
): StepRole[] {
  if (!id) return [];
  return episodes.flatMap((episode, index) => {
    const episodeId = getEpisodeId(episode);
    const number = Number(episode.problem_number) || index + 1;
    const explicitOnsets = stepRefs(episode.onset_step_ids);
    const firstObservedId = idOf(episode.first_observed_step_id);
    const firstObserved = String(review?.schema_version) === "2" && Boolean(firstObservedId);
    const anchor = firstObserved
      ? firstObservedId
      : explicitOnsets.find(candidate => trajectory.some(step => stepId(step) === candidate)) ||
        explicitOnsets[0] ||
        "";
    const refs = [
      ...trajectory.filter(step => stepId(step) === id).flatMap(step => refsWithRole(step.episode_refs)),
      ...(review?.steps || [])
        .filter(step => idOf(step.step_id) === id)
        .flatMap(step => refsWithRole(step.episode_refs)),
    ];
    const role = refs.find(ref => ref.episodeId === episodeId)?.role;
    const result: StepRole[] = [];
    if (id === anchor) result.push({ episodeId, number, kind: "first", firstObserved });
    else if (explicitOnsets.includes(id) || role === "onset")
      result.push({ episodeId, number, kind: "onset", firstObserved });
    if (recoveryIds(episode).includes(id) || role === "recovery")
      result.push({ episodeId, number, kind: "recovery", firstObserved });
    if (
      relatedIds(episode).includes(id) ||
      role === "related" ||
      (refs.some(ref => ref.episodeId === episodeId) &&
        !explicitOnsets.includes(id) &&
        !recoveryIds(episode).includes(id) &&
        id !== anchor)
    )
      result.push({ episodeId, number, kind: "related", firstObserved });
    return result;
  });
}
