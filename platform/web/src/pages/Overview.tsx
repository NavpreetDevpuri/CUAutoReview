import { Link as RouterLink } from "react-router-dom";
import { Box, Button, Chip, Grid, Stack, Typography } from "@mui/material";
import StorageRounded from "@mui/icons-material/StorageRounded";
import PlaylistPlayRounded from "@mui/icons-material/PlaylistPlayRounded";
import TaskAltRounded from "@mui/icons-material/TaskAltRounded";
import WorkspacesRounded from "@mui/icons-material/WorkspacesRounded";
import AddRounded from "@mui/icons-material/AddRounded";
import { PageHeader, Panel, MetricCard, LoadingState, ErrorState, SectionTitle, StatusTag, formatDate, displayValue, runStatusLabel } from "../components";
import { useApi } from "../hooks";

interface OverviewData {
  counts?: Record<string, number>;
  datasets?: number;
  runs?: number;
  batches?: number;
  tasks?: number;
  jobs?: number | Record<string, number>;
  recent_runs?: Record<string, unknown>[];
  recent_batches?: Record<string, unknown>[];
  activity?: Record<string, unknown>[];
  queue?: { mode?: string; connected?: boolean };
  provider?: { default_backend?: string };
  queue_mode?: string;
  provider_mode?: string;
  storage_mode?: string;
}
interface DatasetRows { items?: Record<string, unknown>[]; total?: number; }

export function OverviewPage() {
  const state = useApi<OverviewData>("/overview");
  const datasetsState = useApi<DatasetRows | Record<string, unknown>[]>("/datasets");
  const raw = state.data;
  const counts: Record<string, number | undefined> | undefined = raw ? {
    ...(raw.counts || {}),
    datasets: raw.counts?.datasets ?? raw.datasets,
    runs: raw.counts?.runs ?? raw.runs ?? raw.counts?.batches ?? raw.batches,
    tasks: raw.counts?.tasks ?? raw.tasks,
    jobs: raw.counts?.jobs ?? (typeof raw.jobs === "number" ? raw.jobs : raw.jobs && typeof raw.jobs === "object" ? Object.values(raw.jobs).reduce((sum, value) => sum + Number(value || 0), 0) : undefined),
  } : undefined;
  const datasetRows = Array.isArray(datasetsState.data) ? datasetsState.data : datasetsState.data?.items || [];
  const datasetNames = new Map(datasetRows.map(dataset => [String(dataset.id), String(dataset.name || "")]));
  const data = raw ? {
    ...raw,
    counts,
    queue: raw.queue || { mode: raw.queue_mode, connected: undefined },
    provider: raw.provider || {},
  } : null;
  return <>
    <PageHeader eyebrow="LOCAL REVIEW WORKSPACE" title="Overview" description="A clear view of source datasets, review runs, analytics, and the work that needs attention." action={<Stack direction="row" gap={1} flexWrap="wrap"><Button component={RouterLink} to="/runs" variant="contained" startIcon={<AddRounded />}>Create a run</Button><Button component={RouterLink} to="/analytics" variant="outlined">Open analytics</Button></Stack>} />
    {state.loading && <LoadingState label="Loading workspace overview…" />}
    {state.error && <ErrorState message={state.error} onRetry={state.reload} />}
    {data && <>
      <Grid container spacing={1.6} sx={{ mb: 3 }}>
        <Grid size={{ xs: 6, md: 3 }}><MetricCard label="Datasets" value={displayValue(data.counts?.datasets, "Not recorded")} icon={<StorageRounded />} tint="blue" /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><MetricCard label="Runs" value={displayValue(data.counts?.runs, "Not recorded")} icon={<PlaylistPlayRounded />} tint="violet" /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><MetricCard label="Tasks" value={displayValue(data.counts?.tasks, "Not recorded")} icon={<TaskAltRounded />} tint="green" /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><MetricCard label="Jobs" value={displayValue(data.counts?.jobs, "Not recorded")} icon={<WorkspacesRounded />} tint="amber" detail="Queued, active, or retained" /></Grid>
      </Grid>
      <Grid container spacing={2.2} alignItems="flex-start">
        <Grid size={{ xs: 12, lg: 7.5 }}>
          <Panel>
            <SectionTitle title="Recent runs" subtitle="Outcome and processing progress are shown separately." action={<Button component={RouterLink} to="/runs" size="small">All runs</Button>} />
            {!(data.recent_runs || data.recent_batches)?.length ? <Typography color="text.secondary" sx={{ py: 3 }}>No runs yet. Create a dataset, import tasks, then select the work and workflow for a new run.</Typography> : <Stack divider={<Box sx={{ borderBottom: "1px solid", borderColor: "divider" }} />}>
              {(data.recent_runs || data.recent_batches || []).map((run, i) => {
                const id = String(run.id || run.run_id || run.batch_id || "");
                const progress = (run.progress || {}) as Record<string, unknown>;
                return <Stack key={id || i} component={RouterLink} to={`/runs/${encodeURIComponent(id)}`} direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} gap={1.3} sx={{ p: 1.5, mx: -1.5, borderRadius: 1.5, textDecoration: "none", color: "text.primary", minWidth: 0, "&:hover": { bgcolor: "action.hover" }, "&:focus-visible": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 } }}>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography sx={{ fontSize: 14, fontWeight: 700, overflowWrap: "anywhere" }}>{displayValue(run.name, "Unnamed run")}</Typography>
                    <Typography color="text.secondary" sx={{ mt: .25, fontSize: 13 }}>{displayValue(run.dataset_name || datasetNames.get(String(run.dataset_id || "")), "Multiple datasets or dataset not recorded")} · {formatDate(run.created_at)}</Typography>
                  </Box>
                  <Stack direction="row" gap={.7} flexWrap="wrap"><StatusTag value={runStatusLabel(run)} /><Chip size="small" label={`${displayValue(progress.completed, "Not recorded")} / ${displayValue(progress.total, "Not recorded")} processed`} variant="outlined" /></Stack>
                </Stack>;
              })}
            </Stack>}
          </Panel>
        </Grid>
        <Grid size={{ xs: 12, lg: 4.5 }}>
          <Stack gap={2.2}>
            <Panel>
              <SectionTitle title="Runtime" subtitle="Current local execution settings." />
              <Stack gap={1.2}>
                <Stack direction="row" justifyContent="space-between" gap={2}><Typography color="text.secondary">Queue</Typography><Typography sx={{ fontWeight: 700 }}>{displayValue(data.queue?.mode, "Not reported")}</Typography></Stack>
                <Stack direction="row" justifyContent="space-between" gap={2}><Typography color="text.secondary">Queue connection</Typography><StatusTag value={data.queue?.connected ? "connected" : data.queue?.connected === false ? "offline" : "not reported"} /></Stack>
                <Stack direction="row" justifyContent="space-between" gap={2}><Typography color="text.secondary">Default backend</Typography><StatusTag value={data.provider?.default_backend || "Not reported"} /></Stack>
              </Stack>
            </Panel>
            <Panel>
              <SectionTitle title="Recent activity" action={<Button component={RouterLink} to="/activity" size="small">View all</Button>} />
              {!data.activity?.length ? <Typography color="text.secondary">No activity recorded yet.</Typography> : <Stack gap={1.5}>
                {data.activity.slice(0, 5).map((entry, index) => <Box key={String(entry.id || index)} sx={{ display: "grid", gridTemplateColumns: "10px 1fr", gap: 1.1 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: "primary.main", mt: .8 }} />
                  <Box><Typography sx={{ fontSize: 14, fontWeight: 650 }}>{displayValue(entry.summary || entry.action || entry.kind)}</Typography><Typography color="text.secondary" sx={{ mt: .2, fontSize: 12.5 }}>{displayValue(entry.actor_name || entry.actor_email, "Workspace event")} · {formatDate(entry.created_at)}</Typography></Box>
                </Box>)}
              </Stack>}
            </Panel>
          </Stack>
        </Grid>
      </Grid>
    </>}
  </>;
}
