import { useEffect, useState } from "react";
import { Link as RouterLink, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Collapse, Dialog, DialogActions, DialogContent, DialogTitle, Grid, IconButton, Paper, Stack, TextField, Typography } from "@mui/material";
import AddRounded from "@mui/icons-material/AddRounded";
import FileUploadRounded from "@mui/icons-material/FileUploadRounded";
import SyncRounded from "@mui/icons-material/SyncRounded";
import ArchiveRounded from "@mui/icons-material/ArchiveRounded";
import ExpandMoreRounded from "@mui/icons-material/ExpandMoreRounded";
import { DatasetShares } from "./DatasetShares";
import { apiRequest } from "../api";
import { TaskImportPicker, importSummary, uploadPreparedImport, useTaskImport } from "../TaskImport";
import { useApi } from "../hooks";
import { CATALOG_PAGING } from "../pagination";
import type { DatasetRecord, DatasetTaskModelSummary, DatasetTaskSummary, TaskRecord } from "../types";
import { BenchmarkResult, PageHeader, PageBreadcrumbs, Panel, LoadingState, ErrorState, EmptyState, SectionTitle, StatusTag, formatDate, displayValue, reviewProcessingError, runStatusLabel } from "../components";

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

function normalizeId(row: Record<string, unknown>) { return String(row.id || row.dataset_id || ""); }
function quantity(count: number | undefined, singular: string, plural = `${singular}s`) {
  return `${count ?? "Not recorded"} ${count === 1 ? singular : plural}`;
}

export function DatasetsPage() {
  const [showArchived, setShowArchived] = useState(false);
  const list = useApi<{ items?: DatasetRecord[] } | DatasetRecord[]>(`/datasets${showArchived ? "?include_archived=true" : ""}`, 0, CATALOG_PAGING);
  const datasets = Array.isArray(list.data) ? list.data : list.data?.items || [];
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const navigate = useNavigate();
  const initialImport = useTaskImport();
  const create = async () => {
    setBusy(true); setError("");
    try {
      const result = await apiRequest<Record<string, unknown>>("/datasets", { method: "POST", body: JSON.stringify({ name: name.trim(), description: description.trim(), source_adapter: "cuautoreview" }) });
      const dataset = (result.dataset || result) as Record<string, unknown>;
      const datasetId = normalizeId(dataset);
      let importNotice = "Dataset created. Import records when you are ready.";
      let importError = "";
      if (initialImport.prepared) {
        try { importNotice = importSummary(await uploadPreparedImport(datasetId, initialImport.prepared)); }
        catch (reason) { importError = `Dataset created, but importing tasks failed. Use Import records to retry: ${reason instanceof Error ? reason.message : "Import unavailable"}`; importNotice = ""; }
      }
      setCreateOpen(false); setName(""); setDescription(""); initialImport.reset(); list.reload();
      navigate(`/datasets/${encodeURIComponent(datasetId)}`, { state: { importNotice, importError } });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Dataset could not be created."); }
    finally { setBusy(false); }
  };
  return <>
    <PageHeader eyebrow="SOURCE CATALOG" title="Datasets" description="Keep source tasks and immutable revisions together. Runs select a fixed set of tasks without changing dataset history." action={<Stack direction="row" gap={1} flexWrap="wrap"><Button variant="outlined" startIcon={<ArchiveRounded />} onClick={() => setShowArchived(value => !value)}>{showArchived ? "Hide archived" : "Show archived"}</Button><Button variant="contained" startIcon={<AddRounded />} onClick={() => { setError(""); initialImport.reset(); setCreateOpen(true); }}>New dataset</Button></Stack>} />
    {notice && <Alert severity="success" onClose={() => setNotice("")} sx={{ mb: 2 }}>{notice}</Alert>}
    {error && !createOpen && <ErrorState message={error} />}
    {list.loading && <LoadingState label="Loading datasets…" />}
    {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
    {!list.loading && !list.error && !datasets.length && <EmptyState title={showArchived ? "No archived datasets" : "No datasets yet"} description={showArchived ? "No archived datasets are currently visible." : "Create a dataset with an optional ZIP of tasks and screenshots, or import records later."} action={!showArchived ? <Button variant="contained" startIcon={<AddRounded />} onClick={() => { initialImport.reset(); setCreateOpen(true); }}>Create first dataset</Button> : undefined} />}
    {!!datasets.length && <Grid container spacing={1.8}>
      {datasets.map(row => { const coverage = row.membership_coverage && typeof row.membership_coverage === "object" ? row.membership_coverage as Record<string, unknown> : {}; const covered = Number(coverage.tasks_in_runs); const total = Number(coverage.tasks_total); const coverageLabel = Number.isFinite(covered) && Number.isFinite(total) ? `${covered} / ${total} tasks in runs` : "Not recorded"; return <Grid key={normalizeId(row)} size={{ xs: 12, md: 6, xl: 4 }}>
        <Paper component={RouterLink} to={`/datasets/${encodeURIComponent(normalizeId(row))}${row.archived || row.archived_at ? "?include_archived=true" : ""}`} sx={{ height: "100%", display: "flex", flexDirection: "column", p: 2, textDecoration: "none", color: "text.primary", border: "1px solid", borderColor: "divider", borderRadius: 2, bgcolor: "background.paper", transition: "border-color .15s ease, transform .15s ease", "&:hover": { borderColor: "primary.main", transform: "translateY(-1px)" }, "&:focus-visible": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 } }}>
          <Stack direction="row" justifyContent="space-between" gap={1} alignItems="flex-start">
            <Box sx={{ minWidth: 0 }}><Typography sx={{ fontSize: 15, fontWeight: 700, overflowWrap: "anywhere", lineHeight: 1.4 }}>{row.name || "Untitled dataset"}</Typography><Typography color="text.secondary" sx={{ mt: .6, fontSize: 13 }}>{row.source_adapter || "Source adapter not recorded"}</Typography></Box>
            <StatusTag value={row.archived || row.archived_at ? "archived" : row.source_adapter || "Local"} />
          </Stack>
          <Typography color="text.secondary" sx={{ mt: 1.5, minHeight: 42, lineHeight: 1.5 }}>{row.description || "No description recorded."}</Typography>
          <Stack direction="row" gap={2} flexWrap="wrap" sx={{ mt: 2 }}><Typography sx={{ fontWeight: 750 }}>{quantity(Number(row.task_count ?? 0), "task")}</Typography><Typography color="text.secondary">{quantity(Number(row.run_count ?? row.batch_count ?? 0), "run")}</Typography><Typography color="text.secondary">{coverageLabel}</Typography></Stack>
          <Typography color="text.secondary" sx={{ mt: .7, fontSize: 12.5 }}>Created {formatDate(row.created_at)}</Typography>
          <Typography color="primary.main" sx={{ mt: "auto", pt: 1.4, fontWeight: 600, fontSize: 12.5 }}>Open dataset →</Typography>
        </Paper>
      </Grid>; })}
    </Grid>}
    <Dialog open={createOpen} onClose={() => !busy && !initialImport.checking && setCreateOpen(false)} fullWidth maxWidth="md">
      <DialogTitle>Create a dataset</DialogTitle>
      <DialogContent><Stack gap={2} sx={{ pt: 1}}>
        {error && <Alert severity="error">{error}</Alert>}
        <TextField autoFocus required label="Dataset name" value={name} onChange={event => setName(event.target.value)} />
        <TextField label="Description" value={description} onChange={event => setDescription(event.target.value)} multiline minRows={3} />
        <TextField label="Source adapter" value="cuautoreview" disabled helperText="Normalized task records. ZIP imports can include screenshots; no external URLs are fetched." />
        <TaskImportPicker state={initialImport} disabled={busy} optional />
      </Stack></DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5 }}><Button onClick={() => setCreateOpen(false)} disabled={busy || initialImport.checking}>Cancel</Button><Button variant="contained" onClick={create} disabled={busy || initialImport.checking || Boolean(initialImport.error) || !name.trim()}>{busy ? "Creating…" : initialImport.prepared ? "Create and import" : "Create dataset"}</Button></DialogActions>
    </Dialog>
  </>;
}

interface DatasetDetails {
  dataset?: DatasetRecord;
  /** The caller's effective role on this dataset; sharing needs manager or above. */
  access_role?: string | null;
  tasks?: TaskRecord[];
  runs?: Record<string, unknown>[];
  batches?: Record<string, unknown>[];
  [key: string]: unknown;
}

type TaskHistoryRow = Record<string, unknown>;
interface TaskHistoryResponse { summary?: DatasetTaskSummary; runs?: TaskHistoryRow[]; }

function rowObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function rowArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(item => item && typeof item === "object") as Record<string, unknown>[] : [];
}

function modelEvidenceSummary(model: DatasetTaskModelSummary): string | null {
  if (!model || Number(model.current_review_count || 0) + Number(model.historical_review_count || 0) === 0) return null;
  const sourceCount = Number(model.source_image_count ?? model.source_image_step_ids?.length ?? 0);
  const sentCount = Number(model.supplied_image_count ?? model.supplied_image_step_ids?.length ?? 0);
  const citedCount = Number(model.cited_image_count ?? model.cited_image_step_ids?.length ?? 0);
  const legacyMode = !model.evidence_mode && sourceCount > 0 && sentCount === 0;
  return `${sourceCount} source screenshots · ${sentCount} sent to reviewer · ${citedCount} cited by assessment${model.evidence_mode === "text_only" ? " · text-only review" : legacyMode ? " · legacy image-delivery metadata not recorded" : ""}`;
}

function runReviewMetrics(summary: Record<string, unknown>, reviews: Record<string, unknown>[], processingStatus: string) {
  const latestReview = rowObject(reviews.at(-1)?.review);
  const episodes = Array.isArray(latestReview.episodes) ? latestReview.episodes as Record<string, unknown>[] : undefined;
  const flaggedStepIds = new Set<string>();
  for (const episode of episodes || []) {
    for (const id of Array.isArray(episode.onset_step_ids) ? episode.onset_step_ids.map(String) : []) flaggedStepIds.add(id);
    if (episode.first_observed_step_id !== undefined && episode.first_observed_step_id !== null) flaggedStepIds.add(String(episode.first_observed_step_id));
  }
  const labelIds = new Set((episodes || []).map(episode => String(episode.label_id || episode.label_name || "")).filter(Boolean));
  const revisionCount = Number(summary.review_count ?? reviews.length);
  const problemCount = summary.problem_count === undefined ? episodes?.length : Number(summary.problem_count);
  const flaggedStepCount = summary.flagged_step_count === undefined ? (episodes ? flaggedStepIds.size : undefined) : Number(summary.flagged_step_count);
  const labelCount = Array.isArray(summary.flagged_labels) ? rowArray(summary.flagged_labels).length : episodes ? labelIds.size : undefined;
  const assessed = summary.review_status === "saved" || revisionCount > 0;
  const assessment = !assessed
    ? processingStatus.toLowerCase() === "failed" ? "Not available: review processing failed" : "Not recorded"
    : String(latestReview.result || (problemCount === undefined ? "Assessment recorded" : problemCount ? "Issues recorded" : "No issues recorded"));
  return { revisionCount, problemCount, flaggedStepCount, labelCount, assessment };
}

function TaskReviewBreakdown({ datasetId, taskId, includeArchived, summary }: { datasetId: string; taskId: string; includeArchived: boolean; summary?: DatasetTaskSummary }) {
  const detail = useApi<TaskHistoryResponse>(`/datasets/${encodeURIComponent(datasetId)}/tasks/${encodeURIComponent(taskId)}${includeArchived ? "?include_archived=true" : ""}`);
  const runs = detail.data?.runs || [];
  const modelRows = summary?.models || detail.data?.summary?.models || [];
  return <Box sx={{ p: 1.4, bgcolor: "action.hover", borderRadius: 2 }}>
    <SectionTitle title="Review breakdown" subtitle="Problem counts use the latest saved review per run. Image counts combine source step IDs across current and superseded reviews; each run below shows its own evidence." />
    {!!modelRows.length && <Stack gap={.7} sx={{ mb: 1.2 }}>
      {modelRows.map((model, index) => <Paper key={`${model.backend || ""}-${model.model || index}`} variant="outlined" sx={{ p: 1, bgcolor: "background.paper", borderRadius: 1.5 }}>
        <Typography sx={{ fontWeight: 700, fontSize: 13 }}>{displayValue(model.model, "Model not recorded")} · {displayValue(model.backend, "Harness not recorded")}</Typography>
        <Typography color="text.secondary" sx={{ mt: .3, fontSize: 12.5 }}>{quantity(Number(model.current_review_count || 0), "saved review")} (latest per run) · {quantity(Number(model.current_problem_count || 0), "problem episode")} · {quantity(Number(model.current_flagged_step_count || 0), "explicitly flagged step")} · {quantity(model.current_flagged_labels?.length || 0, "label")}{Number(model.historical_review_count || 0) ? ` · ${quantity(Number(model.historical_review_count), "superseded review revision")}` : ""}</Typography>
        {modelEvidenceSummary(model) && <Typography color="text.secondary" sx={{ mt: .25, fontSize: 12 }}>Evidence: {modelEvidenceSummary(model)}</Typography>}
      </Paper>)}
    </Stack>}
    {detail.loading && <Typography color="text.secondary" sx={{ py: .7, fontSize: 13 }}>Loading run and model details…</Typography>}
    {detail.error && <ErrorState message={detail.error} onRetry={detail.reload} />}
    {!detail.loading && !detail.error && !runs.length && <Typography color="text.secondary" sx={{ fontSize: 13 }}>No run-level review details are available.</Typography>}
    {!!runs.length && <Stack gap={.7}>
      {runs.map((run, index) => {
        const runId = String(run.run_id || run.batch_id || run.id || "");
        const jobs = rowArray(run.jobs);
        const reviewSummary = rowObject(run.review_summary);
        const reviews = rowArray(run.reviews);
        const processingStatus = String(run.processing_status || run.status || "not started").replaceAll("_", " ");
        const metrics = runReviewMetrics(reviewSummary, reviews, processingStatus);
        return <Paper key={runId || index} variant="outlined" sx={{ ...linkedCardSx, p: 1.25, bgcolor: "background.paper" }}>
          <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} justifyContent="space-between" gap={.6}>
            <Typography component={RouterLink} to={`/runs/${encodeURIComponent(runId)}`} sx={{ ...cardLinkSx, fontSize: 13 }}>{displayValue(run.run_name || run.name, `Run ${index + 1}`)}</Typography>
            <Stack direction="row" gap={.5} flexWrap="wrap"><StatusTag value={`Review processing: ${processingStatus}`} /><StatusTag value={`Review assessment: ${metrics.assessment}`} /><Typography color="text.secondary" sx={{ alignSelf: "center", fontSize: 12 }}>{quantity(metrics.revisionCount, "saved review revision")} · Latest: {quantity(metrics.problemCount, "problem episode")} · {quantity(metrics.flaggedStepCount, "explicitly flagged step")} · {quantity(metrics.labelCount, "label")}</Typography></Stack>
          </Stack>
          <BenchmarkResult task={run} compact />
          {!!reviews.length && <Typography color="text.secondary" sx={{ mt: .6, fontSize: 12.5 }}>{reviews.map(review => `${displayValue(review.model, "Model not recorded")} (${displayValue(review.backend, "harness not recorded")})`).join(" · ")}</Typography>}
          {jobs.map((job, jobIndex) => {
            const jobId = String(job.id || job.job_id || "");
            const failed = String(job.status || "").toLowerCase() === "failed";
            return <Stack key={jobId || jobIndex} direction={{ xs: "column", sm: "row" }} gap={.35} sx={{ mt: .5 }}>
              <Typography color={failed ? "error.main" : "text.secondary"} sx={{ fontSize: 12.5 }}>Review processing {String(job.status || "unknown").replaceAll("_", " ")} · attempt {String(job.attempt_count ?? "not recorded")}{job.max_attempts !== undefined ? ` / ${job.max_attempts}` : ""}{failed && job.error ? ` · ${reviewProcessingError(job.error)}` : ""}</Typography>
              {jobId && <Typography component={RouterLink} to={`/jobs/${encodeURIComponent(jobId)}`} sx={{ ...independentControlSx, fontSize: 12.5, color: "primary.main" }}>Job details</Typography>}
            </Stack>;
          })}
        </Paper>;
      })}
    </Stack>}
  </Box>;
}

function TaskReviewCounts({ summary }: { summary?: DatasetTaskSummary }) {
  if (!summary) return <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>Review counts not recorded</Typography>;
  const reviews = Number(summary.saved_review_count || 0);
  const revisions = Number(summary.review_revision_count ?? reviews);
  const historical = Number(summary.historical_review_count || 0);
  const runs = Number(summary.run_count || 0);
  const missing = Number(summary.missing_review_count ?? Math.max(0, runs - reviews));
  return <Stack gap={.25}>
    <Typography sx={{ fontSize: 12.5, fontWeight: 650 }}>{quantity(runs, "run")} · {quantity(reviews, "saved review")} (latest per run){revisions !== reviews ? ` · ${quantity(revisions, "saved review revision")} total` : ""}</Typography>
    {reviews ? <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>{quantity(Number(summary.problem_count || 0), "problem episode")} · {quantity(Number(summary.flagged_step_count || 0), "explicitly flagged step")} · {quantity(summary.flagged_labels?.length || 0, "label")}{missing ? ` · ${quantity(missing, "run")} without an assessment` : ""}{historical ? ` · ${quantity(historical, "superseded review revision")}` : ""}</Typography> : <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>No review assessment has been saved for these runs.</Typography>}
  </Stack>;
}

function DatasetLifecycle({ dataset, onChanged }: { dataset?: DatasetRecord | null; onChanged: (archived: boolean) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const archived = Boolean(dataset?.archived || dataset?.archived_at);
  const run = async () => {
    const id = String(dataset?.id || "");
    if (!id) return;
    setBusy(true); setError("");
    try { await apiRequest(`/datasets/${encodeURIComponent(id)}/${archived ? "restore" : "archive"}`, { method: "POST" }); onChanged(!archived); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Dataset status could not be changed."); }
    finally { setBusy(false); }
  };
  return <Stack direction="row" alignItems="center" gap={.5}>{archived && <StatusTag value="archived" />}<Button size="small" color={archived ? "primary" : "error"} variant="outlined" disabled={busy} onClick={() => void run()}>{busy ? "Saving…" : archived ? "Restore" : "Archive"}</Button>{error && <Typography color="error" sx={{ fontSize: 12 }}>{error}</Typography>}</Stack>;
}

export function DatasetDetailPage() {
  const { id = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [includeArchived, setIncludeArchived] = useState(searchParams.get("include_archived") === "true");
  useEffect(() => setIncludeArchived(searchParams.get("include_archived") === "true"), [searchParams]);
  const [showArchivedTasks, setShowArchivedTasks] = useState(false);
  const [expandedTaskId, setExpandedTaskId] = useState("");
  const includeTaskArchive = showArchivedTasks || includeArchived;
  const state = useApi<DatasetDetails>(id ? `/datasets/${encodeURIComponent(id)}${includeTaskArchive ? "?include_archived=true" : ""}` : null);
  const [importOpen, setImportOpen] = useState(false);
  const location = useLocation();
  const arrival = location.state as { importNotice?: string; importError?: string } | null;
  const importState = useTaskImport();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(arrival?.importError || "");
  const [notice, setNotice] = useState(arrival?.importNotice || "");
  const [syncPreview, setSyncPreview] = useState<unknown>(null);
  const navigate = useNavigate();
  const dataset = state.data?.dataset || state.data as DatasetRecord | null;
  const tasks = state.data?.tasks || [];
  const runs = state.data?.runs || state.data?.batches || [];
  const canShare = ["admin", "manager"].includes(String(state.data?.access_role || ""));
  const archivedDataset = Boolean(dataset?.archived || dataset?.archived_at);
  const submitImport = async () => {
    if (!importState.prepared) return;
    setWorking(true); setError("");
    try {
      const result = await uploadPreparedImport(id, importState.prepared);
      setNotice(importSummary(result));
      setImportOpen(false); importState.reset(); state.reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Import could not be completed."); }
    finally { setWorking(false); }
  };
  const previewSync = async () => {
    setWorking(true); setError("");
    try { setSyncPreview(await apiRequest(`/datasets/${encodeURIComponent(id)}/sync-preview`)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Sync preview failed."); }
    finally { setWorking(false); }
  };

  if (state.loading) return <LoadingState label="Loading dataset details…" />;
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (!state.data) return <EmptyState title="Dataset not found" description="The dataset may have been removed or you may not have access." />;
  return <>
    <PageBreadcrumbs items={[{ label: "Datasets", to: "/datasets" }, { label: dataset?.name || "Dataset" }]} />
    <PageHeader eyebrow="DATASET" title={dataset?.name || "Dataset details"} description={dataset?.description || "Source revisions remain immutable. Runs select tasks from this dataset without rewriting its history."} action={<Stack direction="row" gap={1} flexWrap="wrap"><Button variant="outlined" startIcon={<FileUploadRounded />} onClick={() => { setError(""); importState.reset(); setImportOpen(true); }}>Import records</Button><Button variant="contained" startIcon={<AddRounded />} onClick={() => navigate(`/runs?dataset_id=${encodeURIComponent(id)}`)}>Create run</Button><DatasetLifecycle dataset={dataset} onChanged={archived => { setIncludeArchived(archived); setSearchParams(archived ? { include_archived: "true" } : {}, { replace: true }); }} /></Stack>} />
    {notice && <Alert severity="success" onClose={() => setNotice("")} sx={{ mb: 2 }}>{notice}</Alert>}
    {error && <Alert severity="error" onClose={() => setError("")} sx={{ mb: 2 }}>{error}</Alert>}
    <Grid container spacing={2} sx={{ mb: 2.2 }}>
      <Grid size={{ xs: 12, md: 8 }}><Panel><SectionTitle title="Source details" /><Stack direction="row" flexWrap="wrap" gap={3}><Box><Typography color="text.secondary" sx={{ fontSize: 13 }}>Adapter</Typography><Typography sx={{ fontWeight: 700 }}>{dataset?.source_adapter || "Not recorded"}</Typography></Box><Box><Typography color="text.secondary" sx={{ fontSize: 13 }}>Tasks</Typography><Typography sx={{ fontWeight: 700 }}>{tasks.length}</Typography></Box><Box><Typography color="text.secondary" sx={{ fontSize: 13 }}>Runs</Typography><Typography sx={{ fontWeight: 700 }}>{runs.length}</Typography></Box><Box><Typography color="text.secondary" sx={{ fontSize: 13 }}>Dataset revision</Typography><Typography sx={{ fontWeight: 700 }}>{displayValue(dataset?.revision, "Current")}</Typography></Box></Stack></Panel></Grid>
      <Grid size={{ xs: 12, md: 4 }}><Panel><SectionTitle title="Sync new revisions" /><Typography color="text.secondary" sx={{ fontSize: 14, mb: 1.4 }}>Preview additions and changed source revisions before syncing an appendable run.</Typography><Button variant="outlined" startIcon={<SyncRounded />} onClick={previewSync} disabled={working}>Preview sync</Button>{syncPreview !== null && <Box component="pre" sx={{ mt: 1.5, mb: 0, maxHeight: 230, overflow: "auto", p: 1.4, bgcolor: "action.hover", borderRadius: 2, fontSize: 12 }}>{JSON.stringify(syncPreview, null, 2)}</Box>}</Panel></Grid>
    </Grid>
    <Grid container spacing={2} alignItems="flex-start" sx={{ minWidth: 0 }}>
      <Grid size={{ xs: 12, lg: 7.5 }} sx={{ minWidth: 0 }}><Panel sx={{ minWidth: 0 }}><SectionTitle title="Tasks in this dataset" subtitle="One model-reported problem may flag several steps. Step counts use distinct IDs across the latest review per run; related and recovery links are separate." action={<Button size="small" startIcon={<ArchiveRounded />} onClick={() => setShowArchivedTasks(value => !value)}>{showArchivedTasks ? "Hide archived tasks" : "Show archived tasks"}</Button>} />
        {!tasks.length ? <Typography color="text.secondary" sx={{ py: 3 }}>No task records have been imported. Use Import records to add a ZIP with screenshots or a JSON task file.</Typography> : <Stack gap={1.2}>{tasks.map(task => {
          const taskDefId = String(task.task_definition_id || task.id || task.task_id);
          const taskArchived = Boolean(task.archived || task.archived_at);
          const taskUrl = `/datasets/${encodeURIComponent(id)}/tasks/${encodeURIComponent(taskDefId)}${taskArchived || showArchivedTasks || includeArchived ? "?include_archived=true" : ""}`;
          const expanded = expandedTaskId === taskDefId;
          return <Box key={taskDefId} sx={{ minWidth: 0 }}>
            <Paper variant="outlined" sx={{ ...linkedCardSx, p: 1.5 }}>
              <Stack direction="row" alignItems="flex-start" gap={1}>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography component={RouterLink} to={taskUrl} sx={{ ...cardLinkSx, fontSize: 14, lineHeight: 1.45 }}>{task.title || task.task_id}</Typography>
                  <Typography color="text.secondary" sx={{ mt: .25, fontSize: 11.5, overflowWrap: "anywhere" }}>{task.task_id}</Typography>
                </Box>
                <IconButton size="small" aria-label={expanded ? `Hide review breakdown for ${task.title || task.task_id}` : `Show review breakdown for ${task.title || task.task_id}`} aria-expanded={expanded} onClick={() => setExpandedTaskId(expanded ? "" : taskDefId)} sx={independentControlSx}><ExpandMoreRounded sx={{ transform: expanded ? "rotate(180deg)" : "none", transition: "transform .15s" }} /></IconButton>
              </Stack>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "minmax(0, .85fr) minmax(0, 1.3fr)" }, gap: 1.25, mt: 1.3, pt: 1.2, borderTop: "1px solid", borderColor: "divider" }}>
                <Box sx={{ minWidth: 0 }}><Typography color="text.secondary" sx={{ fontSize: 11.5, fontWeight: 600, mb: .4 }}>Source task</Typography><Stack direction="row" alignItems="center" flexWrap="wrap" gap={.5}><BenchmarkResult task={task as Record<string, unknown>} compact />{taskArchived && <StatusTag value="archived" />}</Stack><Typography color="text.secondary" sx={{ fontSize: 12, mt: .5 }}>{task.steps?.length ?? displayValue(task.step_count)} steps · Revision {displayValue(task.revision ?? task.source_revision ?? task.revision_id)}</Typography></Box>
                <Box sx={{ minWidth: 0 }}><Typography color="text.secondary" sx={{ fontSize: 11.5, fontWeight: 600, mb: .4 }}>Review history</Typography><TaskReviewCounts summary={task.summary} /></Box>
              </Box>
            </Paper>
            <Collapse in={expanded} unmountOnExit><Box sx={{ pt: .7 }}><TaskReviewBreakdown datasetId={id} taskId={taskDefId} includeArchived={taskArchived || showArchivedTasks || includeArchived} summary={task.summary} /></Box></Collapse>
          </Box>;
        })}</Stack>}

      </Panel></Grid>
      <Grid size={{ xs: 12, lg: 4.5 }} sx={{ minWidth: 0 }}><Panel sx={{ minWidth: 0 }}><SectionTitle title="Runs using this dataset" /><Stack gap={1}>{runs.map((run, index) => {
        const runId = String(run.id || run.run_id || "");
        const archived = Boolean(run.archived || run.archived_at);
        const selectedCount = Number(run.selected_task_count);
        const datasetTaskCount = Number(run.dataset_task_count);
        const hasTaskCounts = run.selected_task_count !== null && run.selected_task_count !== undefined && run.dataset_task_count !== null && run.dataset_task_count !== undefined && Number.isFinite(selectedCount) && Number.isFinite(datasetTaskCount);
        const taskCoverage = hasTaskCounts ? `${selectedCount} of ${datasetTaskCount} ${datasetTaskCount === 1 ? "task" : "tasks"}` : "";
        return <Paper key={runId || index} component={RouterLink} to={`/runs/${encodeURIComponent(runId)}${archived ? "?include_archived=true" : ""}`} variant="outlined" sx={{ ...linkedCardSx, p: 1.5, textDecoration: "none", color: "text.primary", "&:focus-visible": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 } }}><Typography sx={{ fontWeight: 750, overflowWrap: "anywhere" }}>{displayValue(run.run_name || run.name)}</Typography><Stack direction="row" gap={1} sx={{ mt: .8, flexWrap: "wrap" }}><StatusTag value={runStatusLabel(run)} /><StatusTag value={run.mode} />{taskCoverage && <Typography color="text.secondary" sx={{ alignSelf: "center", fontSize: 12.5 }}>{taskCoverage}</Typography>}</Stack></Paper>;
      })}{!runs.length && <Typography color="text.secondary">No runs use this dataset yet.</Typography>}</Stack></Panel></Grid>
    </Grid>
    {!archivedDataset && canShare && <Box sx={{ mt: 2 }}><DatasetShares datasetId={id} /></Box>}
    <Dialog open={importOpen} onClose={() => !working && !importState.checking && setImportOpen(false)} fullWidth maxWidth="md">
      <DialogTitle>Import task records</DialogTitle><DialogContent><Stack gap={2} sx={{ pt: 1 }}>
        {error && <Alert severity="error">{error}</Alert>}
        <TaskImportPicker state={importState} disabled={working} />
        <Typography color="text.secondary" sx={{ fontSize: 14 }}>Existing task IDs create new immutable revisions only when their content changes. Importing does not change run membership; sync or create a new run to include updated source records.</Typography>
      </Stack></DialogContent><DialogActions sx={{ px: 3, pb: 2.5 }}><Button onClick={() => setImportOpen(false)} disabled={working || importState.checking}>Cancel</Button><Button variant="contained" onClick={submitImport} disabled={working || importState.checking || !importState.prepared}>{working ? "Importing…" : "Confirm import"}</Button></DialogActions>
    </Dialog>
  </>;
}
