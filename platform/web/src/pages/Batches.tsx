import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid, LinearProgress, Link, Paper, Stack, Typography } from "@mui/material";
import AddRounded from "@mui/icons-material/AddRounded";
import PlayArrowRounded from "@mui/icons-material/PlayArrowRounded";
import PauseRounded from "@mui/icons-material/PauseRounded";
import SyncRounded from "@mui/icons-material/SyncRounded";
import StopRounded from "@mui/icons-material/StopRounded";
import ArchiveRounded from "@mui/icons-material/ArchiveRounded";
import Inventory2Rounded from "@mui/icons-material/Inventory2Rounded";
import InsightsRounded from "@mui/icons-material/InsightsRounded";
import { apiRequest } from "../api/client";
import { CATALOG_PAGING, RUN_TASK_PAGING } from "../api/pagination";
import type { BatchRecord, ReviewJobRecord, TaskRecord, TaskReviewSummary } from "../api/types";
import { BenchmarkResult } from "../components/BenchmarkResult";
import { PageBreadcrumbs, PageHeader, Panel, SectionTitle } from "../components/Page";
import { RunComposer } from "../components/RunComposer";
import { RunShares } from "../components/RunShares";
import { EmptyState, ErrorState, LoadingState, TruncationNote } from "../components/States";
import { StatusTag } from "../components/StatusTag";
import { useApi } from "../hooks/useApi";
import { benchmarkResultLabel } from "../lib/benchmark";
import { displayValue, formatDate, reviewProcessingError, runStatusLabel } from "../lib/format";
import { asRecord } from "../lib/records";

const linkedCardSx = {
  position: "relative", minWidth: 0, borderRadius: 2,
  transition: "border-color .15s ease, background-color .15s ease",
  "&:hover": { borderColor: "primary.main", bgcolor: "action.hover" },
  "&:has(a:focus-visible)": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 },
} as const;
const cardLinkSx = {
  color: "text.primary", textDecoration: "none", fontWeight: 700, overflowWrap: "anywhere",
  "&::after": { content: '""', position: "absolute", inset: 0, zIndex: 1, borderRadius: 2 },
  "&:focus-visible": { outline: "none" },
} as const;
const independentControlSx = { position: "relative", zIndex: 2 } as const;

type Row = Record<string, unknown>;
interface RunRecord extends BatchRecord {
  source_datasets?: Row[];
  configuration?: Record<string, unknown>;
  archived?: boolean;
  archived_at?: string | null;
}
interface RunTask extends TaskRecord {
  member_id?: string;
  run_member_id?: string;
  total_steps?: number;
  reviewed_steps?: number;
  insufficient_evidence_steps?: number;
  review_kind?: string;
  review_status?: string;
  review_summary?: TaskReviewSummary;
  jobs?: ReviewJobRecord[];
  job_id?: string;
}
interface RunDetailResponse {
  run?: RunRecord;
  batch?: RunRecord;
  progress?: Record<string, unknown>;
  waves?: Row[];
  grants?: Row[];
  [key: string]: unknown;
}
const idOf = (row: Row) => String(row.id || row.run_id || row.batch_id || "");
const finishedCount = (progress: Record<string, unknown>) => Number(progress.completed || 0) + Number(progress.failed || 0) + Number(asRecord(progress.status_counts).cancelled || 0);
const percent = (progress?: Record<string, unknown>) => {
  const total = Number(progress?.total || 0);
  const completed = finishedCount(progress || {});
  return total > 0 ? Math.min(100, Math.round(completed / total * 100)) : 0;
};
const records = <T extends Row>(value: { items?: T[]; total?: number } | T[] | null): T[] => Array.isArray(value) ? value : value?.items || [];
function reviewCoverage(task: RunTask, noReviewProduced = false) {
  if (noReviewProduced) return "No review produced";
  const total = task.total_steps ?? task.steps?.length ?? task.review?.steps?.length;
  const reviewSteps = task.review?.steps || [];
  const reviewed = task.reviewed_steps ?? reviewSteps.filter(step => String(step.review_status).toLowerCase() === "reviewed").length;
  const insufficient = task.insufficient_evidence_steps ?? reviewSteps.filter(step => String(step.review_status).toLowerCase() === "insufficient_evidence").length;
  const summary = task.review_summary || {};
  const provenance = task.review_provenance || {};
  const summarySourceIds = Array.isArray(summary.source_image_step_ids) ? summary.source_image_step_ids.map(String) : undefined;
  const provenanceSourceIds = Array.isArray(provenance.source_image_step_ids) ? provenance.source_image_step_ids.map(String) : undefined;
  const sourceIds = summarySourceIds ?? provenanceSourceIds;
  const steps = task.steps || [];
  const screenshotMetadataSteps = steps.filter(step => Boolean(step.screenshot || step.screenshot_path || step.screenshot_url || step.artifact_id));
  const sourceCountKnown = summary.source_image_count !== undefined || sourceIds !== undefined || steps.length > 0;
  const sourceCount = summary.source_image_count === undefined ? sourceIds?.length ?? screenshotMetadataSteps.length : Number(summary.source_image_count);
  const availableSourceCount = steps.filter(step => step.artifact_status === "recorded" || (step.artifact_status !== "missing" && Boolean(step.screenshot_url))).length;
  const missingSourceCount = steps.filter(step => step.artifact_status === "missing").length;
  const availabilityKnown = steps.some(step => step.artifact_status !== undefined || Boolean(step.screenshot_url));

  const suppliedIds = Array.isArray(summary.supplied_image_step_ids) ? summary.supplied_image_step_ids
    : Array.isArray(provenance.supplied_image_step_ids) ? provenance.supplied_image_step_ids : undefined;
  const sentKnown = summary.supplied_image_count !== undefined || suppliedIds !== undefined || provenance.evidence_mode === "text_only";
  const sentCount = summary.supplied_image_count === undefined ? suppliedIds?.length ?? 0 : Number(summary.supplied_image_count);
  const citedIds = Array.isArray(summary.cited_image_step_ids) ? summary.cited_image_step_ids
    : Array.isArray(provenance.cited_image_step_ids) ? provenance.cited_image_step_ids : undefined;
  const citedKnown = summary.cited_image_count !== undefined || citedIds !== undefined || provenance.evidence_mode === "text_only";
  const citedCount = summary.cited_image_count === undefined ? citedIds?.length ?? 0 : Number(summary.cited_image_count);
  const inspectedIds = Array.isArray(provenance.inspected_image_step_ids) ? provenance.inspected_image_step_ids : undefined;
  const legacyNoDeliveryMetadata = !provenance.evidence_mode && !sentKnown && inspectedIds !== undefined;
  const hasImageMetadata = sourceCountKnown || sentKnown || citedKnown || inspectedIds !== undefined;

  return <Stack gap={.25}>
    <Typography sx={{ fontSize: 12 }}>Model-reported step assessment: {total === undefined ? "not recorded" : `${reviewed} marked reviewed · ${insufficient} marked insufficient evidence (of ${total})`}</Typography>
    {hasImageMetadata && <>
      <Typography sx={{ fontSize: 12 }}>Source screenshots: {sourceCountKnown ? `${sourceCount} recorded` : "not recorded"}{availabilityKnown ? ` · ${availableSourceCount} available${missingSourceCount ? ` · ${missingSourceCount} files missing` : ""}` : ""}</Typography>
      <Typography sx={{ fontSize: 12 }}>Sent to reviewer: {sentKnown ? `${sentCount}` : "not recorded"} · Cited by assessment: {citedKnown ? `${citedCount}` : "not recorded"}{inspectedIds !== undefined ? ` · Model-reported image inspections: ${inspectedIds.length}` : ""}{provenance.evidence_mode === "text_only" ? " · text-only review" : ""}</Typography>
      {legacyNoDeliveryMetadata && <Typography color="text.secondary" sx={{ fontSize: 11.5 }}>Legacy review: image-delivery mode was not recorded. Insufficient-evidence statuses describe the model’s assessment, not missing source screenshots.</Typography>}
    </>}
  </Stack>;
}
function hasReviewAssessment(task: RunTask): boolean {
  return Boolean(task.review && (task.review.result || task.review.summary || task.review.episodes?.length || task.review.steps?.length) || task.review_kind);
}
function reviewMetrics(task: RunTask) {
  const summary = task.review_summary;
  const episodes = Array.isArray(task.review?.episodes) ? task.review.episodes : undefined;
  const flaggedSteps = new Set<string>();
  for (const episode of episodes || []) {
    const onsetIds = Array.isArray(episode.onset_step_ids) ? episode.onset_step_ids.map(String) : [];
    onsetIds.forEach(id => { if (id) flaggedSteps.add(id); });
    const firstObserved = String(episode.first_observed_step_id || "");
    if (firstObserved) flaggedSteps.add(firstObserved);
  }
  if (!flaggedSteps.size && episodes?.length) {
    for (const step of task.review?.steps || []) {
      const refs = Array.isArray(step.episode_refs) ? step.episode_refs : [];
      const hasProblemRole = refs.some(ref => {
        const role = ref && typeof ref === "object" ? String((ref as Record<string, unknown>).role || "").toLowerCase() : "";
        return role === "onset" || role === "first" || role === "flagged" || role === "first_observed";
      });
      if (hasProblemRole && step.step_id !== undefined && step.step_id !== null) flaggedSteps.add(String(step.step_id));
    }
  }
  const labels = new Set((episodes || []).map(episode => String(episode.label_id || episode.label_name || "")).filter(Boolean));
  return {
    problemCount: summary?.problem_count ?? episodes?.length,
    flaggedStepCount: summary?.flagged_step_count ?? (episodes ? flaggedSteps.size : undefined),
    labelCount: summary?.flagged_labels?.length ?? (episodes ? labels.size : undefined),
  };
}
function reviewAssessmentLabel(task: RunTask, noReviewProduced: boolean): string {
  if (noReviewProduced) return "Not available: review processing failed";
  if (!hasReviewAssessment(task)) return "Not recorded";
  const result = String(task.review?.result || "").trim();
  if (result) return result;
  const problemCount = Number(task.review_summary?.problem_count ?? task.review?.episodes?.length ?? 0);
  return problemCount ? "Issues recorded" : "No issues recorded";
}
function taskFailureJob(task: RunTask): ReviewJobRecord | undefined {
  const jobs = task.jobs || [];
  return [...jobs].reverse().find(job => String(job.status || "").toLowerCase() === "failed" || Boolean(job.error))
    || (task.job_id ? { id: task.job_id, error: String(task.review_error || "") } as ReviewJobRecord : undefined);
}
function latestTaskJob(task: RunTask): ReviewJobRecord | undefined { return task.jobs?.at(-1); }
function summaryOutcomeText(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "Benchmark results not recorded";
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) return "Benchmark results not recorded";
  return entries.map(([result, count]) => `${result.replaceAll("_", " ")} ${String(count)}`).join(" · ");
}
function failedJobs(progress: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(progress.failed_jobs) ? progress.failed_jobs as Record<string, unknown>[] : [];
}
function runDescription(run: RunRecord): string {
  const datasets = run.source_datasets || [];
  if (datasets.length) return datasets.map(dataset => String(dataset.name || dataset.dataset_name || dataset.id || "Dataset")).join(", ");
  return String(run.dataset_name || (run.dataset_id ? `Dataset ${run.dataset_id}` : "Selected catalog tasks"));
}
function promptText(workflow: Row): string {
  if (Array.isArray(workflow.stages)) return workflow.stages.map(stage => `${String(stage.name || stage.id)}\n${String(stage.prompt || "")}`).join("\n\n");
  for (const key of ["prompt", "system_prompt", "instructions", "template", "text", "content"]) {
    if (typeof workflow[key] === "string" && String(workflow[key]).trim()) return String(workflow[key]);
  }
  return "The workflow prompt snapshot is not included in this run record.";
}

export function BatchesPage() {
  const [showArchived, setShowArchived] = useState(false);
  const runs = useApi<{ items?: RunRecord[] } | RunRecord[]>(`/runs${showArchived ? "?include_archived=true" : ""}`, 0, CATALOG_PAGING);
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [composerOpen, setComposerOpen] = useState(false);
  const initialDatasetIds = search.get("dataset_id") ? [search.get("dataset_id")!] : [];
  const allRuns = records(runs.data);
  const visibleRuns = useMemo(() => {
    if (!initialDatasetIds.length) return allRuns;
    return allRuns.filter(run => run.dataset_id === initialDatasetIds[0] || run.source_datasets?.some(dataset => String(dataset.id || dataset.dataset_id) === initialDatasetIds[0]));
  }, [allRuns, initialDatasetIds.join("|")]);
  const activeRun = visibleRuns.some(run => ["running", "paused"].includes(String(run.status || run.processing_status).toLowerCase()));
  useEffect(() => {
    if (!activeRun) return;
    const timer = window.setInterval(() => void runs.refreshQuietly(), 3000);
    return () => window.clearInterval(timer);
  }, [activeRun, runs.refreshQuietly]);
  return <>
    <PageHeader eyebrow="RUN CATALOG" title="Runs" description="Each run pins a task selection, workflow revision, and execution configuration. Results and review history remain attached to that run." action={<Stack direction="row" gap={1} flexWrap="wrap"><Button component={RouterLink} to="/analytics" variant="outlined" startIcon={<InsightsRounded />}>Analytics</Button><Button variant="outlined" startIcon={<Inventory2Rounded />} onClick={() => setShowArchived(value => !value)}>{showArchived ? "Hide archived" : "Show archived"}</Button><Button variant="contained" startIcon={<AddRounded />} onClick={() => setComposerOpen(true)}>New run</Button></Stack>} />
    {runs.loading && <LoadingState label="Loading runs…" />}
    {runs.error && <ErrorState message={runs.error} onRetry={runs.reload} />}
    {!runs.loading && !runs.error && !visibleRuns.length && <EmptyState title={showArchived ? "No archived runs" : initialDatasetIds.length ? "No runs use this dataset yet" : "No runs yet"} description={showArchived ? "No archived runs are currently visible." : "Start a run by selecting datasets or tasks, then choose a workflow and execution setup."} action={!showArchived ? <Button variant="contained" startIcon={<AddRounded />} onClick={() => setComposerOpen(true)}>Create a run</Button> : undefined} />}
    {!!visibleRuns.length && <Grid container spacing={1.7}>
      {visibleRuns.map(run => {
        const id = idOf(run);
        const progress = run.progress || {};
        const value = percent(progress);
        const failures = failedJobs(progress);
        const firstFailure = failures[0];
        const firstJobId = String(firstFailure?.job_id || "");
        const runPath = `/runs/${encodeURIComponent(id)}${run.archived || run.archived_at ? "?include_archived=true" : ""}`;
        return <Grid key={id} size={{ xs: 12, md: 6, xl: 4 }}><Paper sx={{ ...linkedCardSx, height: "100%", display: "flex", flexDirection: "column", p: 2, border: "1px solid", borderColor: "divider", bgcolor: "background.paper" }}>
          <Stack gap={1}><Box sx={{ minWidth: 0 }}><Typography component={RouterLink} to={runPath} sx={{ ...cardLinkSx, fontSize: 15, lineHeight: 1.4 }}>{run.name || "Untitled run"}</Typography><Typography color="text.secondary" sx={{ mt: .5, fontSize: 13 }}>{runDescription(run)}</Typography></Box><Stack direction="row" alignItems="center" gap={.6} flexWrap="wrap"><Typography color="text.secondary" sx={{ fontSize: 11.5 }}>Review processing</Typography><StatusTag value={runStatusLabel({ ...run, progress })} /></Stack></Stack>
          <Stack direction="row" gap={.7} flexWrap="wrap" sx={{ mt: 1.5 }}><StatusTag value={run.workflow_name || run.configuration?.workflow_revision_id || run.workflow_revision_id ? `Workflow ${String(run.workflow_name || run.configuration?.workflow_revision_id || run.workflow_revision_id)}` : "Workflow not recorded"} /><StatusTag value={asRecord(run.configuration?.execution_snapshot).backend || run.backend || "Execution not recorded"} /></Stack>
          <Typography color="text.secondary" sx={{ mt: 1.1, fontSize: 12.5 }}><strong>{benchmarkResultLabel(run as Record<string, unknown>)}:</strong> {summaryOutcomeText(progress.outcome_summary)}</Typography>
          <Stack direction="row" alignItems="center" gap={1} sx={{ mt: 1.4 }}><Box sx={{ flex: 1 }}><LinearProgress variant="determinate" value={value} sx={{ height: 8, borderRadius: 6 }} /></Box><Typography sx={{ minWidth: 44, fontSize: 13, fontWeight: 750 }}>{finishedCount(progress)} / {String(progress.total ?? 0)}</Typography></Stack>
          <Typography color="text.secondary" sx={{ mt: .3, fontSize: 12.5 }}>Review processing · {String(progress.completed ?? 0)} completed · {String(progress.running ?? 0)} active · {String(progress.queued ?? 0)} queued · {String(progress.failed ?? 0)} failed</Typography>
          {firstFailure && <Typography color="error.main" sx={{ mt: .8, fontSize: 12.5, overflowWrap: "anywhere" }}>Review processing error: {reviewProcessingError(firstFailure.error)}{firstJobId && <> · <Link component={RouterLink} to={`/jobs/${encodeURIComponent(firstJobId)}`} sx={{ ...independentControlSx, color: "inherit", fontWeight: 700 }}>Job details</Link></>}</Typography>}
          <Typography color="text.secondary" sx={{ mt: "auto", pt: 1.2, fontSize: 12.5 }}>Created {formatDate(run.created_at)} · <Box component="span" sx={{ color: "primary.main", fontWeight: 600 }}>Open run →</Box></Typography>
        </Paper></Grid>;
      })}
    </Grid>}
    <RunComposer open={composerOpen} onClose={() => setComposerOpen(false)} onCreated={id => navigate(`/runs/${encodeURIComponent(id)}`)} initialDatasetIds={initialDatasetIds} />
  </>;
}

export function BatchDetailPage() {
  const { id = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [includeArchived, setIncludeArchived] = useState(searchParams.get("include_archived") === "true");
  useEffect(() => setIncludeArchived(searchParams.get("include_archived") === "true"), [searchParams]);
  const navigate = useNavigate();
  const archiveQuery = includeArchived ? "?include_archived=true" : "";
  const detail = useApi<RunDetailResponse>(id ? `/runs/${encodeURIComponent(id)}${archiveQuery}` : null);
  const tasksState = useApi<{ items?: RunTask[]; total?: number } | RunTask[]>(id ? `/runs/${encodeURIComponent(id)}/tasks${archiveQuery}` : null, 0, RUN_TASK_PAGING);
  const [composerOpen, setComposerOpen] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const nestedRun = detail.data?.run || detail.data?.batch;
  const run = detail.data ? ({ ...asRecord(nestedRun), ...detail.data } as RunRecord) : undefined;
  const tasks = records(tasksState.data);
  const progress = detail.data?.progress || run?.progress || {};
  const status = String(run?.status || run?.processing_status || "unknown").toLowerCase();
  const archived = Boolean(run?.archived || run?.archived_at);
  const runConfig = run?.configuration || {};
  const workflow = asRecord(runConfig.workflow_snapshot || run?.workflow_snapshot);
  const execution = asRecord(runConfig.execution_snapshot || run?.execution_snapshot);
  const sourceDatasets = run?.source_datasets || [];
  const primaryDataset = sourceDatasets[0];
  const datasetId = String(primaryDataset?.id || primaryDataset?.dataset_id || run?.dataset_id || "");
  const datasetName = String(primaryDataset?.name || primaryDataset?.dataset_name || run?.dataset_name || "Dataset");
  const showDatasetBreadcrumb = sourceDatasets.length <= 1;
  useEffect(() => {
    if (!id || !["running", "paused"].includes(status)) return;
    const timer = window.setInterval(() => { void detail.refreshQuietly(); void tasksState.refreshQuietly(); }, 2500);
    return () => window.clearInterval(timer);
  }, [id, status, detail.refreshQuietly, tasksState.refreshQuietly]);
  const runAction = async (action: "pause" | "resume" | "cancel" | "sync" | "archive" | "restore") => {
    setBusy(action); setError(""); setNotice("");
    try {
      const result = await apiRequest<Row>(`/runs/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({}) });
      setNotice(String(result.message || (action === "archive" || action === "restore" ? `Run ${action}d.` : `Run ${action} request completed.`)));
      setConfirmCancel(false);
      if (action === "archive" || action === "restore") { const nextArchived = action === "archive"; setIncludeArchived(nextArchived); setSearchParams(nextArchived ? { include_archived: "true" } : {}, { replace: true }); }
      else { await detail.reload(); await tasksState.reload(); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : `Run ${action} failed.`); }
    finally { setBusy(""); }
  };
  if (detail.loading) return <LoadingState label="Loading run results and provenance…" />;
  if (detail.error) return <ErrorState message={detail.error} onRetry={detail.reload} />;
  if (!detail.data || !run) return <EmptyState title="Run not found" description="This run may have been removed or you may not have access." action={<Button component={RouterLink} to="/runs" variant="outlined">Back to runs</Button>} />;
  const workflowId = String(run.configuration?.workflow_revision_id || run.workflow_revision_id || workflow.id || workflow.revision_id || "Not recorded");
  const executionBackend = String(execution.backend || run.backend || asRecord(run.preset).backend || "Not recorded");
  const progressValue = percent(progress);
  const isTerminal = ["completed", "cancelled", "canceled", "failed"].includes(status);
  return <>
    <PageBreadcrumbs items={[{ label: "Runs", to: "/runs" }, ...(showDatasetBreadcrumb && datasetId ? [{ label: datasetName, to: `/datasets/${encodeURIComponent(datasetId)}` }] : []), { label: run.name || "Run" }]} />
    <PageHeader eyebrow="RUN DETAILS" title={run.name || "Run"} description={run.description || `${runDescription(run)} · Workflow revision ${workflowId}`} action={<Stack direction="row" gap={.8} flexWrap="wrap"><Button component={RouterLink} to={`/analytics?run=${encodeURIComponent(id)}`} variant="outlined" startIcon={<InsightsRounded />}>Analyze run</Button>{!archived && (status === "draft" ? <Button variant="contained" startIcon={<PlayArrowRounded />} onClick={() => setComposerOpen(true)}>Configure and start</Button> : <Button variant="contained" startIcon={<AddRounded />} onClick={() => setComposerOpen(true)}>New run from this selection</Button>)}<Button variant="outlined" startIcon={<ArchiveRounded />} color={archived ? "primary" : "error"} disabled={!!busy} onClick={() => void runAction(archived ? "restore" : "archive")}>{archived ? "Restore run" : "Archive run"}</Button></Stack>} />
    {error && <Alert severity="error" onClose={() => setError("")} sx={{ mb: 1.5 }}>{error}</Alert>}
    {notice && <Alert severity="success" onClose={() => setNotice("")} sx={{ mb: 1.5 }}>{notice}</Alert>}
    {archived && <Alert severity="warning" sx={{ mb: 1.5 }}>This run is archived. Its results remain available.</Alert>}
    <Panel sx={{ mb: 2 }}><Grid container spacing={2} alignItems="center"><Grid size={{ xs: 12, md: 3 }}><Typography color="text.secondary" sx={{ fontSize: 13 }}>Review processing</Typography><StatusTag value={runStatusLabel({ ...run, progress })} /></Grid><Grid size={{ xs: 12, md: 6 }}><Typography color="text.secondary" sx={{ fontSize: 13, mb: .5 }}>Review processing progress (finished tasks)</Typography><Stack direction="row" alignItems="center" gap={1}><Box sx={{ flex: 1 }}><LinearProgress variant="determinate" value={progressValue} sx={{ height: 9, borderRadius: 8 }} /></Box><Typography sx={{ minWidth: 80, fontWeight: 750 }}>{finishedCount(progress)} / {String(progress.total ?? tasks.length)}</Typography></Stack><Typography color="text.secondary" sx={{ mt: .4, fontSize: 12 }}>{String(progress.running ?? 0)} active · {String(progress.queued ?? 0)} queued · {String(progress.retrying ?? 0)} retrying · {String(progress.failed ?? 0)} failed</Typography></Grid><Grid size={{ xs: 12, md: 3 }}><Stack direction="row" gap={.7} flexWrap="wrap">{run.mode === "appendable" && <Button size="small" variant="outlined" startIcon={<SyncRounded />} disabled={!!busy || status === "running"} onClick={() => void runAction("sync")}>Sync source</Button>}{status === "running" ? <Button size="small" variant="outlined" startIcon={<PauseRounded />} disabled={!!busy} onClick={() => void runAction("pause")}>Pause</Button> : status === "paused" ? <Button size="small" variant="contained" startIcon={<PlayArrowRounded />} disabled={!!busy} onClick={() => void runAction("resume")}>Resume</Button> : null}{!isTerminal && <Button size="small" color="error" variant="outlined" startIcon={<StopRounded />} disabled={!!busy} onClick={() => setConfirmCancel(true)}>Cancel run</Button>}</Stack></Grid>
      <Grid size={12}><Stack direction="row" flexWrap="wrap" gap={1}><Chip size="small" variant="outlined" label={`${benchmarkResultLabel(run as Record<string, unknown>)}: ${summaryOutcomeText(progress.outcome_summary)}`} /><Chip size="small" variant="outlined" label={`${String(progress.saved_review_count ?? 0)} review assessments recorded · ${String(progress.missing_review_count ?? 0)} tasks without a review assessment`} /><Chip size="small" variant="outlined" label={`Review processing attempts: ${String(progress.attempt_count ?? 0)} · additional attempts: ${String(progress.retry_count ?? 0)}`} />{progress.planned_allowance_usd !== undefined && <Chip size="small" variant="outlined" label={`Planned allowance, including retries: $${Number(progress.planned_allowance_usd).toFixed(2)} · billing estimate, not a provider spending cap`} />}</Stack></Grid>
    </Grid></Panel>
    {!!failedJobs(progress).length && <Alert severity="error" sx={{ mb: 2 }}><Typography sx={{ fontWeight: 750, mb: .5 }}>Review processing errors</Typography><Stack gap={.35}>{failedJobs(progress).map((job, index) => <Typography key={String(job.job_id || index)} sx={{ fontSize: 13, overflowWrap: "anywhere" }}>Task {String(job.task_id || "not recorded")}: {reviewProcessingError(job.error)} · attempt {String(job.attempt_count ?? "?")}{job.max_attempts !== undefined ? ` / ${String(job.max_attempts)}` : ""}{Boolean(job.job_id) && <> · <Link component={RouterLink} to={`/jobs/${encodeURIComponent(String(job.job_id))}`} color="inherit" fontWeight={700}>Job details</Link></>}</Typography>)}</Stack></Alert>}
    <Grid container spacing={2} alignItems="flex-start">
      <Grid size={{ xs: 12, lg: 7 }}><Stack gap={2}>
        <Panel><SectionTitle title="Task results" subtitle="Benchmark results describe the original task. Review processing describes the queue. Review assessment describes issues and evidence." />
          {tasksState.loading && <LoadingState label="Loading task results…" />}{tasksState.error && <ErrorState message={tasksState.error} onRetry={tasksState.reload} />}
          {!tasksState.loading && !tasksState.error && !tasks.length && <Typography color="text.secondary">No tasks are included in this run.</Typography>}
          <TruncationNote list={tasksState.data} noun="tasks" />
          {!!tasks.length && <Stack gap={1.2}>{tasks.map((task, index) => {
            const taskId = String(task.task_id || task.id || "");
            const memberId = String(task.member_id || task.run_member_id || "");
            const taskPath = `/runs/${encodeURIComponent(id)}/tasks/${encodeURIComponent(taskId)}${memberId ? `?member_id=${encodeURIComponent(memberId)}` : ""}`;
            const processingFailed = String(task.processing_status || task.status || "").toLowerCase() === "failed";
            const noReviewProduced = processingFailed && !hasReviewAssessment(task);
            const failureJob = taskFailureJob(task);
            const latestJob = latestTaskJob(task);
            const jobId = String(failureJob?.id || failureJob?.job_id || task.job_id || "");
            const assessment = reviewAssessmentLabel(task, noReviewProduced);
            const assessmentCounts = reviewMetrics(task);
            return <Paper key={memberId || `${taskId}-${index}`} variant="outlined" sx={{ ...linkedCardSx, p: 1.5 }}>
              <Typography component={RouterLink} to={taskPath} sx={{ ...cardLinkSx, fontSize: 14, lineHeight: 1.45 }}>{task.title || taskId}</Typography>
              <Typography color="text.secondary" sx={{ mt: .25, fontSize: 11.5, overflowWrap: "anywhere" }}>{taskId}</Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" }, gap: 1.4, mt: 1.3, pt: 1.2, borderTop: "1px solid", borderColor: "divider" }}>
                <Box sx={{ minWidth: 0 }}><Typography color="text.secondary" sx={{ fontSize: 11.5, fontWeight: 600, mb: .4 }}>Original task result</Typography><BenchmarkResult task={task} compact /></Box>
                <Box sx={{ minWidth: 0 }}><Typography color="text.secondary" sx={{ fontSize: 11.5, fontWeight: 600, mb: .4 }}>Review processing</Typography><Stack gap={.4}><StatusTag value={String(task.processing_status || task.status || "not started").replaceAll("_", " ")} />{failureJob?.error && <Typography color="error.main" sx={{ fontSize: 12, overflowWrap: "anywhere" }}>{reviewProcessingError(failureJob.error)}</Typography>}<Typography color="text.secondary" sx={{ fontSize: 12 }}>Attempt {String(latestJob?.attempt_count ?? failureJob?.attempt_count ?? task.attempt_count ?? "not recorded")}{(latestJob?.max_attempts ?? failureJob?.max_attempts) ? ` / ${latestJob?.max_attempts ?? failureJob?.max_attempts}` : ""}{jobId && <> · <Link component={RouterLink} to={`/jobs/${encodeURIComponent(jobId)}`} sx={independentControlSx}>Job details</Link></>}</Typography></Stack></Box>
                <Box sx={{ minWidth: 0 }}><Typography color="text.secondary" sx={{ fontSize: 11.5, fontWeight: 600, mb: .4 }}>Review assessment</Typography><Stack gap={.35}><StatusTag value={assessment} />{hasReviewAssessment(task) && <Typography color="text.secondary" sx={{ fontSize: 12 }}>{assessmentCounts.problemCount ?? "Not recorded"} problem flags · {assessmentCounts.flaggedStepCount ?? "Not recorded"} flagged steps · {assessmentCounts.labelCount ?? "Not recorded"} labels</Typography>}</Stack></Box>
                <Box sx={{ minWidth: 0 }}><Typography color="text.secondary" sx={{ fontSize: 11.5, fontWeight: 600, mb: .4 }}>Evidence coverage</Typography>{reviewCoverage(task, noReviewProduced)}</Box>
              </Box>
              <Typography color="primary.main" sx={{ mt: 1.2, fontSize: 12, fontWeight: 600 }}>Open task review →</Typography>
            </Paper>;
          })}</Stack>}

        </Panel>
        <Panel><SectionTitle title="Workflow prompt snapshot" subtitle={`Immutable workflow revision ${workflowId}`} />
          <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1 }}>This is the actual review prompt retained with the run. It is distinct from the harness and model used to execute it.</Typography>
          <Box component="pre" sx={{ m: 0, maxHeight: 420, overflow: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere", p: 1.5, borderRadius: 2, bgcolor: "action.hover", fontSize: 13 }}>{promptText(workflow)}</Box>
        </Panel>
      </Stack></Grid>
      <Grid size={{ xs: 12, lg: 5 }}><Stack gap={2}>
        <RunShares runId={id} grants={(detail.data.grants || []) as {id:string}[]} onChange={detail.reload} />
        <Panel><SectionTitle title="Execution configuration" subtitle="Harness and model settings used for this run." />
          <Stack gap={1.1}>{[["Backend", executionBackend], ["Model", execution.model || run.model], ["Reasoning", execution.reasoning || run.reasoning], ["Budget estimate", execution.budget_usd ?? run.budget_usd], ["Run ID", id], ["Created", formatDate(run.created_at)]].map(([label, value]) => <Stack key={String(label)} direction="row" justifyContent="space-between" gap={2}><Typography color="text.secondary" sx={{ fontSize: 13 }}>{String(label)}</Typography><Typography sx={{ maxWidth: "68%", textAlign: "right", fontWeight: 650, overflowWrap: "anywhere", fontSize: 13 }}>{label === "Budget estimate" && value !== undefined && value !== null ? `$${Number(value).toFixed(2)} USD per task` : displayValue(value, "Not recorded")}</Typography></Stack>)}</Stack>
          {Object.keys(execution).length > 0 && <Box component="details" sx={{ mt: 1.3 }}><Box component="summary" sx={{ cursor: "pointer", color: "primary.main", fontWeight: 700, fontSize: 13 }}>Full execution snapshot</Box><Box component="pre" sx={{ maxHeight: 260, overflow: "auto", p: 1.2, bgcolor: "action.hover", color: "text.primary", borderRadius: 2, fontSize: 11.5 }}>{JSON.stringify(execution, null, 2)}</Box></Box>}
        </Panel>
        <Panel><SectionTitle title="Source datasets" subtitle="Membership was fixed when the run was created." />{sourceDatasets.length ? <Stack gap={.8}>{sourceDatasets.map((dataset, index) => <Paper key={String(dataset.id || dataset.dataset_id || index)} component={RouterLink} to={`/datasets/${encodeURIComponent(String(dataset.id || dataset.dataset_id || ""))}`} variant="outlined" sx={{ ...linkedCardSx, p: 1.2, color: "text.primary", textDecoration: "none", "&:focus-visible": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 } }}><Typography sx={{ fontWeight: 700, fontSize: 13, overflowWrap: "anywhere" }}>{String(dataset.name || dataset.dataset_name || dataset.id || "Dataset")}</Typography><Typography color="text.secondary" sx={{ fontSize: 12, mt: .4 }}>{displayValue(dataset.task_count, "Selected")} of {displayValue(dataset.total_task_count, "current")} tasks</Typography></Paper>)}</Stack> : <Typography color="text.secondary">{runDescription(run)}</Typography>}</Panel>
        {!!detail.data.waves?.length && <Panel><SectionTitle title="Sync waves" subtitle="Source changes added after run creation." />{detail.data.waves.map((wave, index) => <Paper key={String(wave.id || index)} variant="outlined" sx={{ p: 1.2, borderRadius: 2, mb: .7 }}><Stack direction="row" justifyContent="space-between"><Typography sx={{ fontWeight: 700 }}>Wave {String(wave.number ?? index + 1)}</Typography><StatusTag value={wave.status || "admitted"} /></Stack><Typography color="text.secondary" sx={{ fontSize: 12, mt: .3 }}>{displayValue(wave.task_count, "0")} tasks · {formatDate(wave.created_at)}</Typography></Paper>)}</Panel>}
      </Stack></Grid>
    </Grid>
    {!archived && <RunComposer open={composerOpen} onClose={() => setComposerOpen(false)} onCreated={newId => navigate(`/runs/${encodeURIComponent(newId)}`)} sourceRunId={id} />}
    <Dialog open={confirmCancel} onClose={() => !busy && setConfirmCancel(false)}><DialogTitle>Cancel this run?</DialogTitle><DialogContent><Typography>Cancellation stops future dispatch. Existing results and reviews remain saved; you can create a new run from the same selection afterward.</Typography></DialogContent><DialogActions><Button onClick={() => setConfirmCancel(false)} disabled={!!busy}>Keep run</Button><Button color="error" variant="contained" disabled={!!busy} onClick={() => void runAction("cancel")}>Cancel run</Button></DialogActions></Dialog>
  </>;
}
