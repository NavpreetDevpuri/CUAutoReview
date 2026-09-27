import { useEffect, useRef, useState } from "react";
import { Link as RouterLink, useParams, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Checkbox, Chip, Dialog, DialogContent, DialogTitle, FormControl, Grid, IconButton, Link, MenuItem, Paper, Select, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography, useMediaQuery } from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import CloseRounded from "@mui/icons-material/CloseRounded";
import OpenInNewRounded from "@mui/icons-material/OpenInNewRounded";
import FormatListNumberedRounded from "@mui/icons-material/FormatListNumberedRounded";
import { StepFlag, type StepFlagData } from "../StepFlag";
import ArchiveRounded from "@mui/icons-material/ArchiveRounded";
import CompareArrowsRounded from "@mui/icons-material/CompareArrowsRounded";
import DownloadRounded from "@mui/icons-material/DownloadRounded";
import InsightsRounded from "@mui/icons-material/InsightsRounded";
import { RunComposer } from "../RunComposer";
import { apiRequest } from "../api";
import { useApi } from "../hooks";
import type { DatasetRecord, DatasetTaskSummary, ReviewEvidenceProvenance, TaskRecord } from "../types";
import { BenchmarkResult, EmptyState, ErrorState, LoadingState, MetricCard, PageBreadcrumbs, PageHeader, Panel, SectionTitle, StatusTag, displayValue, formatDate, reviewProcessingError } from "../components";

type Row = Record<string, unknown>;
interface TaskHistory {
  dataset?: DatasetRecord;
  task_definition?: Row;
  current_revision?: Row;
  revision?: Row;
  task?: TaskRecord;
  runs?: Row[];
  reviews?: Row[];
  summary?: DatasetTaskSummary;
  [key: string]: unknown;
}
const object = (value: unknown): Row => value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const rowId = (row: Row): string => String(row.id || row.run_id || row.batch_id || "");
const idList = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
function evidenceCoverageText(value: unknown, summary: Row = {}, sourceStepCount?: number) {
  const provenance = object(value) as ReviewEvidenceProvenance;
  const sourceIds = idList(provenance.source_image_step_ids);
  const suppliedIds = idList(provenance.supplied_image_step_ids);
  const citedIds = idList(provenance.cited_image_step_ids);
  const sourceCount = Number(summary.source_image_count ?? (sourceIds.length || sourceStepCount || 0));
  const suppliedCount = Number(summary.supplied_image_count ?? (Array.isArray(summary.supplied_image_step_ids) ? idList(summary.supplied_image_step_ids).length : suppliedIds.length));
  const citedCount = Number(summary.cited_image_count ?? (Array.isArray(summary.cited_image_step_ids) ? idList(summary.cited_image_step_ids).length : citedIds.length));
  const legacyTextOnly = !provenance.evidence_mode && Array.isArray(provenance.inspected_image_step_ids) && provenance.inspected_image_step_ids.length === 0;
  const deliveryKnown = provenance.evidence_mode === "text_only" || Array.isArray(provenance.supplied_image_step_ids) || summary.supplied_image_count !== undefined || Array.isArray(summary.supplied_image_step_ids) || legacyTextOnly;
  const citationsKnown = Array.isArray(provenance.cited_image_step_ids) || summary.cited_image_count !== undefined || Array.isArray(summary.cited_image_step_ids) || legacyTextOnly;
  const sentText = deliveryKnown ? `${suppliedCount} sent to reviewer` : "sent count not recorded";
  const citedText = citationsKnown ? `${citedCount} cited by assessment` : "citations not recorded";
  return { sourceCount, sentText, citedText, textOnly: provenance.evidence_mode === "text_only", legacy: legacyTextOnly, reason: String(provenance.omitted_image_reason || "") };
}
function buildSourceStepSlots(steps: NonNullable<TaskRecord["steps"]>) {
  const slots: { id: string; index: number; step?: NonNullable<TaskRecord["steps"]>[number] }[] = [];
  for (const [index, step] of steps.entries()) {
    const id = String(step.step_id ?? index + 1);
    const previous = slots.at(-1);
    const previousNumber = previous ? Number(previous.id) : NaN;
    const currentNumber = Number(id);
    if (Number.isInteger(previousNumber) && Number.isInteger(currentNumber) && currentNumber > previousNumber + 1 && currentNumber - previousNumber <= 100) {
      for (let gap = previousNumber + 1; gap < currentNumber; gap += 1) slots.push({ id: String(gap), index: -1 });
    }
    slots.push({ id, index, step });
  }
  return slots;
}
function reviewIdForFilter(review: Row, index: number) {
  const nested = object(review.review);
  return String(review.result_id || review.review_result_id || nested.result_id || review.id || nested.id || `${review.run_id || review.batch_id || "review"}-${index}`);
}
function reviewFlagsAtStep(row: Row, stepId: string) {
  const review = object(row.review);
  const episodes = Array.isArray(review.episodes) ? review.episodes as Row[] : [];
  const reviewStep = (Array.isArray(review.steps) ? review.steps as Row[] : []).find(step => String(step.step_id || "") === stepId);
  const refs = Array.isArray(reviewStep?.episode_refs) ? reviewStep!.episode_refs.map(ref => String(object(ref).episode_id || object(ref).id || ref)) : [];
  const flags: StepFlagData[] = [];
  const relatedEpisodes: Row[] = [];
  for (const [index, episode] of episodes.entries()) {
    const episodeId = String(episode.episode_id || episode.id || "");
    const onset = Array.isArray(episode.onset_step_ids) ? episode.onset_step_ids.map(String) : [];
    const first = String(episode.first_observed_step_id || onset[0] || "unknown");
    const atOnset = first === stepId || onset.includes(stepId);
    const recovery = object(episode.recovery);
    const recoveryIds = Array.isArray(recovery.step_ids) ? recovery.step_ids.map(String) : [];
    const atRecovery = recoveryIds.includes(stepId);
    const related = refs.includes(episodeId);
    const number = episode.problem_number || index + 1;
    const label = String(episode.label_name || episode.label_id || "Problem flagged");
    const anchorPhrase = String(review.schema_version) === "2" ? "First observed" : "First flagged";
    if (atOnset || related || atRecovery) relatedEpisodes.push(episode);
    if (atOnset) flags.push({ kind: "problem", number: String(number), label, relation: first === stepId ? `${anchorPhrase} here` : `Continues from step ${first}` });
    else if (related && !atRecovery) flags.push({ kind: "related", number: String(number), label, relation: `Related step, starts at step ${first}` });
    if (atRecovery) flags.push({ kind: "recovery", number: String(number), label, relation: `${recovery.status === "recovered" ? "Recovered" : "Recovery evidence"}, starts at step ${first}` });
  }
  return { flags, reviewStep, relatedEpisodes };
}

export function DatasetTaskPage() {
  const { id: datasetId = "", taskId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [includeArchived, setIncludeArchived] = useState(searchParams.get("include_archived") === "true");
  useEffect(() => setIncludeArchived(searchParams.get("include_archived") === "true"), [searchParams]);
  const archiveQuery = includeArchived ? "?include_archived=true" : "";
  const detail = useApi<TaskHistory>(datasetId && taskId ? `/datasets/${encodeURIComponent(datasetId)}/tasks/${encodeURIComponent(taskId)}${archiveQuery}` : null);
  const datasetState = useApi<{ name?: string; dataset?: DatasetRecord } | { dataset?: DatasetRecord }>(datasetId ? `/datasets/${encodeURIComponent(datasetId)}${archiveQuery}` : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [composerOpen, setComposerOpen] = useState(false);
  const [sourceReviewFilter, setSourceReviewFilter] = useState("all");
  const [sourceStepsCollapsed, setSourceStepsCollapsed] = useState(false);
  const [stepPickerOpen, setStepPickerOpen] = useState(false);
  const theme = useTheme();
  const compactSteps = useMediaQuery(theme.breakpoints.down("md"));
  const [selectedSourceStepId, setSelectedSourceStepId] = useState("");
  const [sourceScreenshotFailed, setSourceScreenshotFailed] = useState(false);
  const sourceEvidenceRef = useRef<HTMLDivElement>(null);
  const sourceStepListRef = useRef<HTMLDivElement>(null);
  const history = detail.data;
  const taskSummary = history?.summary;
  const definition = object(history?.task_definition);
  const revision = object(history?.current_revision || history?.revision);
  const task: TaskRecord = (history?.task || object(revision.content) || revision) as TaskRecord;
  const dataset = history?.dataset || (datasetState.data && "dataset" in datasetState.data ? datasetState.data.dataset : datasetState.data) as DatasetRecord | undefined;
  const runs = Array.isArray(history?.runs) ? history!.runs! : [];
  const reviewRows: Row[] = Array.isArray(history?.reviews) ? history!.reviews! : runs.flatMap(run => {
    const embedded = Array.isArray(run.reviews) ? run.reviews as Row[] : run.review ? [object(run.review)] : [];
    return embedded.map(review => ({ ...review, run_id: review.run_id || rowId(run), run_name: review.run_name || run.run_name || run.name }));
  });
  const reviews: Row[] = reviewRows.map(review => {
    const runId = String(review.run_id || review.batch_id || "");
    const run = runs.find(item => rowId(item) === runId);
    const runConfiguration = object(run?.configuration);
    const execution = object(review.execution || run?.execution || runConfiguration.execution_snapshot);
    return {
      ...review,
      run_id: runId || rowId(run || {}),
      run_name: review.run_name || run?.run_name || run?.name,
      backend: review.backend || execution.backend || run?.backend,
      model: review.model || execution.model || run?.model,
      source_revision_id: review.task_revision_id || review.source_revision_id || run?.task_revision_id,
    };
  });
  const sourceSteps = Array.isArray(task.steps) ? task.steps : [];
  const currentRevisionId = String(revision.id || revision.revision_id || revision.task_revision_id || "");
  const sourceSlots = buildSourceStepSlots(sourceSteps);
  const sourceStepSignature = sourceSlots.map(slot => `${slot.id}:${slot.index}`).join("|");
  const allReviewOptions = reviews.map((review, index) => ({ review, key: reviewIdForFilter(review, index) }));
  const reviewOptions = (currentRevisionId ? allReviewOptions.filter(option => String(option.review.source_revision_id || "") === currentRevisionId) : []).map((option, index) => ({ ...option, number: index + 1 }));
  const excludedOverlayReviewCount = allReviewOptions.length - reviewOptions.length;
  const visibleSourceReviews = sourceReviewFilter === "all" ? reviewOptions : reviewOptions.filter(option => option.key === sourceReviewFilter);
  const selectedSourceStep = sourceSteps.find((step, index) => String(step.step_id ?? index + 1) === selectedSourceStepId);
  const selectedSourceScreenshotUrl = selectedSourceStep?.screenshot_url?.startsWith("/api/artifacts/") ? selectedSourceStep.screenshot_url : "";
  const sourceScreenshotMissing = selectedSourceStep?.artifact_status === "missing" || Boolean(selectedSourceStep?.screenshot || selectedSourceStep?.screenshot_path || selectedSourceStep?.artifact_id);
  const title = String(task.title || definition.title || definition.task_id || "Task");
  const taskKey = String(task.task_id || definition.task_id || definition.id || taskId);
  const archived = Boolean(definition.archived || definition.archived_at || history?.archived || history?.archived_at);
  const [backendFilter, setBackendFilter] = useState("all");
  const [modelFilter, setModelFilter] = useState("all");
  const [selectedReviewIds, setSelectedReviewIds] = useState<string[]>([]);
  const backendOptions = [...new Set(reviews.map(review => String(review.backend || "")).filter(Boolean))].sort();
  const modelOptions = [...new Set(reviews.map(review => String(review.model || "")).filter(Boolean))].sort();
  const filteredReviews = reviews.filter(review => (backendFilter === "all" || review.backend === backendFilter) && (modelFilter === "all" || review.model === modelFilter));
  const reviewId = (review: Row) => {
    const nested = object(review.review);
    return String(review.result_id || review.review_result_id || nested.result_id || review.id || nested.id || "");
  };
  const sourceRevisionId = (review: Row) => String(review.source_revision_id || "");
  const selectedRevisionId = sourceRevisionId(reviews.find(review => reviewId(review) === selectedReviewIds[0]) || {});
  const canSelectReview = (review: Row) => {
    const id = reviewId(review);
    const revisionId = sourceRevisionId(review);
    return Boolean(id && revisionId) && (selectedReviewIds.includes(id) || (selectedReviewIds.length < 2 && (!selectedRevisionId || revisionId === selectedRevisionId)));
  };
  const toggleReview = (review: Row, checked: boolean) => {
    const id = reviewId(review);
    setSelectedReviewIds(current => checked ? [...current, id].slice(-2) : current.filter(value => value !== id));
  };
  const compareUrl = selectedReviewIds.length === 2 ? `/compare?left=${encodeURIComponent(selectedReviewIds[0])}&right=${encodeURIComponent(selectedReviewIds[1])}` : "";
  const exportBase = `/api/datasets/${encodeURIComponent(datasetId)}/tasks/${encodeURIComponent(taskId)}/export`;
  const exportHref = (format: "json" | "yaml") => `${exportBase}?format=${format}${includeArchived ? "&include_archived=true" : ""}`;
  const setArchived = async () => {
    setBusy(true); setError("");
    try { await apiRequest(`/tasks/${encodeURIComponent(taskId)}/${archived ? "restore" : "archive"}`, { method: "POST" }); const nextArchived = !archived; setIncludeArchived(nextArchived); setSearchParams(nextArchived ? { include_archived: "true" } : {}, { replace: true }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Task status could not be changed."); }
    finally { setBusy(false); }
  };
  const selectSourceStepAt = (index: number) => {
    const step = sourceSteps[index];
    if (!step) return;
    setSelectedSourceStepId(String(step.step_id ?? index + 1));
    setStepPickerOpen(false);
    requestAnimationFrame(() => sourceEvidenceRef.current?.scrollIntoView({ block: "start" }));
  };

  useEffect(() => {
    setSourceReviewFilter("all");
    setSelectedSourceStepId("");
    setStepPickerOpen(false);
    setSelectedReviewIds([]);
    setBackendFilter("all");
    setModelFilter("all");
  }, [datasetId, taskId, currentRevisionId]);
  useEffect(() => {
    const firstStep = sourceSteps[0];
    if (!selectedSourceStepId || !sourceSteps.some((step, index) => String(step.step_id ?? index + 1) === selectedSourceStepId)) {
      setSelectedSourceStepId(firstStep ? String(firstStep.step_id ?? 1) : "");
    }
  }, [datasetId, taskId, sourceStepSignature]);
  useEffect(() => setSourceScreenshotFailed(false), [selectedSourceStepId]);
  useEffect(() => {
    const list = sourceStepListRef.current;
    const selected = list?.querySelector<HTMLButtonElement>('[aria-current="step"]');
    if (!list || !selected || sourceStepsCollapsed) return;
    const bounds = list.getBoundingClientRect();
    const item = selected.getBoundingClientRect();
    if (item.top < bounds.top || item.bottom > bounds.bottom) {
      list.scrollTop += item.top - bounds.top;
    }
  }, [selectedSourceStepId, sourceStepsCollapsed]);
  useEffect(() => {
    if (stepPickerOpen) requestAnimationFrame(() => sourceStepListRef.current?.querySelector<HTMLElement>('[aria-current="step"]')?.scrollIntoView({ block: "center" }));
  }, [stepPickerOpen]);

  if (detail.loading) return <LoadingState label="Loading task revisions and run history…" />;
  if (detail.error) return <ErrorState message={detail.error} onRetry={detail.reload} />;
  if (!history) return <EmptyState title="Task not found" description="This task may have been removed or you may not have access." action={<Button component={RouterLink} to={`/datasets/${encodeURIComponent(datasetId)}`} variant="outlined">Back to dataset</Button>} />;
  const sourceStepNavigator = <>
          <SectionTitle title="Source steps" subtitle={`${sourceSteps.length} recorded steps · gaps are shown explicitly`} />
          <FormControl fullWidth size="small" sx={{ mb: 1.2 }}>
            <Select value={sourceReviewFilter} onChange={event => setSourceReviewFilter(event.target.value)} MenuProps={{ PaperProps: { sx: { maxWidth: "calc(100vw - 24px)", "& .MuiMenuItem-root": { whiteSpace: "normal" } } } }} inputProps={{ "aria-label": "Choose review overlay" }}>
              <MenuItem value="all">All current revision reviews · {reviewOptions.length}</MenuItem>
              {reviewOptions.map(({ review, key, number }, index) => <MenuItem key={key} value={key}>{`Review ${number} · ${displayValue(review.run_name, `Run ${index + 1}`)} · ${displayValue(review.model, "Model not recorded")}`}</MenuItem>)}
            </Select>
          </FormControl>
          {!sourceSlots.length ? <Typography color="text.secondary" sx={{ py: 2 }}>No source steps are recorded.</Typography> : <Stack ref={sourceStepListRef} gap={.5} sx={{ maxHeight: compactSteps ? "none" : "min(70vh, 760px)", overflowY: "auto", pr: .4 }}>
            {sourceSlots.map((slot, index) => {
              if (!slot.step) return <Alert key={`gap-${slot.id}`} severity="warning" icon={false} sx={{ py: .1, px: 1.2, fontSize: 12 }}>Step {slot.id} is missing from the source record.</Alert>;
              const flags = visibleSourceReviews.flatMap(({ review, number }, reviewIndex) => {
                const found = reviewFlagsAtStep(review, slot.id).flags;
                return found.map(flag => ({ ...flag, review: String(number), model: displayValue(review.model, "Not recorded"), key: `${reviewIdForFilter(review, reviewIndex)}-${flag.kind}-${flag.number}-${flag.label}` }));
              });
              const active = slot.id === selectedSourceStepId;
              return <Button disableRipple key={`${slot.id}-${index}`} onClick={() => selectSourceStepAt(slot.index)} aria-current={active ? "step" : undefined} variant="text" color="inherit" sx={theme => ({ display: "block", flexShrink: 0, textAlign: "left", textTransform: "none", whiteSpace: "normal", p: 1, border: "1px solid", borderColor: active ? "primary.main" : "divider", borderRadius: 1.5, bgcolor: active ? alpha(theme.palette.primary.main, .075) : "transparent", color: "text.primary", "&:hover": { bgcolor: "action.hover" } })}>
                <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1}><Typography sx={{ fontWeight: 700, fontSize: 13 }}>Step {slot.id}</Typography>{!!flags.length && <Typography color="text.secondary" sx={{ fontSize: 11.5 }}>{flags.length} flag{flags.length === 1 ? "" : "s"}</Typography>}</Stack>
                <Typography sx={{ mt: .3, fontSize: 12.5, opacity: .85, overflowWrap: "anywhere", display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2, overflow: "hidden" }}>{displayValue(slot.step.action || slot.step.intent, "Action not recorded")}</Typography>
                {!!flags.length && <Stack component="span" gap={.5} sx={{ mt: .75 }}>{flags.map(({ key, ...flag }) => <StepFlag key={key} {...flag} />)}</Stack>}
              </Button>;
            })}
          </Stack>}
  </>;

  return <>
    <PageBreadcrumbs items={[{ label: "Datasets", to: "/datasets" }, { label: String(dataset?.name || "Dataset"), to: `/datasets/${encodeURIComponent(datasetId)}${includeArchived ? "?include_archived=true" : ""}` }, { label: title }]} />
    <PageHeader eyebrow="DATASET TASK" title={title} description={`${taskKey} · revision ${displayValue(revision.revision, "Current")}`} action={<Stack direction="row" alignItems="center" gap={.8} flexWrap="wrap" sx={{ display: { xs: "grid", sm: "flex" }, gridTemplateColumns: "repeat(2, minmax(0, 1fr))", "& .MuiButton-root": { width: { xs: "100%", sm: "auto" }, minWidth: 0 } }}><Button size="small" variant="outlined" href={exportHref("json")} startIcon={<DownloadRounded />}>Download JSON</Button><Button size="small" variant="outlined" href={exportHref("yaml")}>Download YAML</Button><Button size="small" variant="contained" onClick={() => setComposerOpen(true)} startIcon={<InsightsRounded />}>Analyze task</Button><Button size="small" variant="outlined" component={RouterLink} to={`/analytics?dataset=${encodeURIComponent(datasetId)}&task=${encodeURIComponent(taskId)}`}>View analytics</Button><Button size="small" color={archived ? "primary" : "error"} variant="outlined" startIcon={<ArchiveRounded />} onClick={() => void setArchived()} disabled={busy}>{busy ? "Saving…" : archived ? "Restore task" : "Archive task"}</Button></Stack>} />
    {error && <Alert severity="error" onClose={() => setError("")} sx={{ mb: 1.5 }}>{error}</Alert>}
    {archived && <Alert severity="warning" sx={{ mb: 1.5 }}>This task is archived. It stays available in its existing runs and can be restored for future selections.</Alert>}
    <Panel sx={{ mb: 2 }}><SectionTitle title="Review summary" subtitle="Original task results, review processing, and review assessments are separate records." />
      <Grid container spacing={1.2}>
        <Grid size={{ xs: 6, md: 3 }}><MetricCard label="Runs containing this task" value={taskSummary ? Number(taskSummary.run_count ?? runs.length) : runs.length} /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><MetricCard label="Latest saved review assessments" value={taskSummary ? Number(taskSummary.saved_review_count || 0) : reviews.length} detail={taskSummary ? `${Number(taskSummary.review_revision_count ?? taskSummary.saved_review_count ?? 0)} saved review revisions across runs` : "Review summaries not available"} /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><MetricCard label="Problem flags" value={taskSummary ? Number(taskSummary.problem_count || 0) : "Not recorded"} detail={taskSummary ? `${Number(taskSummary.historical_problem_count || 0)} in superseded review revisions` : "Review summaries not available"} /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><MetricCard label="Flagged source steps" value={taskSummary ? Number(taskSummary.flagged_step_count || 0) : "Not recorded"} detail={taskSummary ? `${Number(taskSummary.historical_flagged_step_count || 0)} in superseded review revisions` : "Review summaries not available"} /></Grid>
      </Grid>
      <Stack direction="row" gap={.6} flexWrap="wrap" sx={{ mt: 1.2, alignItems: "center" }}><Typography sx={{ fontSize: 13, fontWeight: 700 }}>Flagged labels:</Typography>{taskSummary?.flagged_labels?.length ? taskSummary.flagged_labels.map(label => <Chip key={label.id || label.name} size="small" variant="outlined" color="warning" label={`${label.name} · ${label.count}`} />) : <Typography color="text.secondary" sx={{ fontSize: 13 }}>{taskSummary ? "No labels recorded in current assessments." : "Not recorded"}</Typography>}</Stack>
      {!!taskSummary?.models?.length && <Box sx={{ mt: 1.4 }}><Typography sx={{ fontWeight: 750, mb: .7 }}>By reviewer model</Typography><Typography color="text.secondary" sx={{ mb: .7, fontSize: 13 }}>Image counts cover unique source steps across reviews. Each run below shows what that reviewer received.</Typography><Stack gap={.6}>{taskSummary.models.map((model, index) => { const hasSavedReviews = Number(model.current_review_count || 0) + Number(model.historical_review_count || 0) > 0; const currentCount = Number(model.current_review_count || 0); const sourceCount = Number(model.source_image_count ?? model.source_image_step_ids?.length ?? 0); const suppliedCount = Number(model.supplied_image_count ?? model.supplied_image_step_ids?.length ?? 0); const citedCount = Number(model.cited_image_count ?? model.cited_image_step_ids?.length ?? 0); const legacyImageDelivery = !model.evidence_mode && sourceCount > 0 && suppliedCount === 0; return <Paper key={`${model.backend || ""}-${model.model || index}`} variant="outlined" sx={{ p: 1, borderRadius: 1.5 }}><Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={.5}><Typography sx={{ fontWeight: 700, fontSize: 13 }}>{displayValue(model.model, "Model not recorded")} · {displayValue(model.backend, "Harness not recorded")}</Typography><Typography color="text.secondary" sx={{ fontSize: 12.5 }}>{currentCount} latest saved result{currentCount === 1 ? "" : "s"} (one per run) · {Number(model.current_problem_count || 0)} problems · {Number(model.current_flagged_step_count || 0)} flagged steps · {model.current_flagged_labels?.length || 0} labels{Number(model.historical_review_count || 0) ? ` · ${model.historical_review_count} superseded review revisions` : ""}</Typography></Stack>{hasSavedReviews && <Typography color="text.secondary" sx={{ mt: .35, fontSize: 12 }}>Evidence: {sourceCount} source screenshots · {suppliedCount} sent to reviewer · {citedCount} cited by assessment{model.evidence_mode === "text_only" ? " · text-only review" : legacyImageDelivery ? " · legacy image-delivery metadata not recorded" : ""}</Typography>}</Paper>; })}</Stack></Box>}
    </Panel>
    <Panel sx={{ mb: 2 }}>
      <Alert severity="info" sx={{ mb: 1.5 }}>{`Review flags match source revision ${displayValue(revision.revision, "current")}. ${excludedOverlayReviewCount ? `${excludedOverlayReviewCount} older or unaligned reviews are listed below.` : "Select a review to inspect its flags, or view all together."}`}</Alert>
      <Stack direction={{ xs: "column", md: "row" }} gap={2} alignItems="stretch">
        {!compactSteps && !sourceStepsCollapsed && <Box sx={{ width: { md: 280, lg: 304 }, flex: "0 0 auto", minWidth: 0 }}>{sourceStepNavigator}</Box>}
        <Box ref={sourceEvidenceRef} sx={{ flex: 1, minWidth: 0, scrollMarginTop: 16 }}>
          <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ xs: "stretch", sm: "center" }} justifyContent="space-between" gap={1} sx={{ mb: 1.2 }}>
            <SectionTitle title={selectedSourceStep ? `Source step ${selectedSourceStepId}` : "Source evidence"} subtitle={selectedSourceStep ? `${sourceSteps.findIndex((step, index) => String(step.step_id ?? index + 1) === selectedSourceStepId) + 1} of ${sourceSteps.length} recorded steps` : "Choose a source step to inspect its evidence."} />
            <Stack direction="row" gap={.7} flexWrap="wrap"><Button size="small" variant={compactSteps ? "outlined" : "text"} startIcon={compactSteps ? <FormatListNumberedRounded /> : undefined} onClick={() => compactSteps ? setStepPickerOpen(true) : setSourceStepsCollapsed(value => !value)}>{compactSteps ? "All steps" : sourceStepsCollapsed ? "Show steps" : "Hide steps"}</Button><Button size="small" variant="outlined" disabled={!selectedSourceStep || sourceSteps.findIndex((step, index) => String(step.step_id ?? index + 1) === selectedSourceStepId) <= 0} onClick={() => selectSourceStepAt(sourceSteps.findIndex((step, index) => String(step.step_id ?? index + 1) === selectedSourceStepId) - 1)}>Previous</Button><Button size="small" variant="outlined" disabled={!selectedSourceStep || sourceSteps.findIndex((step, index) => String(step.step_id ?? index + 1) === selectedSourceStepId) >= sourceSteps.length - 1} onClick={() => selectSourceStepAt(sourceSteps.findIndex((step, index) => String(step.step_id ?? index + 1) === selectedSourceStepId) + 1)}>Next</Button></Stack>
          </Stack>
          <Box sx={{ width: "100%", minHeight: selectedSourceScreenshotUrl && !sourceScreenshotFailed ? { xs: 140, md: 260 } : 120, maxHeight: "72vh", display: "grid", placeItems: "center", overflow: "auto", bgcolor: "action.hover", border: "1px solid", borderColor: "divider", borderRadius: 2.5 }}>
            {selectedSourceScreenshotUrl && !sourceScreenshotFailed && <Link href={selectedSourceScreenshotUrl} target="_blank" rel="noopener noreferrer" aria-label={`Open screenshot for source step ${selectedSourceStepId} at full size`} sx={{ display: "block", width: "100%", lineHeight: 0, cursor: "zoom-in" }}><Box component="img" src={selectedSourceScreenshotUrl} alt={`Source screenshot for step ${selectedSourceStepId}`} className="screenshot-full" sx={{ maxHeight: "72vh", objectFit: "contain" }} onError={() => setSourceScreenshotFailed(true)} /></Link>}
            {selectedSourceStep && !selectedSourceScreenshotUrl && <Typography color="text.secondary" sx={{ p: 2, textAlign: "center", fontSize: 13 }}>{sourceScreenshotMissing ? "The recorded screenshot is missing from this source step." : "No screenshot was recorded for this source step."}</Typography>}
            {selectedSourceStep && selectedSourceScreenshotUrl && sourceScreenshotFailed && <Typography color="text.secondary" sx={{ p: 2, textAlign: "center", fontSize: 13 }}>The screenshot source exists, but it could not be loaded.</Typography>}
          </Box>
          {selectedSourceScreenshotUrl && !sourceScreenshotFailed && <Link href={selectedSourceScreenshotUrl} target="_blank" rel="noopener noreferrer" sx={{ display: "inline-flex", alignItems: "center", gap: .5, mt: .7, fontSize: 12 }}>Open screenshot at full size<OpenInNewRounded sx={{ fontSize: 14 }} /></Link>}
          {selectedSourceStep && <Stack gap={1.2} sx={{ mt: 1.4 }}>
            <Stack direction={{ xs: "column", md: "row" }} gap={1.2}><Paper variant="outlined" sx={{ p: 1.2, flex: 1, minWidth: 0 }}><Typography sx={{ fontWeight: 700, fontSize: 13 }}>Recorded intent</Typography><Typography sx={{ mt: .3, fontSize: 14, overflowWrap: "anywhere" }}>{displayValue(object(selectedSourceStep.intent).text || selectedSourceStep.intent)}</Typography></Paper><Paper variant="outlined" sx={{ p: 1.2, flex: 1, minWidth: 0 }}><Typography sx={{ fontWeight: 700, fontSize: 13 }}>Action</Typography><Typography sx={{ mt: .3, fontSize: 14, overflowWrap: "anywhere" }}>{displayValue(selectedSourceStep.action)}</Typography></Paper><Paper variant="outlined" sx={{ p: 1.2, flex: 1, minWidth: 0 }}><Typography sx={{ fontWeight: 700, fontSize: 13 }}>Observation</Typography><Typography sx={{ mt: .3, fontSize: 14, overflowWrap: "anywhere" }}>{displayValue(selectedSourceStep.observation || selectedSourceStep.observed_ui)}</Typography></Paper></Stack>
            <Box><Typography variant="h3" sx={{ mb: .5 }}>{sourceReviewFilter === "all" ? "Review overlays" : "Selected review"}</Typography><Typography color="text.secondary" sx={{ mb: 1, fontSize: 13 }}>Flags are model assessments. Use the evidence and review status below before accepting a diagnosis.</Typography>{!visibleSourceReviews.length ? <Typography color="text.secondary" sx={{ fontSize: 13 }}>No saved reviews are available to overlay.</Typography> : <Stack gap={.8}>{visibleSourceReviews.map(({ review, number }, reviewIndex) => {
              const evidence = reviewFlagsAtStep(review, selectedSourceStepId);
              const provenance = object(review.provenance || review.review_provenance);
              const textOnly = provenance.evidence_mode === "text_only" || (!Array.isArray(provenance.supplied_image_step_ids) && Array.isArray(provenance.inspected_image_step_ids) && provenance.inspected_image_step_ids.length === 0);
              const sent = Array.isArray(provenance.supplied_image_step_ids) ? (idList(provenance.supplied_image_step_ids).includes(selectedSourceStepId) ? "yes" : "no") : textOnly ? "no" : "not recorded";
              const cited = Array.isArray(provenance.cited_image_step_ids) ? (idList(provenance.cited_image_step_ids).includes(selectedSourceStepId) ? "yes" : "no") : textOnly ? "no" : "not recorded";

              return <Paper key={reviewIdForFilter(review, reviewIndex)} variant="outlined" sx={{ p: 1.2, borderRadius: 2 }}><Box sx={{ display: "grid", gridTemplateColumns: "64px minmax(0, 1fr)", columnGap: 1, rowGap: .25, "& .MuiTypography-root": { fontSize: 12, overflowWrap: "anywhere" } }}><Typography color="text.secondary">Review</Typography><Typography fontWeight={700}>{number}</Typography><Typography color="text.secondary">Model</Typography><Typography>{displayValue(review.model, "Not recorded")}</Typography><Typography color="text.secondary">Harness</Typography><Typography>{displayValue(review.backend, "Not recorded")}</Typography><Typography color="text.secondary">Run</Typography><Link component={RouterLink} to={`/runs/${encodeURIComponent(String(review.run_id || review.batch_id || ""))}`} sx={{ fontSize: 12, overflowWrap: "anywhere" }}>{displayValue(review.run_name, `Run ${reviewIndex + 1}`)}</Link></Box><Stack direction="row" gap={.6} flexWrap="wrap" sx={{ mt: .7 }}><Chip size="small" variant="outlined" label={`Screenshot sent to this review: ${sent}`} /><Chip size="small" variant="outlined" label={`Frame cited by this review: ${cited}`} /></Stack>{textOnly && <Alert severity="info" sx={{ mt: .8 }}>This review received text only. Screenshots visible above were not supplied to that model. Its original assessment is preserved.</Alert>}{evidence.flags.length ? <Stack gap={.5} sx={{ mt: .8 }}>{evidence.flags.map((flag, flagIndex) => <StepFlag key={`${flag.kind}-${flagIndex}`} {...flag} />)}</Stack> : <Typography color="text.secondary" sx={{ mt: .6, fontSize: 13 }}>No problem or recovery flag recorded for this step.</Typography>}{evidence.relatedEpisodes.map((episode, episodeIndex) => <Paper key={`${episode.episode_id || episodeIndex}-detail`} variant="outlined" sx={{ mt: .8, p: 1, borderRadius: 1.5 }}><Typography sx={{ fontWeight: 700, fontSize: 13 }}>{String(episode.label_name || episode.label_id || "Problem details")}</Typography><Typography color="text.secondary" sx={{ mt: .4, fontSize: 12.5 }}><strong>Definition:</strong> {displayValue(episode.label_description || episode.label_definition || episode.definition || episode.description, "Draft label: use the evidence-backed mechanism below.")}</Typography><Typography color="text.secondary" sx={{ mt: .4, fontSize: 12.5 }}><strong>Mechanism:</strong> {displayValue(episode.mechanism)}</Typography></Paper>)}{evidence.reviewStep && <><StatusTag value={evidence.reviewStep.review_status === "insufficient_evidence" ? "Cannot confirm from evidence" : evidence.reviewStep.review_status || "review recorded"} /><Typography sx={{ mt: .5, fontSize: 13, whiteSpace: "pre-wrap" }}>{displayValue(evidence.reviewStep.assessment, "No assessment recorded.")}</Typography>{evidence.reviewStep.intent && <Typography sx={{ mt: .6, fontSize: 13 }}><strong>Reviewer intent interpretation:</strong> {displayValue(object(evidence.reviewStep.intent).kind)} · {displayValue(object(evidence.reviewStep.intent).text || evidence.reviewStep.intent)}</Typography>}{evidence.reviewStep.observed_ui && <Typography color="text.secondary" sx={{ mt: .4, fontSize: 12.5 }}>Observed: {displayValue(evidence.reviewStep.observed_ui)}</Typography>}{evidence.reviewStep.effect && <Typography color="text.secondary" sx={{ mt: .4, fontSize: 12.5 }}>Effect: {displayValue(evidence.reviewStep.effect)}</Typography>}</>}</Paper>;
            })}</Stack>}</Box>
          </Stack>}
        </Box>
      </Stack>
    </Panel>
    <Grid container spacing={2} alignItems="flex-start">
      <Grid size={{ xs: 12, lg: 5 }}><Panel><SectionTitle title="Current source revision" subtitle={`Updated ${formatDate(revision.created_at || task.updated_at)}`} />
        <Stack gap={1.2}><BenchmarkResult task={task} />
          <Box><Typography color="text.secondary" sx={{ fontSize: 13, fontWeight: 700 }}>Instruction</Typography><Typography sx={{ mt: .3, whiteSpace: "pre-wrap" }}>{String(task.instruction || definition.instruction || "No instruction recorded.")}</Typography></Box>
          <Box><Typography color="text.secondary" sx={{ fontSize: 13, fontWeight: 700 }}>Steps</Typography><Typography>{Array.isArray(task.steps) ? task.steps.length : displayValue(task.step_count, "Not recorded")}</Typography></Box>

        </Stack>
      </Panel></Grid>
      <Grid size={{ xs: 12, lg: 7 }}><Stack gap={2}>
        <Panel><SectionTitle title="Runs containing this task" subtitle="Original benchmark results, review processing, and review assessments are listed separately for each run." />
          {!runs.length ? <Typography color="text.secondary">This task has not been included in a run yet.</Typography> : <Box sx={{ maxWidth: "100%", overflowX: "auto" }}><Table size="small" sx={{ minWidth: 900 }}><TableHead><TableRow><TableCell>Run</TableCell><TableCell>Original task result</TableCell><TableCell>Review processing</TableCell><TableCell>Review assessment</TableCell><TableCell>Created</TableCell><TableCell /></TableRow></TableHead><TableBody>{runs.map((run, index) => {
            const runId = rowId(run);
            const memberId = String(run.member_id || run.run_member_id || "");
            const runTaskId = String(run.task_id || taskKey);
            const runArchived = Boolean(run.archived || run.archived_at);
            const archiveParam = runArchived ? "include_archived=true" : "";
            const runQuery = archiveParam ? `?${archiveParam}` : "";
            const reviewParams = new URLSearchParams();
            if (runArchived) reviewParams.set("include_archived", "true");
            if (memberId) reviewParams.set("member_id", memberId);
            const reviewQuery = reviewParams.size ? `?${reviewParams.toString()}` : "";
            const jobs = Array.isArray(run.jobs) ? run.jobs as Row[] : [];
            const latestJob = jobs.at(-1);
            const failureJob = [...jobs].reverse().find(job => String(job.status || "").toLowerCase() === "failed" || Boolean(job.error));
            const latestReview = object((Array.isArray(run.reviews) ? run.reviews as Row[] : []).at(-1));
            const latestReviewData = object(latestReview.review);
            const reviewSummary = object(run.review_summary);
            const processingStatus = String(run.processing_status || run.status || "not started").replaceAll("_", " ");
            const reviewCount = Number(reviewSummary.review_count ?? (Array.isArray(run.reviews) ? run.reviews.length : 0));
            const reviewEpisodes = Array.isArray(latestReviewData.episodes) ? latestReviewData.episodes as Row[] : undefined;
            const flaggedStepIds = new Set<string>();
            for (const episode of reviewEpisodes || []) {
              for (const stepId of idList(episode.onset_step_ids)) flaggedStepIds.add(stepId);
              if (episode.first_observed_step_id !== undefined && episode.first_observed_step_id !== null) flaggedStepIds.add(String(episode.first_observed_step_id));
            }
            const problemCount = reviewSummary.problem_count === undefined ? reviewEpisodes?.length : Number(reviewSummary.problem_count);
            const flaggedStepCount = reviewSummary.flagged_step_count === undefined ? (reviewEpisodes ? flaggedStepIds.size : undefined) : Number(reviewSummary.flagged_step_count);
            const labelCount = Array.isArray(reviewSummary.flagged_labels) ? reviewSummary.flagged_labels.length : reviewEpisodes ? new Set(reviewEpisodes.map(episode => String(episode.label_id || episode.label_name || "")).filter(Boolean)).size : undefined;
            const assessment = reviewCount ? String(latestReviewData.result || run.review_result || (problemCount === undefined ? "Assessment recorded" : problemCount ? "Issues recorded" : "No issues recorded")) : processingStatus === "failed" ? "Not available: review processing failed" : "Not recorded";
            const jobId = String(failureJob?.id || failureJob?.job_id || latestJob?.id || latestJob?.job_id || run.job_id || "");
            const provenance = run.review_provenance || latestReview.provenance;
            const evidence = evidenceCoverageText(provenance, reviewSummary, idList(run.source_image_step_ids).length);
            return <TableRow key={runId || index} hover>
              <TableCell><Typography component={RouterLink} to={`/runs/${encodeURIComponent(runId)}${runQuery}`} sx={{ color: "primary.main", fontWeight: 700, textDecoration: "none" }}>{displayValue(run.run_name || run.name, `Run ${index + 1}`)}</Typography><Typography color="text.secondary" sx={{ fontSize: 12 }}>{runId}</Typography>{Array.isArray(run.reviews) && (run.reviews as Row[]).length > 0 && <Typography color="text.secondary" sx={{ mt: .4, fontSize: 12 }}>{(run.reviews as Row[]).map(review => `${String(review.model || "Model not recorded")} (${String(review.backend || "harness not recorded")})`).join(" · ")}</Typography>}</TableCell>
              <TableCell><BenchmarkResult task={run} compact /></TableCell>
              <TableCell><Stack gap={.35}><StatusTag value={`Review processing: ${processingStatus}`} />{Boolean(failureJob?.error) && <Typography color="error.main" sx={{ maxWidth: 250, fontSize: 12.5, overflowWrap: "anywhere" }}>{reviewProcessingError(failureJob?.error)}</Typography>}<Typography color="text.secondary" sx={{ fontSize: 12 }}>Attempt {String(latestJob?.attempt_count ?? failureJob?.attempt_count ?? run.attempt_count ?? "not recorded")}{(latestJob?.max_attempts ?? failureJob?.max_attempts) ? ` / ${latestJob?.max_attempts ?? failureJob?.max_attempts}` : ""}{jobId && <> · <Link component={RouterLink} to={`/jobs/${encodeURIComponent(jobId)}`}>Job details</Link></>}</Typography></Stack></TableCell>
              <TableCell><Stack gap={.35}><StatusTag value={assessment} />{reviewCount > 0 && <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>{problemCount ?? "Not recorded"} problem flags · {flaggedStepCount ?? "Not recorded"} flagged steps · {labelCount ?? "Not recorded"} labels</Typography>}{reviewCount > 0 && <Typography color="text.secondary" sx={{ fontSize: 12 }}>{evidence.sourceCount} source screenshots · {evidence.sentText} · {evidence.citedText}{evidence.textOnly ? " · text-only review" : evidence.legacy ? " · legacy image-delivery metadata not recorded" : ""}{evidence.reason ? ` · ${evidence.reason}` : ""}</Typography>}</Stack></TableCell>
              <TableCell>{formatDate(run.created_at || run.run_created_at || run.started_at || run.created_on || run.created)}</TableCell>
              <TableCell><Button size="small" component={RouterLink} to={`/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(runTaskId)}${reviewQuery}`}>Open task</Button></TableCell>
            </TableRow>;
          })}</TableBody></Table></Box>}
        </Panel>
        <Panel><SectionTitle title="Reviews" subtitle="Filter saved reviews by harness or model. Compare two reviews of the same source revision." action={<Button component={RouterLink} to={compareUrl || "#"} disabled={!compareUrl} variant="outlined" size="small" sx={{ width: { xs: "100%", sm: "auto" } }} startIcon={<CompareArrowsRounded />}>Compare {selectedReviewIds.length ? `(${selectedReviewIds.length}/2)` : "reviews"}</Button>} />
          {selectedReviewIds.length === 1 && <Alert severity="info" sx={{ mb: 1.3 }}>Select one more review of the same source revision. Reviews from other revisions are unavailable for this comparison.</Alert>}
          {selectedReviewIds.length === 2 && <Alert severity="success" sx={{ mb: 1.3 }}>Two reviews selected. Open Compare to inspect their differences.</Alert>}
          {!!reviews.length && <Stack direction={{ xs: "column", sm: "row" }} gap={1} sx={{ mb: 1.4 }}>
            <FormControl size="small" fullWidth><Select value={backendFilter} onChange={event => { setBackendFilter(event.target.value); setSelectedReviewIds([]); }} displayEmpty inputProps={{ "aria-label": "Filter reviews by harness" }}><MenuItem value="all">All harnesses</MenuItem>{backendOptions.map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</Select></FormControl>
            <FormControl size="small" fullWidth><Select value={modelFilter} onChange={event => { setModelFilter(event.target.value); setSelectedReviewIds([]); }} displayEmpty inputProps={{ "aria-label": "Filter reviews by model" }}><MenuItem value="all">All models</MenuItem>{modelOptions.map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</Select></FormControl>
          </Stack>}
          {!reviews.length ? <Typography color="text.secondary">No reviews are recorded for this task.</Typography> : !filteredReviews.length ? <Typography color="text.secondary">No reviews match these filters.</Typography> : <Stack gap={1}>{filteredReviews.map((review, index) => {
            const runId = String(review.run_id || review.batch_id || "");
            const run = runs.find(item => rowId(item) === runId);
            const memberId = String(review.member_id || run?.member_id || "");
            const id = reviewId(review);
            const nestedReview = object(review.review);
            const revisionId = sourceRevisionId(review);
            const runArchived = Boolean(run?.archived || run?.archived_at);
            const reviewParams = new URLSearchParams();
            if (runArchived) reviewParams.set("include_archived", "true");
            if (memberId) reviewParams.set("member_id", memberId);
            const reviewQuery = reviewParams.size ? `?${reviewParams.toString()}` : "";
            const summary = nestedReview.summary ?? review.summary;
            const openReviewPath = `/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(String(review.task_id || taskKey))}${reviewQuery}`;
            return <Paper key={id || `${runId}-${index}`} variant="outlined" sx={{ p: 1.4, borderRadius: 2, position: "relative", "&:hover": { borderColor: "primary.main" }, "&:has(a:focus-visible)": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 } }}><Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} justifyContent="space-between" gap={1}><Stack direction="row" alignItems="center" gap={.5}><Checkbox size="small" sx={{ position: "relative", zIndex: 2 }} checked={Boolean(id && selectedReviewIds.includes(id))} disabled={!canSelectReview(review)} onChange={(_, checked) => toggleReview(review, checked)} inputProps={{ "aria-label": `Select ${String(review.model || "model not recorded")} review from ${String(review.run_name || run?.name || "run")}` }} /><Box sx={{ minWidth: 0 }}><Typography component={RouterLink} to={openReviewPath} sx={{ fontWeight: 650, color: "text.primary", textDecoration: "none", overflowWrap: "anywhere", "&::after": { content: '""', position: "absolute", inset: 0, borderRadius: 2, zIndex: 1 } }}>{displayValue(review.run_name || run?.run_name || run?.name, "Review")}</Typography><Typography color="text.secondary" sx={{ fontSize: 12 }}>{String(review.review_kind || "Review kind not recorded")} · {formatDate(review.created_at || run?.created_at)}</Typography><Typography color="text.secondary" sx={{ fontSize: 12 }}>{displayValue(review.backend, "Harness not recorded")} · {displayValue(review.model, "Model not recorded")} · source revision {displayValue(revisionId, "Not recorded")}</Typography></Box></Stack><Stack direction="row" gap={.7} alignItems="center"><StatusTag value={review.status || review.review_status || "saved"} /><Button size="small" component={RouterLink} to={openReviewPath} sx={{ position: "relative", zIndex: 2 }} disabled={!runId}>Open review</Button></Stack></Stack>{summary !== undefined && summary !== null && <Typography color="text.secondary" sx={{ mt: .8, fontSize: 13 }}>{String(summary)}</Typography>}</Paper>;
          })}</Stack>}
        </Panel>
      </Stack></Grid>
    </Grid>
    <Dialog open={stepPickerOpen && compactSteps} fullScreen disableRestoreFocus slotProps={{ transition: { onExited: () => sourceEvidenceRef.current?.scrollIntoView({ block: "start" }) } }} onClose={() => setStepPickerOpen(false)}><DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", py: 1.2 }}>Choose a source step<IconButton aria-label="Close step picker" onClick={() => setStepPickerOpen(false)}><CloseRounded /></IconButton></DialogTitle><DialogContent dividers sx={{ p: 1.5 }}>{sourceStepNavigator}</DialogContent></Dialog>
    <RunComposer open={composerOpen} onClose={() => setComposerOpen(false)} initialTaskDefinitionIds={[taskId]} />
  </>;
}
