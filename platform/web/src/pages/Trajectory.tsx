import { useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Alert, Avatar, Box, Button, Chip, Collapse, Dialog, DialogContent, DialogTitle, Divider, IconButton, InputAdornment, Link, Paper, Stack, TextField, Typography, useMediaQuery } from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import FormatListNumberedRounded from "@mui/icons-material/FormatListNumberedRounded";
import { StepFlag } from "../StepFlag";
import ArrowBackRounded from "@mui/icons-material/ArrowBackRounded";
import ArrowForwardRounded from "@mui/icons-material/ArrowForwardRounded";
import ExpandLessRounded from "@mui/icons-material/ExpandLessRounded";
import ExpandMoreRounded from "@mui/icons-material/ExpandMoreRounded";
import SearchRounded from "@mui/icons-material/SearchRounded";
import CloseRounded from "@mui/icons-material/CloseRounded";
import OpenInNewRounded from "@mui/icons-material/OpenInNewRounded";
import { apiRequest } from "../api";
import { useApi } from "../hooks";
import type { BatchRecord, Episode, ReviewEvidenceProvenance, TaskRecord, TrajectoryStep } from "../types";
import { BenchmarkResult, EmptyState, ErrorState, LoadingState, PageBreadcrumbs, PageHeader, Panel, SectionTitle, StatusTag, displayValue, formatDate, reviewProcessingError } from "../components";

type AnyRecord = Record<string, unknown>;
interface BatchTaskRow extends TaskRecord { review_kind?: string; review_status?: string; reviewed_steps?: number; total_steps?: number; }
interface TrajectoryResponse {
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

function idOf(value: unknown): string { return value === undefined || value === null ? "" : String(value); }
function record(value: unknown): AnyRecord { return value && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {}; }
function text(value: unknown, fallback = "Not recorded"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(item => text(item)).join(", ");
  const inner = record(value);
  if (typeof inner.text === "string") return inner.text;
  return displayValue(value, fallback);
}
function outcomeLabel(value: unknown): string {
  if (value === true) return "passed";
  if (value === false) return "failed";
  return text(value, "unknown");
}
function stepsOf(task?: TaskRecord | null): TrajectoryStep[] {
  return Array.isArray(task?.steps) ? task.steps : [];
}
function stepId(step: TrajectoryStep): string { return idOf(step.step_id ?? step.id); }
function reviewFor(row: BatchTaskRow | TaskRecord | undefined): TaskRecord["review"] {
  return row?.review && typeof row.review === "object" ? row.review : undefined;
}
function episodesOf(review?: TaskRecord["review"]): Episode[] { return Array.isArray(review?.episodes) ? review.episodes : []; }
function getEpisodeId(episode: Episode): string { return idOf(episode.episode_id ?? episode.id); }
function stepRefs(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(item => typeof item === "object" && item !== null ? idOf((item as AnyRecord).step_id ?? (item as AnyRecord).id) : idOf(item)).filter(Boolean);
}
function refsWithRole(value: unknown): { episodeId: string; role: string }[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap(item => {
    if (typeof item === "string" || typeof item === "number") return [{ episodeId: String(item), role: "" }];
    const ref = record(item);
    const episodeId = idOf(ref.episode_id ?? ref.id);
    return episodeId ? [{ episodeId, role: String(ref.role || "").toLowerCase() }] : [];
  });
}
function recoveryIds(episode: Episode): string[] {
  const recovery = record(episode.recovery);
  return stepRefs(recovery.step_ids ?? recovery.steps);
}
function relatedIds(episode: Episode): string[] {
  return stepRefs(episode.related_step_ids ?? episode.related_steps);
}
function labelFor(episode: Episode): string { return text(episode.label_name ?? episode.label_id, "Unlabeled"); }
const labelTitles: Record<string, string> = {
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
function displayedLabel(name: string): string { return labelTitles[name] || name; }
const labelPalette = [
  { light: { bg: "#eaf1ff", fg: "#345fc0", border: "#b8c9ef" }, dark: { bg: "#253a60", fg: "#c1d4ff", border: "#5272a7" } },
  { light: { bg: "#e7f5ee", fg: "#19704d", border: "#b1dbc6" }, dark: { bg: "#214638", fg: "#b8e8d0", border: "#497961" } },
  { light: { bg: "#fff2da", fg: "#946311", border: "#e8d2a4" }, dark: { bg: "#49391f", fg: "#f3d18c", border: "#896b35" } },
  { light: { bg: "#f0eaff", fg: "#6845a7", border: "#d2c2ed" }, dark: { bg: "#392f52", fg: "#d6c6ff", border: "#7462a4" } },
  { light: { bg: "#ffebeb", fg: "#aa3a40", border: "#e5b7b9" }, dark: { bg: "#4a2c32", fg: "#ffc1c6", border: "#97575e" } },
  { light: { bg: "#e5f5f6", fg: "#176d73", border: "#acd9dc" }, dark: { bg: "#1e4144", fg: "#b9e9eb", border: "#4c8386" } },
  { light: { bg: "#fce9f2", fg: "#9b3c6b", border: "#e8bfd2" }, dark: { bg: "#482c3b", fg: "#f7c4db", border: "#985b79" } },
  { light: { bg: "#eef1f4", fg: "#495766", border: "#c7cdd4" }, dark: { bg: "#303945", fg: "#d0d7df", border: "#687583" } },
];
function labelColor(key: string): typeof labelPalette[number] {
  const canonical = /^c(\d+)$/i.exec(key);
  const index = canonical ? Number(canonical[1]) - 1 : [...key].reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 0);
  return labelPalette[Math.abs(index) % labelPalette.length];
}
function LabelChip({ id, label, count }: { id?: string; label: string; count?: number }) {
  const theme = useTheme();
  const colors = labelColor(id || label);
  const color = theme.palette.mode === "dark" ? colors.dark : colors.light;
  return <Chip size="small" label={count === undefined ? label : `${label} · ${count}`} sx={{ maxWidth: "100%", fontWeight: 750, bgcolor: color.bg, color: color.fg, border: "1px solid", borderColor: color.border }} />;
}
function resolveEpisodeLabel(episode: Episode, labels: AnyRecord[], proposals: AnyRecord[]) {
  const episodeLabelId = idOf(episode.label_id);
  const pinned = labels.find(item => episodeLabelId && String(item.id) === episodeLabelId);
  const recordedName = labelFor(episode);
  const draft = proposals.find(item => episodeLabelId && String(item.label_id || item.id || item.proposal_id) === episodeLabelId)
    || proposals.find(item => String(item.name || "") === recordedName);
  const revision = record(draft?.latest_revision);
  const name = String(pinned?.name || draft?.name || revision.name || recordedName);
  const pinnedDescription = typeof pinned?.description === "string" && pinned.description.trim() ? pinned.description : undefined;
  const draftDescription = episode.label_description || draft?.description || revision.description;
  return {
    id: String(pinned?.id || episode.label_id || draft?.id || ""),
    rawName: recordedName,
    displayName: displayedLabel(name),
    definition: pinnedDescription || draftDescription,
    definitionSource: pinnedDescription ? "Pinned taxonomy definition" : draftDescription ? "Recorded draft definition (not approved)" : "Definition",
  };
}
function labelDefinitionText(resolved: ReturnType<typeof resolveEpisodeLabel>): string {
  return resolved.definition ? `${resolved.definitionSource}: ${text(resolved.definition)}` : "Not recorded in the pinned taxonomy or draft proposals.";
}
function taskSummary(task: TaskRecord) {
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
function taskOutcome(row: TaskRecord): unknown { return row.outcome ?? row.evaluator_outcome ?? record(row.source).outcome; }
function taskKey(row: TaskRecord): string { return idOf(row.task_id ?? row.id); }
function reviewAssessmentLabel(row: TaskRecord, review = reviewFor(row)): string {
  if (review) return String(review.result || (episodesOf(review).length ? "Issues recorded" : "No issues recorded"));
  const summary = record(row.review_summary);
  if (Number(summary.review_count || 0) > 0) return "Assessment recorded";
  if (String(row.processing_status || row.status || "").toLowerCase() === "failed") return "Not available: review processing failed";
  return "Not recorded";
}
function reviewProcessingLabel(row: TaskRecord): string {
  return `Review processing: ${String(row.processing_status || row.status || "not started").replaceAll("_", " ")}`;
}

function firstProblemAnchor(task: TaskRecord, episode: Episode): string {
  if (String(task.review?.schema_version) === "2" && episode.first_observed_step_id !== undefined && episode.first_observed_step_id !== null) return String(episode.first_observed_step_id);
  const onset = new Set(stepRefs(episode.onset_step_ids));
  return (task.steps || []).map(stepId).find(id => onset.has(id)) || stepRefs(episode.onset_step_ids)[0] || "";
}
function taskProblemLinks(task: TaskRecord, episode: Episode): { id: string; role: string }[] {
  const anchor = firstProblemAnchor(task, episode);
  const observedAnchor = String(task.review?.schema_version) === "2" && episode.first_observed_step_id !== undefined && episode.first_observed_step_id !== null;
  const onset = stepRefs(episode.onset_step_ids);
  const links: { id: string; role: string }[] = [];
  if (observedAnchor && anchor && !onset.includes(anchor)) links.push({ id: anchor, role: "First observed here" });
  for (const id of onset) links.push({ id, role: id === anchor ? (observedAnchor ? "First observed here" : "First flagged here") : observedAnchor ? "Also observed here" : "Also flagged here" });
  for (const id of recoveryIds(episode)) links.push({ id, role: "Recovery step" });
  const episodeId = getEpisodeId(episode);
  for (const step of task.steps || []) {
    const id = stepId(step);
    if (!id || id === anchor || onset.includes(id) || recoveryIds(episode).includes(id)) continue;
    if (refsWithRole(step.episode_refs).some(ref => ref.episodeId === episodeId)) links.push({ id, role: "Related step" });
  }
  const seen = new Set<string>();
  return links.filter(link => { const key = `${link.id}/${link.role}`; if (seen.has(key)) return false; seen.add(key); return true; });
}

export function TrajectoryPage() {
  const { id: batchId = "", taskId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const memberId = searchParams.get("member_id") || "";
  const requestedStepId = searchParams.get("step_id") || "";
  const batch = useApi<{ run?: BatchRecord; batch?: BatchRecord }>(batchId ? `/runs/${encodeURIComponent(batchId)}` : null);
  const taxonomyState = useApi<{ releases?: AnyRecord[]; labels?: AnyRecord[]; proposals?: AnyRecord[] }>("/taxonomy");
  const tasksState = useApi<{ items?: BatchTaskRow[]; total?: number } | BatchTaskRow[]>(batchId ? `/runs/${encodeURIComponent(batchId)}/tasks` : null);
  const memberQuery = memberId ? `?member_id=${encodeURIComponent(memberId)}` : "";
  const detailState = useApi<TrajectoryResponse>(batchId && taskId ? `/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(taskId)}${memberQuery}` : null);
  const tasks = Array.isArray(tasksState.data) ? tasksState.data : tasksState.data?.items || [];
  const response = detailState.data;
  const member = response?.member;
  const directTask = response && typeof response.task_id === "string" && Array.isArray(response.steps) ? response as TaskRecord : undefined;
  const task = response?.task || member?.task || (member && member.steps ? member : undefined) || directTask;
  const review = response?.review || task?.review || member?.review || directTask?.review;
  const normalizedTask: TaskRecord | undefined = task ? { ...task, task_id: taskKey(task) || taskId, review: review || task.review } : undefined;
  const batchRecord = batch.data?.run || batch.data?.batch || batch.data as BatchRecord | null;
  const sourceDatasets = Array.isArray((batch.data as AnyRecord | null)?.source_datasets) ? (batch.data as AnyRecord).source_datasets as AnyRecord[] : [];
  const datasetId = String(normalizedTask?.dataset_id || record(normalizedTask?.source).dataset_id || sourceDatasets[0]?.id || sourceDatasets[0]?.dataset_id || batchRecord?.dataset_id || "");
  const datasetState = useApi<{ dataset?: AnyRecord }>(datasetId ? `/datasets/${encodeURIComponent(datasetId)}` : null);
  const selectedMemberId = memberId || idOf(normalizedTask?.member_id || member?.id);
  const selectedMemberQuery = selectedMemberId ? `?member_id=${encodeURIComponent(selectedMemberId)}` : "";
  const steps = useMemo(() => stepsOf(normalizedTask), [normalizedTask]);
  const episodes = useMemo(() => episodesOf(review), [review]);
  const [stepIndex, setStepIndex] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [stepPickerOpen, setStepPickerOpen] = useState(false);
  const theme = useTheme();
  const compactSteps = useMediaQuery(theme.breakpoints.down("lg"));
  const [taskPickerOpen, setTaskPickerOpen] = useState(false);
  const [taskSearch, setTaskSearch] = useState("");
  const [feedbackText, setFeedbackText] = useState("");
  const [feedback, setFeedback] = useState<AnyRecord[]>([]);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackError, setFeedbackError] = useState("");
  const [feedbackNotice, setFeedbackNotice] = useState("");
  const [screenshotLoadFailed, setScreenshotLoadFailed] = useState(false);
  const screenshotRef = useRef<HTMLDivElement>(null);
  const stepListRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setStepIndex(0); }, [taskId, memberId]);
  useEffect(() => {
    if (detailState.loading) return;
    const index = requestedStepId ? steps.findIndex(step => stepId(step) === requestedStepId) : -1;
    setStepIndex(index >= 0 ? index : 0);
  }, [detailState.loading, requestedStepId, steps]);
  useEffect(() => {
    setFeedback(Array.isArray(response?.feedback) ? response.feedback : []);
  }, [response?.feedback, taskId, memberId]);
  useEffect(() => {
    if (detailState.loading) return;
    requestAnimationFrame(() => screenshotRef.current?.scrollIntoView({ block: "start" }));
  }, [taskId, memberId, detailState.loading]);
  const selectedStep = steps[stepIndex];
  const selectedStepId = selectedStep ? stepId(selectedStep) : "";
  useEffect(() => {
    if (selectedStepId) requestAnimationFrame(() => screenshotRef.current?.scrollIntoView({ block: "start" }));
  }, [selectedStepId]);
  useEffect(() => { setScreenshotLoadFailed(false); }, [selectedStepId]);
  useEffect(() => {
    if (stepPickerOpen) requestAnimationFrame(() => stepListRef.current?.querySelector<HTMLElement>('[aria-current="step"]')?.scrollIntoView({ block: "center" }));
  }, [stepPickerOpen]);
  const currentTask = normalizedTask;
  const reviewProvenance = response?.review_provenance || currentTask?.review_provenance || member?.review_provenance || (Array.isArray(response?.review_history) ? record(response.review_history.at(-1)?.provenance) as ReviewEvidenceProvenance : undefined);
  const currentJobs = Array.isArray(currentTask?.jobs) ? currentTask.jobs : [];
  const failedJob = [...currentJobs].reverse().find(job => String(job.status || "").toLowerCase() === "failed" || Boolean(job.error));
  const failureJobId = idOf(failedJob?.job_id || failedJob?.id || currentTask?.job_id);
  const reviewProcessingStatus = currentTask ? reviewProcessingLabel(currentTask) : "Review processing: not recorded";
  const reviewAssessmentStatus = currentTask ? reviewAssessmentLabel(currentTask, review) : "Not recorded";
  const summary = currentTask ? taskSummary(currentTask) : undefined;
  const filteredTasks = useMemo(() => {
    const query = taskSearch.trim().toLowerCase();
    if (!query) return tasks;
    return tasks.filter(row => {
      const review = reviewFor(row);
      const searchable = [row.title, row.task_id, row.instruction, ...episodesOf(review).flatMap(episode => [labelFor(episode), displayedLabel(labelFor(episode))])].map(value => String(value || "").toLowerCase());
      return searchable.some(value => value.includes(query));
    });
  }, [tasks, taskSearch]);
  const currentTaskIndex = tasks.findIndex(row => taskKey(row) === taskId && (!selectedMemberId || idOf(row.member_id) === selectedMemberId));
  const moveToTask = (nextTaskId: string, nextStepId = "", nextMemberId = "") => {
    if (!nextTaskId) return;
    setTaskPickerOpen(false);
    setStepPickerOpen(false);
    const query = new URLSearchParams();
    if (nextMemberId) query.set("member_id", nextMemberId);
    if (nextStepId) query.set("step_id", nextStepId);
    navigate(`/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(nextTaskId)}${query.size ? `?${query.toString()}` : ""}`);
  };
  const alignScreenshot = () => screenshotRef.current?.scrollIntoView({ block: "start" });
  const changeStep = (nextIndex: number) => {
    const boundedIndex = Math.max(0, Math.min(steps.length - 1, nextIndex));
    setStepIndex(boundedIndex);
    setStepPickerOpen(false);
    const nextId = steps[boundedIndex] ? stepId(steps[boundedIndex]) : "";
    const nextParams = new URLSearchParams(searchParams);
    if (selectedMemberId) nextParams.set("member_id", selectedMemberId);
    if (nextId) nextParams.set("step_id", nextId);
    else nextParams.delete("step_id");
    setSearchParams(nextParams, { replace: true });
    requestAnimationFrame(alignScreenshot);
  };
  const stepById = (id: string) => {
    const found = steps.findIndex(step => stepId(step) === id);
    if (found >= 0) changeStep(found);
  };
  const submitFeedback = async () => {
    if (!feedbackText.trim() || !taskId) return;
    setFeedbackBusy(true); setFeedbackError(""); setFeedbackNotice("");
    try {
    const created = await apiRequest<AnyRecord>(`/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(taskId)}/feedback${selectedMemberQuery}`, { method: "POST", body: JSON.stringify({ text: feedbackText.trim(), ...(selectedStepId ? { step_id: selectedStepId } : {}) }) });
      setFeedback(current => [...current, created.feedback && typeof created.feedback === "object" ? created.feedback as AnyRecord : created]);
      setFeedbackText(""); setFeedbackNotice("Feedback recorded.");
    } catch (reason) { setFeedbackError(reason instanceof Error ? reason.message : "Feedback could not be recorded."); }
    finally { setFeedbackBusy(false); }
  };
  const selectedReviewStep = (review?.steps || []).find(item => idOf(item.step_id) === selectedStepId);
  const provenance = record(reviewProvenance);
  const suppliedImageIds = stepRefs(provenance.supplied_image_step_ids);
  const citedImageIds = stepRefs(provenance.cited_image_step_ids);
  const sourceImageIds = stepRefs(provenance.source_image_step_ids);
  const evidenceMode = String(provenance.evidence_mode || "");
  const deliveryRecorded = Array.isArray(provenance.supplied_image_step_ids) || evidenceMode === "text_only";
  const screenshotWasSent = suppliedImageIds.includes(selectedStepId);
  const screenshotCitationCount = citedImageIds.includes(selectedStepId) ? 1 : 0;
  const cannotConfirmFromEvidence = String(selectedReviewStep?.review_status || "").toLowerCase() === "insufficient_evidence";
  const stepRoles = selectedStepId ? rolesForStep(selectedStepId, steps, episodes, review) : [];
  const problemIdsAtSelectedStep = new Set(stepRoles.map(role => role.episodeId));
  const selectedProblemEpisodes = episodes.filter(episode => problemIdsAtSelectedStep.has(getEpisodeId(episode)));
  const screenshotUrl = selectedStep?.screenshot_url?.startsWith("/api/artifacts/") ? selectedStep.screenshot_url : undefined;
  const sourceScreenshotRecorded = selectedStep?.artifact_status === "missing" || sourceImageIds.includes(selectedStepId) || Boolean(selectedStep?.screenshot || selectedStep?.screenshot_path || selectedStep?.artifact_id || screenshotUrl);
  const sourceScreenshotAvailable = selectedStep?.artifact_status !== "missing" && (sourceImageIds.includes(selectedStepId) || Boolean(selectedStep?.screenshot || selectedStep?.screenshot_path || selectedStep?.artifact_id || screenshotUrl));
  const exportBase = `/api/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(taskId)}/export`;
  const exportHref = (format: "yaml" | "json") => `${exportBase}?${new URLSearchParams({ format, ...(selectedMemberId ? { member_id: selectedMemberId } : {}) }).toString()}`;
  const recordedRawUrl = text(currentTask?.raw_url ?? member?.raw_url ?? response?.raw_url, "");

  if (batch.loading || tasksState.loading || detailState.loading) return <LoadingState label="Loading saved trajectory and review evidence…" />;
  if (batch.error) return <ErrorState message={batch.error} onRetry={batch.reload} />;
  if (tasksState.error) return <ErrorState message={tasksState.error} onRetry={tasksState.reload} />;
  if (detailState.error) return <ErrorState message={detailState.error} onRetry={detailState.reload} />;
  if (!currentTask) return <EmptyState title="Task trajectory not found" description="This run task may no longer be available, or access may have changed." action={<Button component={RouterLink} to={`/runs/${encodeURIComponent(batchId)}`} variant="outlined">Back to run</Button>} />;
  const pinnedRelease = (batchRecord?.taxonomy_release || taxonomyState.data?.releases?.find(item => String(item.id) === String(batchRecord?.taxonomy_release_id)) || {}) as AnyRecord;
  const pinnedLabels = Array.isArray(pinnedRelease.labels) ? pinnedRelease.labels as AnyRecord[] : Array.isArray(record(pinnedRelease.content).labels) ? record(pinnedRelease.content).labels as AnyRecord[] : [];
  const draftProposals = taxonomyState.data?.proposals || [];

  const datasetRecord = datasetState.data?.dataset || datasetState.data as AnyRecord | null;
  const datasetName = String(datasetRecord?.name || sourceDatasets[0]?.name || "Dataset");
  const sourceScreenshotMissing = selectedStep?.artifact_status === "missing" || (!screenshotUrl && Boolean(selectedStep?.screenshot || selectedStep?.screenshot_path || selectedStep?.artifact_id));
  const screenshotMessage = screenshotUrl
    ? screenshotLoadFailed ? "Screenshot source exists, but it could not be loaded." : ""
    : sourceScreenshotAvailable ? "A source screenshot is available, but this review did not receive a viewer URL."
      : sourceScreenshotMissing ? "Screenshot file is missing from the saved source."
      : "No screenshot was recorded for this step.";

  const stepNavigator = <>
          <Button fullWidth variant="outlined" startIcon={<SearchRounded />} onClick={() => setTaskPickerOpen(true)} sx={{ my: 1, justifyContent: "flex-start" }}>Search tasks in run</Button>
          <Stack direction="row" gap={.6} flexWrap="wrap" sx={{ mb: 1.2 }}><Chip size="small" label={`${summary?.problemCount ?? "Not recorded"} problems`} /><Chip size="small" label={`${summary?.flaggedCount ?? "Not recorded"} flagged steps`} /><Chip size="small" label={`${summary?.recoveryCount ?? "Not recorded"} recovery steps`} /></Stack>
          <Divider sx={{ mb: 1 }} />
          <Typography color="text.secondary" sx={{ px: .6, mb: .7, fontSize: 12.5, fontWeight: 700 }}>RECORDED STEPS</Typography>
          {!steps.length ? <Typography color="text.secondary" sx={{ px: .6, py: 1, fontSize: 13 }}>No trajectory steps recorded.</Typography> : <Stack ref={stepListRef} gap={.45} sx={{ maxHeight: compactSteps ? "none" : "min(60vh, 680px)", overflowY: "auto", pr: .25 }}>
            {steps.map((step, index) => {
              const id = stepId(step);
              const roles = rolesForStep(id, steps, episodes, review);
              const selected = index === stepIndex;
              return <Button disableRipple key={`${id || "missing"}-${index}`} onClick={() => changeStep(index)} aria-current={selected ? "step" : undefined} variant="text" color="inherit" sx={theme => ({ display: "block", flexShrink: 0, textAlign: "left", p: 1, textTransform: "none", border: "1px solid", borderColor: selected ? "primary.main" : "divider", borderRadius: 1.5, bgcolor: selected ? alpha(theme.palette.primary.main, .075) : "transparent", color: "text.primary", "&:hover": { bgcolor: "action.hover" } })}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" gap={.5}><Typography sx={{ fontWeight: 700, fontSize: 13 }}>Step {id || index + 1}</Typography>{roles.length > 0 && <Typography color="text.secondary" sx={{ fontSize: 11.5 }}>{roles.length} flag{roles.length === 1 ? "" : "s"}</Typography>}</Stack>
                <Typography sx={{ color: "text.secondary", mt: .3, fontSize: 12.5, overflowWrap: "anywhere", display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2, overflow: "hidden" }}>{text(step.action, text(step.intent, "Action not recorded"))}</Typography>{roles.length > 0 && <Stack component="span" gap={.5} sx={{ mt: .75 }}>{roles.map(role => { const episode = episodes.find(item => getEpisodeId(item) === role.episodeId); const anchor = episode ? firstProblemAnchor(currentTask, episode) : ""; return <StepFlag key={`${role.episodeId}-${role.kind}`} kind={role.kind === "recovery" ? "recovery" : role.kind === "related" ? "related" : "problem"} number={role.number} label={episode ? resolveEpisodeLabel(episode, pinnedLabels, draftProposals).displayName : "Problem flagged"} relation={`${roleBadgeLabel(role.kind, role.firstObserved)}${role.kind !== "first" && anchor ? `, starts at step ${anchor}` : ""}`} />; })}</Stack>}
              </Button>;
            })}
          </Stack>}
          <Divider sx={{ my: 1.1 }} />
          <Typography color="text.secondary" sx={{ px: .6, mb: .8, fontSize: 12.5, fontWeight: 700 }}>PROBLEMS</Typography>
          {!!episodes.length && <Typography color="text.secondary" sx={{ px: .6, mb: .9, fontSize: 12.5, lineHeight: 1.5 }}>
            “First observed” marks the agent’s earliest identified step in a version 2 review; “First flagged” marks the earliest explicit flag in a legacy review. A recovery link records an attempted fix or recovery evidence, not proof of success. Related steps add context without starting a new problem.
          </Typography>}
          {!review ? <Typography color="text.secondary" sx={{ px: .6, py: .5, fontSize: 13 }}>Not recorded</Typography> : !episodes.length ? <Typography color="text.secondary" sx={{ px: .6, py: .5, fontSize: 13 }}>No problems recorded in this review.</Typography> : <Stack gap={.8}>{episodes.map((episode, index) => <EpisodeCard key={getEpisodeId(episode) || index} episode={episode} index={index} steps={steps} review={review} labels={pinnedLabels} proposals={draftProposals} onStep={stepById} />)}</Stack>}
  </>;

  return <Box className="trajectory-page">
    <Stack direction="row" justifyContent="space-between" alignItems="center" gap={1} sx={{ mb: 1.5 }}>
      <Button component={RouterLink} to={`/runs/${encodeURIComponent(batchId)}`} startIcon={<ArrowBackRounded />} sx={{ px: 0 }}>Back to run</Button>
      <Stack direction="row" gap={.7} flexWrap="wrap" justifyContent="flex-end">
        <Button size="small" variant="outlined" href={exportHref("yaml")} startIcon={<OpenInNewRounded />}>Export YAML</Button>
        <Button size="small" variant="outlined" href={exportHref("json")}>Export JSON</Button>
        {recordedRawUrl && <Button size="small" variant="text" href={recordedRawUrl}>Raw record</Button>}
      </Stack>
    </Stack>
    {record(currentTask.provenance).saved_replay === true || (Array.isArray(response?.review_history) && record(response.review_history.at(-1)).backend === "saved_replay") ? <Alert severity="info" sx={{ mb: 1.5 }}><strong>Saved replay.</strong> This review reuses retained evidence and made no new model calls.</Alert> : <Alert severity="info" sx={{ mb: 1.5 }}>The viewer displays the saved task and review. Opening evidence does not start new model calls.</Alert>}
    <PageBreadcrumbs items={[{ label: "Datasets", to: "/datasets" }, { label: datasetName, to: datasetId ? `/datasets/${encodeURIComponent(datasetId)}` : undefined }, { label: currentTask.title || currentTask.task_id, to: datasetId ? `/datasets/${encodeURIComponent(datasetId)}/tasks/${encodeURIComponent(String(currentTask.task_definition_id || taskId))}` : undefined }, { label: "Review" }]} />
    <PageHeader eyebrow="TRAJECTORY REVIEW" title={currentTask.title || currentTask.task_id} description={`${currentTask.task_id} · ${batchRecord?.name || "Run"}`} action={<Stack gap={.7} alignItems="flex-start"><BenchmarkResult task={currentTask} compact /><StatusTag value={reviewProcessingStatus} /><StatusTag value={`Review assessment: ${reviewAssessmentStatus}`} /></Stack>} />
    <Panel sx={{ mb: 2, p: { xs: 1.2, md: 1.5 } }}>
      <Stack direction={{ xs: "column", md: "row" }} alignItems={{ md: "center" }} justifyContent="space-between" gap={1.2}>
        <Stack direction="row" alignItems="center" gap={1.2} flexWrap="wrap"><Button variant="outlined" onClick={() => setTaskPickerOpen(true)} startIcon={<SearchRounded />}>Choose task</Button><Typography sx={{ fontWeight: 650, fontSize: 12, overflowWrap: "anywhere" }}>{currentTask.task_id}</Typography><StatusTag value={review?.review_kind || member?.review_kind || "Review kind: not recorded"} /><StatusTag value={reviewProcessingStatus} /></Stack>
        <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap"><Button size="small" variant="outlined" startIcon={<ArrowBackRounded />} disabled={currentTaskIndex <= 0} onClick={() => { const previous = tasks[currentTaskIndex - 1]; if (previous) moveToTask(taskKey(previous), "", idOf(previous.member_id)); }}>Previous task</Button><Typography color="text.secondary" sx={{ fontSize: 13 }}>{Math.max(0, currentTaskIndex + 1)} / {tasks.length}</Typography><Button size="small" variant="outlined" endIcon={<ArrowForwardRounded />} disabled={currentTaskIndex < 0 || currentTaskIndex >= tasks.length - 1} onClick={() => { const next = tasks[currentTaskIndex + 1]; if (next) moveToTask(taskKey(next), "", idOf(next.member_id)); }}>Next task</Button></Stack>
      </Stack>
    </Panel>
    {failedJob && <Alert severity="error" sx={{ mb: 2 }}>Review processing failed: {reviewProcessingError(failedJob.error)}{failureJobId && <> · <Link component={RouterLink} to={`/jobs/${encodeURIComponent(failureJobId)}`} color="inherit" fontWeight={700}>Job details</Link></>}</Alert>}
    {requestedStepId && !steps.some(step => stepId(step) === requestedStepId) && <Alert severity="warning" sx={{ mb: 2 }}>Step {requestedStepId} was requested, but it is not available in this recorded trajectory. The exact requested step ID remains in the address.</Alert>}

    <Stack direction={{ xs: "column", lg: "row" }} gap={2} alignItems="stretch">
      {!compactSteps && <Paper elevation={0} sx={{ width: sidebarOpen ? 304 : 72, flex: "0 0 auto", border: "1px solid", borderColor: "divider", borderRadius: 2, p: 1, alignSelf: "flex-start" }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between"><Typography sx={{ fontWeight: 700, fontSize: 13, pl: .5 }}>{sidebarOpen ? "Task and steps" : "Steps"}</Typography><IconButton size="small" aria-label={sidebarOpen ? "Collapse task and step sidebar" : "Expand task and step sidebar"} onClick={() => setSidebarOpen(value => !value)}>{sidebarOpen ? <ExpandLessRounded /> : <ExpandMoreRounded />}</IconButton></Stack>
        <Collapse in={sidebarOpen} unmountOnExit>{stepNavigator}</Collapse>
      </Paper>}

      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Panel sx={{ mb: 2 }}>
          <Stack ref={screenshotRef} direction={{ xs: "column", sm: "row" }} alignItems={{ xs: "stretch", sm: "center" }} justifyContent="space-between" gap={1} sx={{ mb: 1.2, scrollMarginTop: 16 }}>
            <Box><SectionTitle title={selectedStep ? `Step ${selectedStepId || stepIndex + 1}` : "Trajectory evidence"} subtitle={selectedStep ? `${stepIndex + 1} of ${steps.length} recorded steps` : "No saved trajectory step is available."} /></Box>
            <Stack direction="row" gap={.7} flexWrap="wrap" justifyContent={{ xs: "flex-start", sm: "flex-end" }}>{compactSteps ? <Button size="small" variant="outlined" startIcon={<FormatListNumberedRounded />} onClick={() => setStepPickerOpen(true)}>All steps</Button> : <Button size="small" variant="text" onClick={alignScreenshot}>Screen ↑</Button>}<Button size="small" variant="outlined" startIcon={<ArrowBackRounded />} disabled={stepIndex <= 0} onClick={() => changeStep(stepIndex - 1)}>Previous</Button><Button size="small" variant="outlined" endIcon={<ArrowForwardRounded />} disabled={stepIndex >= steps.length - 1} onClick={() => changeStep(stepIndex + 1)}>Next</Button></Stack>
          </Stack>
          {selectedStep && <>
              <Box sx={{ width: "100%", minHeight: screenshotUrl && !screenshotLoadFailed ? { xs: 140, md: 260 } : 112, maxHeight: "72vh", display: "grid", placeItems: "center", overflow: "auto", bgcolor: "action.hover", border: "1px solid", borderColor: "divider", borderRadius: 2.5 }}>
              {screenshotUrl && !screenshotLoadFailed ? <Link href={screenshotUrl} target="_blank" rel="noopener noreferrer" aria-label={`Open screenshot for step ${selectedStepId} at full size`} sx={{ display: "block", width: "100%", lineHeight: 0, cursor: "zoom-in" }}><Box component="img" src={String(screenshotUrl)} alt={`Recorded screenshot for step ${selectedStepId}`} className="screenshot-full" sx={{ maxHeight: "72vh", objectFit: "contain" }} onError={() => setScreenshotLoadFailed(true)} /></Link> : null}
              {screenshotMessage && <Typography sx={{ px: 2, py: 2, color: sourceScreenshotMissing ? "text.secondary" : "text.secondary", textAlign: "center", fontSize: 13 }}>{screenshotMessage}</Typography>}
            </Box>
            {screenshotUrl && !screenshotLoadFailed && <Link href={screenshotUrl} target="_blank" rel="noopener noreferrer" sx={{ display: "inline-flex", alignItems: "center", gap: .5, mt: .7, fontSize: 12 }}>Open screenshot at full size<OpenInNewRounded sx={{ fontSize: 14 }} /></Link>}
            <Box sx={{ pt: 1.7 }}>
              <Stack direction="row" gap={.65} flexWrap="wrap" sx={{ mb: 1 }}>
                <Chip size="small" variant="outlined" color={sourceScreenshotAvailable ? "success" : "default"} label={`Source screenshot: ${sourceScreenshotAvailable ? "available" : sourceScreenshotRecorded ? "file missing" : "not recorded"}`} />
                <Chip size="small" variant="outlined" color={deliveryRecorded && screenshotWasSent ? "success" : "default"} label={`Sent to reviewer: ${deliveryRecorded ? screenshotWasSent ? "yes" : "no" : "not recorded"}`} />
                <Chip size="small" variant="outlined" color={screenshotCitationCount ? "info" : "default"} label={`Cited by assessment: ${Array.isArray(provenance.cited_image_step_ids) || evidenceMode === "text_only" ? screenshotCitationCount ? "yes" : "no" : "not recorded"}`} />
              </Stack>
              {(deliveryRecorded && screenshotWasSent) && <Typography color="text.secondary" sx={{ mb: 1, fontSize: 12.5 }}>A screenshot sent to the reviewer does not establish whether it was examined.</Typography>}
              {cannotConfirmFromEvidence && <Alert severity="warning" sx={{ mb: 1.2 }}>Cannot confirm from evidence. The saved review marked this step as insufficient evidence.</Alert>}
              {stepRoles.length > 0 && <Stack direction="row" gap={.7} flexWrap="wrap" sx={{ mb: 1.2 }}>{stepRoles.map(role => <Chip key={`${role.episodeId}-${role.kind}`} color={role.kind === "recovery" ? "success" : "warning"} label={`Problem ${role.number}: ${roleBadgeLabel(role.kind, role.firstObserved)}`} />)}</Stack>}
              {selectedProblemEpisodes.length > 0 && <Stack gap={.8} sx={{ mb: 1.2 }}>{selectedProblemEpisodes.map((episode, index) => {
                const resolved = resolveEpisodeLabel(episode, pinnedLabels, draftProposals);
                return <Paper key={getEpisodeId(episode) || index} variant="outlined" sx={{ p: 1.1, borderRadius: 2, bgcolor: "background.paper" }}><Stack direction="row" gap={.8} alignItems="center" flexWrap="wrap"><Typography sx={{ fontWeight: 750, fontSize: 14 }}>Problem {Number(episode.problem_number) || episodes.indexOf(episode) + 1}</Typography><LabelChip id={resolved.id} label={resolved.displayName} /></Stack><Typography color="text.secondary" sx={{ mt: .5, fontSize: 13 }}>{labelDefinitionText(resolved)}</Typography></Paper>;
              })}</Stack>}
              <Stack direction={{ xs: "column", md: "row" }} gap={1.2}>
                <DetailField label="Intent" value={text(selectedReviewStep?.intent ?? selectedStep.intent)} />
                <DetailField label="Action" value={text(selectedStep.action)} />
                <DetailField label="Observation" value={text(selectedReviewStep?.observed_ui ?? selectedStep.observation ?? selectedStep.observed_ui)} />
              </Stack>
              {selectedReviewStep && <Stack direction={{ xs: "column", md: "row" }} gap={1.2} sx={{ mt: 1.2 }}><DetailField label="Effect" value={text(selectedReviewStep.effect)} /><DetailField label="Assessment" value={text(selectedReviewStep.assessment)} /><DetailField label="Review status" value={text(selectedReviewStep.review_status)} /></Stack>}
              {Array.isArray(selectedStep.evidence_refs) && selectedStep.evidence_refs.length > 0 && <Typography color="text.secondary" sx={{ mt: 1.1, fontSize: 12.5 }}>Recorded evidence references: {selectedStep.evidence_refs.map(item => text(item)).join(", ")}</Typography>}
            </Box>
          </>}
        </Panel>

        {!review ? <Alert severity="warning" sx={{ mb: 2 }}>Review data: Not recorded. This does not mean the task has zero issues.</Alert> : <Panel sx={{ mb: 2 }}><SectionTitle title="Review summary" subtitle={text(review.review_kind, "Review kind not recorded")} /><Typography sx={{ whiteSpace: "pre-wrap" }}>{text(review.summary, "No review summary recorded.")}</Typography><Stack direction="row" gap={.7} flexWrap="wrap" sx={{ mt: 1.2 }}><StatusTag value={review.result} /><StatusTag value={review.review_kind} />{review.schema_version && <Chip size="small" variant="outlined" label={`Schema v${review.schema_version}`} />}</Stack>{Array.isArray(review.coverage_notes) && !!review.coverage_notes.length && <Box sx={{ mt: 1.2 }}><Typography sx={{ fontWeight: 700, mb: .3 }}>Coverage notes</Typography>{review.coverage_notes.map((note, index) => <Typography key={index} color="text.secondary" sx={{ fontSize: 13 }}>{text(note)}</Typography>)}</Box>}</Panel>}

        <Panel sx={{ mb: 2 }}><SectionTitle title="Record reviewer feedback" subtitle="Feedback is attached to the selected task and step." />{feedbackError && <Alert severity="error" sx={{ mb: 1 }}>{feedbackError}</Alert>}{feedbackNotice && <Alert severity="success" sx={{ mb: 1 }}>{feedbackNotice}</Alert>}<Stack direction={{ xs: "column", sm: "row" }} gap={1} alignItems="flex-start"><TextField fullWidth multiline minRows={2} label="Feedback" value={feedbackText} onChange={event => setFeedbackText(event.target.value)} /><Button variant="contained" disabled={feedbackBusy || !feedbackText.trim()} onClick={() => void submitFeedback()}>{feedbackBusy ? "Saving…" : "Save feedback"}</Button></Stack>{feedback.length > 0 && <Stack gap={.7} sx={{ mt: 1.5 }}>{feedback.map((entry, index) => <Paper key={String(entry.id || index)} variant="outlined" sx={{ p: 1.2, borderRadius: 2 }}><Typography sx={{ whiteSpace: "pre-wrap" }}>{text(entry.text || entry.feedback, "Feedback text not recorded")}</Typography><Typography color="text.secondary" sx={{ mt: .4, fontSize: 12 }}>{text(entry.actor_name || entry.actor_email, "Reviewer")} · {formatDate(entry.created_at)}{entry.step_id ? ` · Step ${entry.step_id}` : ""}</Typography></Paper>)}</Stack>}</Panel>
      </Box>
    </Stack>

    <Dialog open={stepPickerOpen && compactSteps} fullScreen disableRestoreFocus slotProps={{ transition: { onExited: alignScreenshot } }} onClose={() => setStepPickerOpen(false)}><DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", py: 1.2 }}>Choose a step<IconButton aria-label="Close step picker" onClick={() => setStepPickerOpen(false)}><CloseRounded /></IconButton></DialogTitle><DialogContent dividers sx={{ p: 1.5 }}>{stepNavigator}</DialogContent></Dialog>
    <Dialog open={taskPickerOpen} onClose={() => setTaskPickerOpen(false)} fullWidth fullScreen={compactSteps} maxWidth="md">
      <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 1 }}>Choose a task in this run<IconButton onClick={() => setTaskPickerOpen(false)} aria-label="Close task selector"><CloseRounded /></IconButton></DialogTitle>
      <DialogContent dividers>
        <TextField autoFocus fullWidth value={taskSearch} onChange={event => setTaskSearch(event.target.value)} placeholder="Search task name, ID, instruction, or label" InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded /></InputAdornment> }} sx={{ mb: 1.5 }} />
        {!filteredTasks.length ? <Typography color="text.secondary" sx={{ py: 3, textAlign: "center" }}>No tasks match this search.</Typography> : <Stack gap={1}>{filteredTasks.map((row, index) => {
          const taskIdValue = taskKey(row);
          const rowSummary = taskSummary(row);
          const rowReview = reviewFor(row);
          const rowMemberId = idOf(row.member_id);
          const active = taskIdValue === taskId && (!selectedMemberId || rowMemberId === selectedMemberId);
          const taskLinkGroups = rowSummary.episodes.map((episode, episodeIndex) => {
            const links = taskProblemLinks(row, episode);
            return {
              episode,
              number: Number(episode.problem_number) || episodeIndex + 1,
              anchorId: firstProblemAnchor(row, episode),
              flagged: links.filter(link => link.role.startsWith("First ") || link.role.startsWith("Also ")),
              recovery: links.filter(link => link.role === "Recovery step"),
              related: links.filter(link => link.role === "Related step"),
            };
          });
          const taskPath = `/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(taskIdValue)}${rowMemberId ? `?member_id=${encodeURIComponent(rowMemberId)}` : ""}`;
          return <Paper key={`${taskIdValue}-${rowMemberId || index}`} variant="outlined" sx={theme => ({ p: 1.5, borderRadius: 2, position: "relative", borderColor: active ? "primary.main" : "divider", bgcolor: active ? alpha(theme.palette.primary.main, .075) : "background.paper", "&:hover": { borderColor: "primary.main" }, "&:has(a:focus-visible)": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 } })}>
            <Stack direction={{ xs: "column", sm: "row" }} gap={1.2} alignItems={{ sm: "center" }}>
              <Avatar sx={{ width: 38, height: 38, bgcolor: outcomeLabel(taskOutcome(row)).toLowerCase().includes("fail") ? "error.light" : "primary.light", color: "primary.dark", fontWeight: 800 }}>{index + 1}</Avatar>
              <Box sx={{ flex: 1, minWidth: 0 }}><Typography component={RouterLink} to={taskPath} onClick={() => setTaskPickerOpen(false)} className="task-card-title" sx={{ fontWeight: 650, color: "text.primary", textDecoration: "none", overflowWrap: "anywhere", "&::after": { content: '""', position: "absolute", inset: 0, borderRadius: 2, zIndex: 1 } }}>{row.title || taskIdValue}</Typography><Typography color="text.secondary" sx={{ fontSize: 12.5, overflowWrap: "anywhere" }}>{taskIdValue} · {row.steps?.length ?? row.total_steps ?? "Not recorded"} source steps</Typography><Stack direction="row" gap={.55} flexWrap="wrap" sx={{ mt: .8 }}><BenchmarkResult task={row} compact /><StatusTag value={reviewProcessingLabel(row)} /><StatusTag value={`Review assessment: ${reviewAssessmentLabel(row, rowReview)}`} /><Chip size="small" variant="outlined" label={`${rowSummary.problemCount} problems`} /><Chip size="small" variant="outlined" label={`${rowSummary.flaggedCount} flagged steps`} /><Chip size="small" variant="outlined" label={`${rowSummary.recoveryCount} recovery steps`} /><Chip size="small" variant="outlined" label={`${rowSummary.labelCount} labels`} /></Stack>
                {!!rowSummary.labels.length && <Stack direction="row" gap={.55} flexWrap="wrap" sx={{ mt: .8 }}>{rowSummary.labels.map(group => <LabelChip key={group.id || group.label} id={group.id} label={group.label} count={group.count} />)}</Stack>}
                {!!taskLinkGroups.some(group => group.flagged.length || group.recovery.length || group.related.length) && <Stack gap={.9} sx={{ mt: .9 }}>{taskLinkGroups.filter(group => group.flagged.length || group.recovery.length || group.related.length).map(({ episode, number, anchorId, flagged, recovery, related }) => {
                  const renderStepChip = (stepIdValue: string, label: string, key: string) => {
                    const missing = Array.isArray(row.steps) && !row.steps.some(step => stepId(step) === stepIdValue);
                    return <Chip key={key} size="small" component="button" clickable={!missing} disabled={missing} color={missing ? "error" : undefined} variant="outlined" label={missing ? `Step ${stepIdValue} unavailable` : `${label} · ${stepIdValue}`} onClick={() => !missing && moveToTask(taskIdValue, stepIdValue, rowMemberId)} sx={{ fontSize: 12, fontWeight: 650, position: "relative", zIndex: 2 }} />;
                  };
                  return <Box key={`${getEpisodeId(episode)}-${number}`}>
                    <Typography color="text.secondary" sx={{ mb: .4, fontSize: 12.5, fontWeight: 700 }}>Problem {number}</Typography>
                    {!!flagged.length && <Stack direction="row" gap={.45} flexWrap="wrap">{flagged.map((link, linkIndex) => renderStepChip(link.id, link.role, `flag-${link.id}-${linkIndex}`))}</Stack>}
                    {!!recovery.length && <Box sx={{ mt: .45 }}><Stack direction="row" gap={.5} alignItems="center" flexWrap="wrap"><Typography color="success.dark" sx={{ fontSize: 12.5, fontWeight: 700 }}>Recovery</Typography>{anchorId ? renderStepChip(anchorId, "First anchor", `recovery-anchor-${anchorId}`) : <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>First anchor: Not recorded</Typography>}</Stack><Stack direction="row" gap={.45} flexWrap="wrap" sx={{ mt: .35 }}>{recovery.map((link, linkIndex) => renderStepChip(link.id, "Recovery step", `recovery-${link.id}-${linkIndex}`))}</Stack></Box>}
                    {!!related.length && <Box component="details" sx={{ mt: .45, position: "relative", zIndex: 2 }}><Box component="summary" sx={{ cursor: "pointer", color: "primary.main", fontSize: 12.5, fontWeight: 650 }}>Related steps · {related.length}</Box><Stack direction="row" gap={.45} flexWrap="wrap" sx={{ mt: .4 }}>{anchorId ? renderStepChip(anchorId, "First anchor", `related-anchor-${anchorId}`) : <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>First anchor: Not recorded</Typography>}{related.map((link, linkIndex) => renderStepChip(link.id, "Related step", `related-${link.id}-${linkIndex}`))}</Stack></Box>}
                  </Box>;
                })}</Stack>}
              </Box>
              <Button variant={active ? "contained" : "outlined"} sx={{ position: "relative", zIndex: 2 }} onClick={() => moveToTask(taskIdValue, "", rowMemberId)}>{active ? "Current task" : "Open task"}</Button>
            </Stack>
          </Paper>;
        })}</Stack>}
      </DialogContent>
    </Dialog>
  </Box>;
}

function roleBadgeLabel(kind: string, observedAnchor: boolean): string {
  if (kind === "first") return observedAnchor ? "First observed here" : "First flagged here";
  if (kind === "onset") return observedAnchor ? "Also observed here" : "Also flagged here";
  if (kind === "recovery") return "Recovery step";
  return "Related step";
}

interface StepRole { episodeId: string; number: number; kind: "first" | "onset" | "recovery" | "related"; firstObserved: boolean; }
function rolesForStep(id: string, trajectory: TrajectoryStep[], episodes: Episode[], review: TaskRecord["review"]): StepRole[] {
  if (!id) return [];
  return episodes.flatMap((episode, index) => {
    const episodeId = getEpisodeId(episode);
    const number = Number(episode.problem_number) || index + 1;
    const explicitOnsets = stepRefs(episode.onset_step_ids);
    const firstObservedId = idOf(episode.first_observed_step_id);
    const firstObserved = String(review?.schema_version) === "2" && Boolean(firstObservedId);
    const anchor = firstObserved ? firstObservedId : explicitOnsets.find(candidate => trajectory.some(step => stepId(step) === candidate)) || explicitOnsets[0] || "";
    const refs = [
      ...trajectory.filter(step => stepId(step) === id).flatMap(step => refsWithRole(step.episode_refs)),
      ...(review?.steps || []).filter(step => idOf(step.step_id) === id).flatMap(step => refsWithRole(step.episode_refs)),
    ];
    const role = refs.find(ref => ref.episodeId === episodeId)?.role;
    const result: StepRole[] = [];
    if (id === anchor) result.push({ episodeId, number, kind: "first", firstObserved });
    else if (explicitOnsets.includes(id) || role === "onset") result.push({ episodeId, number, kind: "onset", firstObserved });
    if (recoveryIds(episode).includes(id) || role === "recovery") result.push({ episodeId, number, kind: "recovery", firstObserved });
    if (relatedIds(episode).includes(id) || role === "related" || (refs.some(ref => ref.episodeId === episodeId) && !explicitOnsets.includes(id) && !recoveryIds(episode).includes(id) && id !== anchor)) result.push({ episodeId, number, kind: "related", firstObserved });
    return result;
  });
}
function EpisodeCard({ episode, index, steps, review, labels, proposals, onStep }: { episode: Episode; index: number; steps: TrajectoryStep[]; review?: TaskRecord["review"]; labels: AnyRecord[]; proposals: AnyRecord[]; onStep: (id: string) => void }) {
  const id = getEpisodeId(episode);
  const observedAnchor = String(review?.schema_version) === "2" && episode.first_observed_step_id !== undefined && episode.first_observed_step_id !== null;
  const onset = stepRefs(episode.onset_step_ids);
  const explicitAnchor = observedAnchor ? idOf(episode.first_observed_step_id) : "";
  const anchorId = explicitAnchor || onset.slice().sort((a, b) => {
    const ai = steps.findIndex(step => stepId(step) === a); const bi = steps.findIndex(step => stepId(step) === b);
    return ai < 0 ? (bi < 0 ? 0 : 1) : bi < 0 ? -1 : ai - bi;
  })[0] || "";
  const recovery = recoveryIds(episode);
  const explicitlyRelated = relatedIds(episode);
  const onsetSet = new Set(onset);
  const recoverySet = new Set(recovery);
  const relatedFromLinks = steps.filter(step => {
    if (!refsWithRole(step.episode_refs).some(ref => ref.episodeId === id)) return false;
    const linkedStep = stepId(step);
    const explicitRole = refsWithRole(step.episode_refs).find(ref => ref.episodeId === id)?.role;
    return explicitRole === "related" || (!onsetSet.has(linkedStep) && !recoverySet.has(linkedStep) && linkedStep !== anchorId);
  }).map(stepId);
  const related = [...new Set([...explicitlyRelated, ...relatedFromLinks])];
  const resolvedLabel = resolveEpisodeLabel(episode, labels, proposals);
  const recordedLabel = resolvedLabel.rawName;
  return <Paper variant="outlined" sx={{ p: 1.1, borderRadius: 2 }}>
    <Stack direction="row" justifyContent="space-between" gap={.6} alignItems="flex-start"><Typography sx={{ fontWeight: 750, fontSize: 13.5 }}>Problem {Number(episode.problem_number) || index + 1}</Typography><StatusTag value={episode.outcome_contribution} /></Stack>
    <Box sx={{ mt: .6 }}><LabelChip id={resolvedLabel.id} label={resolvedLabel.displayName} /></Box>
    <Typography color="text.secondary" sx={{ mt: .6, fontSize: 13 }}>{labelDefinitionText(resolvedLabel)}</Typography>
    <Box component="details" sx={{ mt: .4 }}><Box component="summary" sx={{ cursor: "pointer", color: "primary.main", fontSize: 12.5, fontWeight: 650 }}>Recorded label</Box><Typography color="text.secondary" sx={{ mt: .3, fontSize: 12 }}>Name: {recordedLabel}{episode.label_id ? ` · ID: ${episode.label_id}` : " · ID: Not recorded"}</Typography></Box>
    <Typography color="text.secondary" sx={{ mt: .45, fontSize: 13, whiteSpace: "pre-wrap" }}>{text(episode.mechanism, "Problem description not recorded.")}</Typography>
    <Stack gap={.65} sx={{ mt: .9 }}>
      {!!(onset.length || anchorId) && <Stack direction="row" gap={.45} flexWrap="wrap"><StepJumpChip label={observedAnchor ? "First observed here" : "First flagged here"} id={anchorId} missing={!steps.some(step => stepId(step) === anchorId)} onClick={onStep} /><>{onset.filter(step => step !== anchorId).map((step, i) => <StepJumpChip key={`onset-${step}-${i}`} label={observedAnchor ? "Also observed here" : "Also flagged here"} id={step} missing={!steps.some(item => stepId(item) === step)} onClick={onStep} />)}</></Stack>}
      {!!recovery.length && <Box><Stack direction="row" gap={.45} alignItems="center" flexWrap="wrap"><Typography color="success.dark" sx={{ fontSize: 12.5, fontWeight: 700 }}>Recovery steps</Typography><Typography color="text.secondary" sx={{ fontSize: 12.5 }}>First anchor:</Typography><StepJumpChip label="Step" id={anchorId} missing={!steps.some(item => stepId(item) === anchorId)} onClick={onStep} /></Stack><Stack direction="row" gap={.45} flexWrap="wrap" sx={{ mt: .35 }}>{recovery.map((step, i) => <StepJumpChip key={`recovery-${step}-${i}`} label="Recovery" id={step} missing={!steps.some(item => stepId(item) === step)} onClick={onStep} tone="success" />)}</Stack></Box>}
      {!!related.length && <Box component="details"><Box component="summary" sx={{ cursor: "pointer", color: "primary.main", fontSize: 12.5, fontWeight: 650 }}>Related steps · {related.length}</Box><Stack direction="row" gap={.45} flexWrap="wrap" sx={{ mt: .4 }}><Typography color="text.secondary" sx={{ fontSize: 12.5, alignSelf: "center" }}>First anchor:</Typography><StepJumpChip label="Step" id={anchorId} missing={!steps.some(item => stepId(item) === anchorId)} onClick={onStep} />{related.map((step, i) => <StepJumpChip key={`related-${step}-${i}`} label="Related" id={step} missing={!steps.some(item => stepId(item) === step)} onClick={onStep} />)}</Stack></Box>}
      {!anchorId && !onset.length && !recovery.length && !related.length && <Typography color="text.secondary" sx={{ fontSize: 13 }}>No exact step links recorded.</Typography>}
    </Stack>
    <Typography color="text.secondary" sx={{ display: "block", mt: .8, fontSize: 12 }}>Recovery: {text(record(episode.recovery).status, "Not recorded")}{record(episode.recovery).rationale ? ` · ${text(record(episode.recovery).rationale)}` : ""}</Typography>
    {episode.uncertainty && <Typography color="text.secondary" sx={{ mt: .5, fontSize: 12 }}>Uncertainty: {text(episode.uncertainty)}</Typography>}
  </Paper>;
}

function StepJumpChip({ label, id, missing, onClick, tone }: { label: string; id: string; missing: boolean; onClick: (id: string) => void; tone?: "success" }) {
  if (!id) return <Chip size="small" variant="outlined" disabled label={`${label}: Not recorded`} sx={{ fontSize: 12 }} />;
  return <Chip size="small" component="button" clickable={!missing} disabled={missing} color={missing ? "error" : tone} variant="outlined" label={missing ? `Step ${id} unavailable` : `${label} · ${id}`} onClick={() => !missing && onClick(id)} sx={{ fontSize: 12, fontWeight: 650 }} />;
}

function DetailField({ label, value }: { label: string; value: string }) {
  return <Paper variant="outlined" sx={{ p: 1.2, borderRadius: 2, flex: 1, minWidth: 0 }}><Typography color="text.secondary" sx={{ mb: .3, fontSize: 12, fontWeight: 750, textTransform: "uppercase", letterSpacing: ".055em" }}>{label}</Typography><Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 13 }}>{value}</Typography></Paper>;
}
