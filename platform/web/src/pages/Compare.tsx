import { useEffect, useMemo, useState } from "react";
import { Alert, Box, Button, Checkbox, Chip, FormControlLabel, Grid, Link, Stack, TextField, Typography } from "@mui/material";
import FlagRounded from "@mui/icons-material/FlagRounded";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import { apiRequest } from "../api/client";
import { PageBreadcrumbs, PageHeader, Panel } from "../components/Page";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { StatusTag } from "../components/StatusTag";
import { formatDate } from "../lib/format";
interface Step { step_id: string; review_status: string; assessment: string; effect: string; observed_ui: string; episode_refs: string[]; intent?: {kind: string; text: string}; action?: string }
interface Episode { episode_id: string; problem_number?: number; label_id: string; label_name: string; first_observed_step_id?: string; onset_step_ids: string[]; mechanism: string; recovery: { status: string; step_ids: string[]; rationale: string }; outcome_contribution: string; uncertainty?: string }
interface Review { summary?: string; result?: string; coverage_notes?: string[]; steps?: Step[]; episodes?: Episode[] }
interface Result { id: string; run_id: string; member_id: string; task_id?: string; model?: string; backend?: string; review?: Review; execution?: { model?: string; backend?: string }; created_at: string }
interface Comparison { aligned: { task_definition_id: string; task_revision_id: string; task_revision: number; task_id?: string; dataset_id?: string }; results: Result[]; differences: { field: string; values: { result_id: string; value: unknown }[] }[] }
const episodesAt = (review: Review, stepId: string) => (review.episodes || []).filter(episode => episode.onset_step_ids?.includes(stepId) || episode.recovery?.step_ids?.includes(stepId) || review.steps?.find(step => step.step_id === stepId)?.episode_refs?.includes(episode.episode_id));
export function ComparePage() {
  const [params] = useSearchParams();
  const left = params.get("left"), right = params.get("right");
  const [data, setData] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [onlyDifferent, setOnlyDifferent] = useState(true);
  const [note, setNote] = useState("");
  const [flagged, setFlagged] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [nonce, setNonce] = useState(0);
  useEffect(() => { if (!left || !right) return; let alive = true; setLoading(true); setError(""); setFlagged([]); apiRequest<Comparison>("/analytics/compare", { method: "POST", body: JSON.stringify({ result_ids: [left, right] }) }).then(value => { if (alive) setData(value); }).catch(reason => { if (alive) setError(reason instanceof Error ? reason.message : "Could not compare reviews."); }).finally(() => { if (alive) setLoading(false); }); return () => { alive = false; }; }, [left, right, nonce]);
  const reviews: Review[] = useMemo(() => (data?.results || []).map(result => result.review || Object.fromEntries((data?.differences || []).map(diff => [diff.field, diff.values.find(value => value.result_id === result.id)?.value]))), [data]);
  const stepIds = useMemo(() => [...new Set(reviews.flatMap(review => (review.steps || []).map(step => step.step_id)))], [reviews]);
  const isDifferent = (id: string) => JSON.stringify({ step: reviews[0]?.steps?.find(step => step.step_id === id), episodes: episodesAt(reviews[0] || {}, id) }) !== JSON.stringify({ step: reviews[1]?.steps?.find(step => step.step_id === id), episodes: episodesAt(reviews[1] || {}, id) });
  const changed = stepIds.filter(isDifferent);
  const visible = onlyDifferent ? changed : stepIds;
  const flag = async () => {
    if (!data) return; setBusy(true); setError("");
    try {
      const done = [...flagged];
      for (const result of data.results) {
        if (done.includes(result.id)) continue;
        const taskId = result.task_id || data.aligned.task_id;
        if (!taskId) throw new Error("Task identity was not included in the comparison; feedback could not be attached.");
        await apiRequest(`/runs/${result.run_id}/tasks/${encodeURIComponent(taskId)}/feedback?member_id=${result.member_id}`, { method: "POST", body: JSON.stringify({ text: `Review disagreement flagged. Compared result IDs: ${data.results.map(item => item.id).join(", ")}. Source revision: ${data.aligned.task_revision_id}. ${note.trim()}` }) });
        done.push(result.id); setFlagged([...done]);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save feedback."); }
    finally { setBusy(false); }
  };
  return <><PageBreadcrumbs items={[{ label: "Analytics", to: "/analytics" }, { label: "Compare reviews" }]} /><PageHeader eyebrow="REVIEW COMPARISON" title="Compare model reviews" description="Align the same task and source revision, inspect different labels or explanations, and flag disagreements for human review." />
    {(!left || !right) && <EmptyState title="Choose two reviews" description="Open Analytics, filter to a task, then select two reviews of the same source revision." action={<Button component={RouterLink} to="/analytics" variant="contained">Choose reviews</Button>} />}
    {loading && <LoadingState label="Aligning review evidence…" />}{error && <ErrorState message={error} onRetry={() => setNonce(n => n + 1)} />}
    {!loading && data && <>
      <Alert severity="info" sx={{ mb: 2 }}>Same source revision {data.aligned.task_revision}. {changed.length} of {stepIds.length} steps have different recorded fields. Wording differences alone do not prove either review is wrong.</Alert>
      <Grid container spacing={2} sx={{ mb: 2 }}>{data.results.map((result, i) => <Grid key={result.id} size={{ xs: 12, md: 6 }}><Panel sx={{ height: "100%", borderTop: "3px solid", borderTopColor: i ? "secondary.main" : "primary.main" }}><Typography variant="overline">{i ? "Review B" : "Review A"}</Typography><Typography variant="h3">{result.model || result.execution?.model || "Model not recorded"}</Typography><Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}><Chip size="small" label={result.backend || result.execution?.backend || "Harness not recorded"} /><StatusTag value={reviews[i]?.result} /><Chip size="small" label={`${reviews[i]?.episodes?.length || 0} ${reviews[i]?.episodes?.length === 1 ? "problem" : "problems"}`} /></Stack><Typography sx={{ mt: 1.5 }}>{reviews[i]?.summary || "Summary not recorded."}</Typography><Typography color="text.secondary" sx={{ mt: 1, fontSize: 13 }}>{formatDate(result.created_at)}</Typography><Stack direction="row" gap={2} sx={{ mt: 1 }}><Link component={RouterLink} to={`/runs/${result.run_id}`}>Open run</Link>{(result.task_id || data.aligned.task_id) && <Link component={RouterLink} to={`/runs/${result.run_id}/tasks/${result.task_id || data.aligned.task_id}?member_id=${result.member_id}`}>Open trajectory</Link>}</Stack>{!!reviews[i]?.coverage_notes?.length && <Box component="details" sx={{ mt: 1 }}><Box component="summary" sx={{ cursor: "pointer", color: "text.secondary" }}>Evidence coverage</Box>{reviews[i].coverage_notes?.map((value, j) => <Typography key={j} sx={{ fontSize: 13, mt: .7 }}>{value}</Typography>)}</Box>}</Panel></Grid>)}</Grid>
      <Panel sx={{ mb: 2 }}><Typography variant="h3">Flag for human review</Typography><Typography color="text.secondary" sx={{ mt: .5, mb: 1.5, fontSize: 14 }}>Attach your note to both reviews. Existing results remain unchanged.</Typography><Stack direction={{ xs: "column", md: "row" }} gap={1.5} alignItems={{ md: "flex-start" }}><TextField label="What should a reviewer investigate?" value={note} onChange={event => setNote(event.target.value)} fullWidth multiline minRows={2} disabled={flagged.length === data.results.length} /><Button startIcon={<FlagRounded />} variant="outlined" color="warning" onClick={flag} disabled={busy || !note.trim() || flagged.length === data.results.length} sx={{ flexShrink: 0 }}>{busy ? "Saving…" : flagged.length === data.results.length ? "Feedback saved" : "Flag disagreement"}</Button></Stack>{flagged.length === data.results.length && <Alert severity="success" sx={{ mt: 1.5 }}>Your note is now visible in both review histories.</Alert>}</Panel>
      <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ xs: "flex-start", sm: "center" }} justifyContent="space-between" gap={1} sx={{ mb: 1.5 }}><Typography variant="h3">Step by step</Typography><FormControlLabel control={<Checkbox checked={onlyDifferent} onChange={(_, value) => setOnlyDifferent(value)} />} label="Show differences only" /></Stack>
      {!visible.length && <Panel><Typography>No differing step fields were found in these reviews.</Typography></Panel>}
      <Stack gap={2}>{visible.map(id => <Panel key={id} sx={{ p: 2 }}><Stack direction="row" gap={1} alignItems="center" sx={{ mb: 1.5 }}><Typography fontWeight={800}>Step {id}</Typography>{isDifferent(id) && <Chip size="small" color="warning" variant="outlined" label="Review fields differ" />}</Stack><Grid container spacing={2}>{reviews.map((review, i) => { const step = review.steps?.find(item => item.step_id === id); const episodes = episodesAt(review, id); return <Grid key={i} size={{ xs: 12, md: 6 }}><Box sx={{ minWidth: 0, borderLeft: "2px solid", borderColor: i ? "secondary.main" : "primary.main", pl: 1.5, overflowWrap: "anywhere" }}><Typography variant="overline">Review {i ? "B" : "A"}</Typography>{!step ? <Alert severity="warning">This review did not include this step.</Alert> : <><StatusTag value={step.review_status} /><Typography color="text.secondary" sx={{ mt: .8, fontSize: 13 }}><strong>Intent:</strong> {step.intent?.kind ? `${step.intent.kind} · ` : ""}{step.intent?.text || "Not recorded"}</Typography><Typography color="text.secondary" sx={{ mt: .5, fontSize: 13 }}><strong>Action:</strong> {step.action || "Not recorded"}</Typography><Typography sx={{ mt: .8, fontSize: 14 }}>{step.assessment}</Typography><Typography color="text.secondary" sx={{ mt: .7, fontSize: 13 }}><strong>Observed:</strong> {step.observed_ui || "Not recorded"}</Typography><Typography color="text.secondary" sx={{ mt: .7, fontSize: 13 }}><strong>Effect:</strong> {step.effect || "Not recorded"}</Typography></>}{episodes.map(episode => <Box key={episode.episode_id} sx={{ mt: 1.3, p: 1.3, bgcolor: "action.hover", borderRadius: 2 }}><Box sx={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr)", alignItems: "start", gap: 1 }}><Chip size="small" color="warning" variant="outlined" label={`P${episode.problem_number || (review.episodes || []).indexOf(episode) + 1}`} /><Typography sx={{ fontSize: 13, fontWeight: 650, lineHeight: 1.45, overflowWrap: "anywhere" }}>{episode.label_name}</Typography></Box><Typography sx={{ fontSize: 13, mt: .7 }}>First observed: step {episode.first_observed_step_id || episode.onset_step_ids?.join(", ")}. Recovery: {episode.recovery?.status?.replaceAll("_", " ")} {episode.recovery?.step_ids?.length ? `(steps ${episode.recovery.step_ids.join(", ")})` : ""}.</Typography><Typography sx={{ fontSize: 13, mt: .7 }}>{episode.mechanism}</Typography>{episode.uncertainty && <Typography color="text.secondary" sx={{ fontSize: 13, mt: .5 }}>{episode.uncertainty}</Typography>}</Box>)}</Box></Grid>; })}</Grid></Panel>)}</Stack>
    </>}
  </>;
}
