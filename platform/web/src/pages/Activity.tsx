import { Link as RouterLink, useParams } from "react-router-dom";
import { Alert, Box, Button, Chip, Grid, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import { useApi } from "../hooks";
import type { ReviewAttemptRecord, ReviewJobRecord } from "../types";
import { EmptyState, ErrorState, LoadingState, PageBreadcrumbs, PageHeader, Panel, SectionTitle, StatusTag, TruncationNote, displayValue, formatDate, reviewProcessingError } from "../components";
import { LATEST_PAGE } from "../pagination";

type Row = Record<string, unknown>;
function object(value: unknown): Row { return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {}; }
interface RowsResponse { items?: Row[]; total?: number; activity?: Row[]; jobs?: Row[]; }
function rowsFrom(data: RowsResponse | Row[] | null, key: "activity" | "jobs"): Row[] {
  if (Array.isArray(data)) return data;
  if (!data) return [];
  if (Array.isArray(data.items)) return data.items;
  if (Array.isArray(data[key])) return data[key]!;
  return [];
}
function rowId(row: Row, fallback: number): string { return String(row.id ?? row.job_id ?? row.activity_id ?? fallback); }
function summaryOf(row: Row): string { return String(row.summary || row.message || row.action || row.kind || row.event || "Workspace event"); }
function actorOf(row: Row): string { return String(row.actor_name || row.actor_email || row.user_name || row.user_email || "Workspace"); }
function shortId(value: unknown): string {
  const id = String(value ?? "");
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}
function recordedNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return null;
}
function isSavedReplay(job: Row): boolean {
  const usage = object(job.usage);
  return String(usage.kind || job.backend || job.source_kind || "").toLowerCase() === "saved_replay";
}
function tokenSummary(job: Row): string {
  const usage = object(job.usage);
  const totals = object(job.usage_tokens);
  const total = recordedNumber(usage.total_tokens, usage.totalTokens, totals.total_tokens, totals.totalTokens, job.usage_tokens);
  if (total !== null) return `Tokens ${total.toLocaleString()}`;
  const input = recordedNumber(usage.input_tokens, usage.prompt_tokens, totals.input_tokens, totals.prompt_tokens);
  const output = recordedNumber(usage.output_tokens, usage.completion_tokens, totals.output_tokens, totals.completion_tokens);
  if (input !== null && output !== null) return `Tokens ${(input + output).toLocaleString()} · ${input.toLocaleString()} in · ${output.toLocaleString()} out`;
  if (input !== null || output !== null) return `Tokens ${input === null ? "Unknown" : input.toLocaleString()} in · ${output === null ? "Unknown" : output.toLocaleString()} out`;
  return "Unknown";
}
function costSummary(job: Row): string {
  const cost = recordedNumber(job.cost_usd);
  return cost === null ? "Unknown" : `$${cost.toFixed(4)} USD`;
}

export function ActivityPage() {
  const state = useApi<RowsResponse | Row[]>("/activity", 0, LATEST_PAGE);
  const entries = rowsFrom(state.data, "activity");
  return <>
    <PageHeader eyebrow="AUDIT TRAIL" title="Activity" description="Append-only workspace events for membership, dataset, run, review, and taxonomy changes." action={<Button variant="outlined" startIcon={<RefreshRounded />} onClick={state.reload}>Refresh</Button>} />
    {state.loading && <LoadingState label="Loading workspace activity…" />}
    {state.error && <ErrorState message={state.error} onRetry={state.reload} />}
    {!state.loading && !state.error && !entries.length && <EmptyState title="No activity recorded" description="Workspace changes and review actions will appear here when they are recorded by the API." />}
    <TruncationNote list={state.data} noun="events (newest first)" />
    {!!entries.length && <Panel><SectionTitle title="Workspace events" subtitle={`${entries.length} events returned by the activity API`} /><Stack gap={0} divider={<Box sx={{ borderBottom: "1px solid", borderColor: "divider" }} />}>
      {entries.map((entry, index) => <Grid key={rowId(entry, index)} container spacing={1.3} alignItems="flex-start" sx={{ py: 1.5 }}>
        <Grid size={{ xs: 12, sm: 2.4 }}><Typography color="text.secondary" sx={{ fontSize: 13 }}>{formatDate(entry.created_at || entry.timestamp)}</Typography></Grid>
        <Grid size={{ xs: 12, sm: 7.6 }}><Typography sx={{ fontWeight: 700 }}>{summaryOf(entry)}</Typography><Typography color="text.secondary" sx={{ mt: .3, fontSize: 13 }}>{actorOf(entry)}{entry.resource_type || entry.entity_type ? ` · ${String(entry.resource_type || entry.entity_type)} ${String(entry.resource_id || entry.entity_id || "")}` : ""}</Typography>{Boolean(entry.detail) && <Typography color="text.secondary" sx={{ mt: .5, whiteSpace: "pre-wrap", fontSize: 13 }}>{displayValue(entry.detail)}</Typography>}</Grid>
        <Grid size={{ xs: 12, sm: 2 }}><Chip size="small" variant="outlined" label={String(entry.kind || entry.action || "event").replaceAll("_", " ")} /></Grid>
      </Grid>)}
    </Stack></Panel>}
  </>;
}

export function JobsPage() {
  const state = useApi<RowsResponse | Row[]>("/jobs", 0, LATEST_PAGE);
  const jobs = rowsFrom(state.data, "jobs");
  return <>
    <PageHeader eyebrow="PROCESSING QUEUE" title="Jobs" description="Authoritative job state, attempts, ownership, and usage are reported by the local queue API." action={<Button variant="outlined" startIcon={<RefreshRounded />} onClick={state.reload}>Refresh</Button>} />
    {state.loading && <LoadingState label="Loading jobs…" />}
    {state.error && <ErrorState message={state.error} onRetry={state.reload} />}
    {!state.loading && !state.error && !jobs.length && <EmptyState title="No jobs in the queue" description="Run tasks appear here after a run is explicitly started. Execution settings and saved evidence stay linked to each job." />}
    <TruncationNote list={state.data} noun="jobs (newest first)" />
    {!!jobs.length && <Panel><SectionTitle title="Review processing jobs" subtitle={`${jobs.length} records returned by the queue API. Job state describes processing, not the original benchmark result or the review assessment.`} />
      <Box sx={{ overflowX: "auto" }}><Table size="medium"><TableHead><TableRow><TableCell>Job</TableCell><TableCell>Review processing</TableCell><TableCell>Attempts</TableCell><TableCell>Usage / cost</TableCell><TableCell>Updated</TableCell><TableCell align="right">Action</TableCell></TableRow></TableHead><TableBody>
        {jobs.map((job, index) => {
          const id = rowId(job, index);
          const status = String(job.status || job.state || "unknown").toLowerCase();
          const taskLabel = String(job.task_title || job.name || (job.task_id ? `Task ${shortId(job.task_id)}` : `Job ${shortId(id)}`));
          const attemptValue = job.attempt ?? job.attempt_count;
          const attemptText = attemptValue === undefined || attemptValue === null ? "Unknown" : String(attemptValue);
          const maxAttemptText = job.max_attempts === undefined || job.max_attempts === null ? "" : ` / ${String(job.max_attempts)}`;
          const replay = isSavedReplay(job);
          const runId = String(job.run_id || job.batch_id || "");
          return <TableRow key={id} hover>
            <TableCell>
              <Typography component={RouterLink} to={`/jobs/${encodeURIComponent(id)}`} sx={{ fontWeight: 750, color: "primary.main", textDecoration: "none" }}>{taskLabel}</Typography>
              <Typography color="text.secondary" sx={{ fontSize: 12 }}>Job {shortId(id)}{runId ? ` · run ${shortId(runId)}` : ""}{job.task_id ? ` · task ${shortId(job.task_id)}` : ""}</Typography>
              {status === "failed" && Boolean(job.error) && <Typography color="error.main" sx={{ mt: .5, fontSize: 12.5, overflowWrap: "anywhere" }}>Review processing failed: {reviewProcessingError(job.error)}</Typography>}
              <Box component="details" sx={{ mt: .5, fontSize: 12 }}>
                <Box component="summary" sx={{ color: "text.secondary", cursor: "pointer", width: "fit-content" }}>Full IDs and job data</Box>
                <Box sx={{ mt: .5 }}>
                  <Typography component="div" sx={{ fontSize: 12 }}>Job ID: {id}<br />Run ID: {String(runId || "Unknown")}<br />Task ID: {String(job.task_id ?? "Unknown")}</Typography>
                  <Typography color="text.secondary" sx={{ mt: .5, fontSize: 11 }}>Raw job data</Typography>
                  <Typography component="pre" sx={{ m: 0, maxWidth: 420, overflowX: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 11 }}>{JSON.stringify(job, null, 2)}</Typography>
                </Box>
              </Box>
            </TableCell>
            <TableCell><StatusTag value={`Review processing: ${status}`} /></TableCell>
            <TableCell>Attempt {attemptText}{maxAttemptText}</TableCell>
            <TableCell>
              {replay ? <Typography sx={{ fontSize: 13 }}>Saved replay · no model call</Typography> : <>
                <Typography sx={{ fontSize: 13 }}>{tokenSummary(job)}</Typography>
                <Typography color="text.secondary" sx={{ fontSize: 12 }}>Cost {costSummary(job)}</Typography>
              </>}
            </TableCell>
            <TableCell>{formatDate(job.updated_at || job.created_at)}</TableCell>
            <TableCell align="right"><Stack direction="row" gap={.5} justifyContent="flex-end"><Button size="small" component={RouterLink} to={`/jobs/${encodeURIComponent(id)}`} variant="outlined">Job details</Button><Button size="small" variant="outlined" component={RouterLink} to={runId ? `/runs/${encodeURIComponent(runId)}` : "/runs"} disabled={!runId} aria-label={`Open run for ${taskLabel}`}>Open run</Button></Stack></TableCell>
          </TableRow>;
        })}
      </TableBody></Table></Box>
    </Panel>}
  </>;
}

interface JobDetailResponse extends ReviewJobRecord { job?: ReviewJobRecord; run_name?: string; budget_usd?: number; max_total_budget_usd?: number; cumulative_cost_usd?: number | null; unknown_cost_attempts?: number; backend?: string; model?: string; }

export function JobDetailPage() {
  const { id = "" } = useParams();
  const state = useApi<JobDetailResponse>(id ? `/jobs/${encodeURIComponent(id)}` : null);
  const job = state.data?.job || state.data;
  if (state.loading) return <LoadingState label="Loading review job and attempt history…" />;
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (!job) return <EmptyState title="Review job not found" description="This job may have been removed or you may not have access." action={<Button component={RouterLink} to="/jobs" variant="outlined">Back to jobs</Button>} />;
  const runId = String(job.run_id || job.batch_id || "");
  const taskId = String(job.task_id || "");
  const attemptCount = Number(job.attempt_count || 0);
  const maxAttempts = Number(job.max_attempts || 0);
  const budget = recordedNumber(job.budget_usd, object(job.preset).budget_usd, object(job.execution).budget_usd);
  const plannedAllowance = recordedNumber(job.max_total_budget_usd) ?? (budget !== null && maxAttempts ? budget * maxAttempts : null);
  const attempts = Array.isArray(job.attempts) ? job.attempts as ReviewAttemptRecord[] : [];
  const unknownCostAttempts = Number(job.unknown_cost_attempts || 0);
  const recordedCost = job.cumulative_cost_usd !== undefined ? job.cumulative_cost_usd : job.cost_usd;
  const isFailed = String(job.status || "").toLowerCase() === "failed";
  return <>
    <PageBreadcrumbs items={[{ label: "Jobs", to: "/jobs" }, ...(runId ? [{ label: String(job.run_name || "Run"), to: `/runs/${encodeURIComponent(runId)}` }] : []), { label: `Job ${shortId(job.id)}` }]} />
    <PageHeader eyebrow="REVIEW PROCESSING" title={String(job.task_title || `Job ${shortId(job.id)}`)} description={`${displayValue(job.review_kind, "Review job")} · ${displayValue(job.backend, "Harness not recorded")} · ${displayValue(job.model, "Model not recorded")}`} action={<Stack direction="row" gap={.7} flexWrap="wrap">{runId && <Button component={RouterLink} to={`/runs/${encodeURIComponent(runId)}`} variant="outlined">Open run</Button>}{runId && taskId && <Button component={RouterLink} to={`/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskId)}${job.member_id ? `?member_id=${encodeURIComponent(String(job.member_id))}` : ""}`} variant="contained">Open task</Button>}</Stack>} />
    {isFailed && Boolean(job.error) && <Alert severity="error" sx={{ mb: 2 }}><strong>Review processing failed:</strong> {reviewProcessingError(job.error)}</Alert>}
    <Grid container spacing={1.6} sx={{ mb: 2 }}>
      <Grid size={{ xs: 6, md: 3 }}><Panel><Typography color="text.secondary" sx={{ fontSize: 13 }}>Review processing</Typography><Box sx={{ mt: .7 }}><StatusTag value={String(job.status || "unknown")} /></Box></Panel></Grid>
      <Grid size={{ xs: 6, md: 3 }}><Panel><Typography color="text.secondary" sx={{ fontSize: 13 }}>Attempts</Typography><Typography variant="h3" sx={{ mt: .7 }}>{attemptCount} / {maxAttempts || "Not recorded"}</Typography></Panel></Grid>
      <Grid size={{ xs: 6, md: 3 }}><Panel><Typography color="text.secondary" sx={{ fontSize: 13 }}>{unknownCostAttempts && recordedCost != null ? "Known cost subtotal" : "Recorded cost"}</Typography><Typography variant="h3" sx={{ mt: .7 }}>{costSummary({ cost_usd: recordedCost })}</Typography><Typography color="text.secondary" sx={{ fontSize: 12 }}>{unknownCostAttempts ? `${unknownCostAttempts} ${unknownCostAttempts === 1 ? "attempt has" : "attempts have"} unknown cost. Total spend is not established.` : "Across recorded attempts"}</Typography></Panel></Grid>
      <Grid size={{ xs: 6, md: 3 }}><Panel><Typography color="text.secondary" sx={{ fontSize: 13 }}>Planned allowance, including retries</Typography><Typography variant="h3" sx={{ mt: .7 }}>{plannedAllowance === null ? "Not recorded" : `$${plannedAllowance.toFixed(2)}`}</Typography><Typography color="text.secondary" sx={{ fontSize: 12 }}>Per-attempt allowance: {budget === null ? "Not recorded" : `$${budget.toFixed(2)}`} · billing estimate, not a provider spending cap.</Typography></Panel></Grid>
    </Grid>
    <Panel><SectionTitle title="Attempt history" subtitle={`${attempts.length} recorded attempts${maxAttempts ? ` · ${maxAttempts} maximum attempts` : ""}`} />
      {!attempts.length ? <Typography color="text.secondary">No attempt history was returned for this job.</Typography> : <Box sx={{ overflowX: "auto" }}><Table size="small"><TableHead><TableRow><TableCell>Attempt</TableCell><TableCell>Review processing</TableCell><TableCell>Error reason</TableCell><TableCell>Usage / cost</TableCell><TableCell>Started</TableCell><TableCell>Finished</TableCell></TableRow></TableHead><TableBody>{attempts.map((attempt, index) => <TableRow key={`${attempt.attempt_number}-${index}`}><TableCell>{attempt.attempt_number}</TableCell><TableCell><StatusTag value={`Review processing: ${String(attempt.status || "unknown")}`} /></TableCell><TableCell sx={{ maxWidth: 420, overflowWrap: "anywhere", color: attempt.error ? "error.main" : "text.secondary" }}>{attempt.error ? reviewProcessingError(attempt.error) : "No error recorded"}</TableCell><TableCell>{tokenSummary({ usage: attempt.usage })}<Typography color="text.secondary" sx={{ fontSize: 12 }}>Cost {costSummary(attempt as unknown as Row)}</Typography></TableCell><TableCell>{formatDate(attempt.started_at)}</TableCell><TableCell>{formatDate(attempt.finished_at)}</TableCell></TableRow>)}</TableBody></Table></Box>}
    </Panel>
  </>;
}
