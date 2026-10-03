import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Grid,
  LinearProgress,
  Link,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import FilterAltRounded from "@mui/icons-material/FilterAltRounded";
import CompareArrowsRounded from "@mui/icons-material/CompareArrowsRounded";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";
import { MetricCard } from "../components/MetricCard";
import { PageHeader, Panel, SectionTitle } from "../components/Page";
import {
  type Catalog,
  emptySelection,
  type Selection,
  SelectionDialog,
  selectionSummary,
} from "../components/SelectionDialog";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { StatusTag } from "../components/StatusTag";
import { useApi } from "../hooks/useApi";
import { usePostQuery } from "../hooks/usePostQuery";

export interface AnalyticsRow {
  run_id: string | null;
  run_name: string | null;
  dataset_id: string;
  task_definition_id: string;
  task_id: string;
  task_title?: string;
  task_revision_id: string;
  task_revision: number;
  member_id: string | null;
  review_result_id: string | null;
  status: string;
  outcome: string;
  review_kind: string | null;
  problem_count: number;
  labels: { id: string; name: string }[];
  recovery_step_count: number;
  missing_evidence_count: number;
  known_cost_usd: number;
  unknown_cost_jobs: number;
  unknown_cost_attempts: number;
  backend?: string;
  model?: string;
}
interface Analytics {
  counts: {
    task_definitions: number;
    rows: number;
    run_members: number;
    problem_episodes: number;
    recovery_steps: number;
    missing_evidence: number;
    absent_frame_steps?: number;
    missing_artifact_records?: number;
    broken_source_files?: number;
    cost_usd: number | null;
    known_cost_usd: number;
    unknown_cost_jobs: number;
    unknown_cost_attempts: number;
    statuses: Record<string, number>;
    outcomes: Record<string, number>;
  };
  labels: { id: string; name: string; count: number }[];
  rows: AnalyticsRow[];
}
export function AnalyticsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const selection: Selection = useMemo(
    () => ({
      datasetIds: params.getAll("dataset"),
      runIds: params.getAll("run"),
      taskDefinitionIds: params.getAll("task"),
    }),
    [params],
  );
  const [filterOpen, setFilterOpen] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const catalog = useApi<Catalog>("/catalog");
  const names = new Map(
    catalog.data?.tasks.map(task => [task.task_definition_id || task.id, task.title || task.task_id]) || [],
  );
  const query = usePostQuery<Analytics>(
    "/analytics/query",
    {
      dataset_ids: selection.datasetIds,
      run_ids: selection.runIds,
      task_definition_ids: selection.taskDefinitionIds,
    },
    nonce,
    "Analytics could not load.",
  );
  const { data, loading, error } = query;
  // Review selections belong to one result set; a new filter or refresh clears them.
  const resultKey = `${JSON.stringify(selection)}:${nonce}`;
  const [selectedFor, setSelectedFor] = useState(resultKey);
  if (selectedFor !== resultKey) {
    setSelectedFor(resultKey);
    setSelected([]);
  }
  const apply = (value: Selection) => {
    const next = new URLSearchParams();
    value.datasetIds.forEach(id => next.append("dataset", id));
    value.runIds.forEach(id => next.append("run", id));
    value.taskDefinitionIds.forEach(id => next.append("task", id));
    setParams(next);
  };
  const first = data?.rows.find(row => selected.includes(row.review_result_id || ""));
  const canSelect = (row: AnalyticsRow) =>
    !!row.review_result_id &&
    (!first ||
      (row.task_definition_id === first.task_definition_id && row.task_revision_id === first.task_revision_id)) &&
    (selected.length < 2 || selected.includes(row.review_result_id));
  const c = data?.counts;
  const recordedReviews = data?.rows.filter(row => row.review_result_id).length || 0;
  const labels = [...(data?.labels || [])].sort((a, b) => b.count - a.count);
  const filterNames = [
    ...selection.datasetIds.map(id => catalog.data?.datasets.find(item => item.id === id)?.name || id),
    ...selection.runIds.map(id => catalog.data?.runs.find(item => item.id === id)?.name || id),
    ...selection.taskDefinitionIds.map(id => names.get(id) || id),
  ];
  return (
    <>
      <PageHeader
        eyebrow="WORKSPACE INSIGHTS"
        title="Analytics"
        description="Explore recorded problems, recovery and coverage. Compare reviews of the same source revision to inspect disagreements."
        action={
          <Button
            sx={{ width: { xs: "100%", sm: "auto" } }}
            variant="contained"
            startIcon={<FilterAltRounded />}
            onClick={() => setFilterOpen(true)}
          >
            Edit filters
          </Button>
        }
      />
      <Panel sx={{ mb: 2, p: 2 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          gap={1.5}
          justifyContent="space-between"
          alignItems={{ sm: "center" }}
        >
          <Box>
            <Typography fontWeight={750}>{selectionSummary(selection)}</Typography>
            <Stack direction="row" gap={0.7} flexWrap="wrap" sx={{ mt: 0.7 }}>
              {filterNames.slice(0, 5).map((name, i) => (
                <Chip key={i} size="small" label={name} sx={{ maxWidth: 260 }} />
              ))}
              {filterNames.length > 5 && <Chip size="small" label={`+${filterNames.length - 5} more`} />}
              {!filterNames.length && (
                <Typography color="text.secondary" sx={{ fontSize: 13 }}>
                  Archived records are excluded. Every filter is saved in this page's URL.
                </Typography>
              )}
            </Stack>
          </Box>
          <Stack direction="row" gap={1}>
            <Button onClick={() => apply(emptySelection())} disabled={!filterNames.length}>
              Clear
            </Button>
            <Button startIcon={<RefreshRounded />} onClick={() => setNonce(n => n + 1)}>
              Refresh
            </Button>
          </Stack>
        </Stack>
      </Panel>
      {loading && <LoadingState label="Calculating analytics for your selection…" />}
      {error && <ErrorState message={error} onRetry={() => setNonce(n => n + 1)} />}
      {!loading && !error && c && (
        <>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            <Grid size={{ xs: 6, lg: 3 }}>
              <MetricCard
                label="Unique tasks"
                value={c.task_definitions}
                detail={`${c.run_members} task appearances in runs`}
              />
            </Grid>
            <Grid size={{ xs: 6, lg: 3 }}>
              <MetricCard
                label="Recorded reviews"
                value={recordedReviews}
                detail={`${c.rows - recordedReviews} rows without a completed review`}
                tint="green"
              />
            </Grid>
            <Grid size={{ xs: 6, lg: 3 }}>
              <MetricCard
                label="Problem episodes"
                value={c.problem_episodes}
                detail="Across recorded reviews, including repeat analyses"
                tint="amber"
              />
            </Grid>
            <Grid size={{ xs: 6, lg: 3 }}>
              <MetricCard
                label="Estimated usage cost"
                value={c.cost_usd === null ? "Partly unknown" : `$${c.known_cost_usd.toFixed(4)}`}
                detail={
                  c.unknown_cost_jobs
                    ? `$${c.known_cost_usd.toFixed(4)} known · ${c.unknown_cost_jobs} jobs across ${c.unknown_cost_attempts} attempts with unreported cost`
                    : "Derived from recorded usage; not an invoice"
                }
                tint="violet"
              />
            </Grid>
          </Grid>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid size={{ xs: 12, md: 7 }}>
              <Panel sx={{ height: "100%" }}>
                <SectionTitle
                  title="Reported failure labels"
                  subtitle="Frequency counts problem episodes across reviews. Similar names may still be unapproved taxonomy proposals."
                />
                {labels.length ? (
                  <Stack gap={1.5}>
                    {labels.map(label => (
                      <Box key={`${label.id}-${label.name}`}>
                        <Stack direction="row" justifyContent="space-between" gap={1}>
                          <Typography fontWeight={650} sx={{ fontSize: 14 }}>
                            {label.name}
                          </Typography>
                          <Chip size="small" label={label.count} />
                        </Stack>
                        <LinearProgress
                          variant="determinate"
                          value={(100 * label.count) / Math.max(1, c.problem_episodes)}
                          sx={{ mt: 0.7, height: 6, borderRadius: 3 }}
                        />
                      </Box>
                    ))}
                  </Stack>
                ) : (
                  <Typography color="text.secondary">
                    No problem episodes have been recorded for this selection.
                  </Typography>
                )}
              </Panel>
            </Grid>
            <Grid size={{ xs: 12, md: 5 }}>
              <Panel sx={{ height: "100%" }}>
                <SectionTitle title="Coverage and execution" />
                <Stack gap={1.5}>
                  <Box>
                    <Typography fontWeight={650}>Run task status</Typography>
                    <Stack direction="row" flexWrap="wrap" gap={0.8} sx={{ mt: 0.7 }}>
                      {Object.entries(c.statuses).map(([status, count]) => (
                        <Chip key={status} label={`${status.replaceAll("_", " ")}: ${count}`} />
                      ))}
                    </Stack>
                  </Box>
                  <Box>
                    <Typography fontWeight={650}>Recorded source outcome</Typography>
                    <Stack direction="row" flexWrap="wrap" gap={0.8} sx={{ mt: 0.7 }}>
                      {Object.entries(c.outcomes).map(([outcome, count]) => (
                        <Chip key={outcome} variant="outlined" label={`${outcome}: ${count}`} />
                      ))}
                    </Stack>
                  </Box>
                  <Typography color="text.secondary" sx={{ fontSize: 14 }}>
                    {c.recovery_steps} recovery step references · {c.absent_frame_steps ?? c.missing_evidence} steps
                    without a source screenshot · {(c.missing_artifact_records || 0) + (c.broken_source_files || 0)}{" "}
                    unavailable screenshot files
                  </Typography>
                  <Typography color="text.secondary" sx={{ fontSize: 13 }}>
                    Source outcome belongs to the original computer-use task. Review completion means the analysis
                    finished, not that the task passed.
                  </Typography>
                </Stack>
              </Panel>
            </Grid>
          </Grid>
          <Panel>
            <SectionTitle
              title="Tasks and reviews"
              subtitle="Select two reviews of the same task and source revision to compare. Open a task to see its complete review history."
              action={
                <Button
                  sx={{ width: { xs: "100%", sm: "auto" } }}
                  variant="outlined"
                  startIcon={<CompareArrowsRounded />}
                  disabled={selected.length !== 2}
                  onClick={() => navigate(`/compare?left=${selected[0]}&right=${selected[1]}`)}
                >
                  Compare {selected.length ? `(${selected.length}/2)` : "reviews"}
                </Button>
              }
            />
            {!!selected.length && (
              <Alert
                severity="info"
                sx={{ mb: 1.5 }}
                action={
                  <Button color="inherit" onClick={() => setSelected([])}>
                    Clear
                  </Button>
                }
              >
                Choose another review of this same task and revision. Other tasks are temporarily unavailable for
                comparison.
              </Alert>
            )}
            {!data?.rows.length ? (
              <EmptyState title="No matching records" description="Broaden the filter or add tasks to a dataset." />
            ) : (
              <Box sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Select</TableCell>
                      <TableCell>Task</TableCell>
                      <TableCell>Run / review</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Problems</TableCell>
                      <TableCell>Labels</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.rows.map((row, index) => (
                      <TableRow key={row.member_id || `${row.task_definition_id}-${index}`} hover>
                        <TableCell>
                          <Checkbox
                            size="small"
                            checked={selected.includes(row.review_result_id || "")}
                            disabled={!canSelect(row)}
                            onChange={(_, checked) =>
                              setSelected(old =>
                                checked
                                  ? [...old, row.review_result_id!]
                                  : old.filter(id => id !== row.review_result_id),
                              )
                            }
                            inputProps={{ "aria-label": `Compare ${row.run_name || "unreviewed task"} ${row.task_id}` }}
                          />
                        </TableCell>
                        <TableCell sx={{ minWidth: 220, maxWidth: 340 }}>
                          <Link
                            component={RouterLink}
                            to={
                              names.has(row.task_definition_id) || !row.run_id
                                ? `/datasets/${row.dataset_id}/tasks/${row.task_definition_id}`
                                : `/runs/${row.run_id}/tasks/${encodeURIComponent(row.task_id)}?member_id=${row.member_id}`
                            }
                            fontWeight={700}
                          >
                            {names.get(row.task_definition_id) || row.task_title || row.task_id}
                          </Link>
                          <Typography color="text.secondary" sx={{ fontSize: 12, mt: 0.5 }}>
                            Source revision {row.task_revision} · {row.outcome}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ minWidth: 190 }}>
                          {row.run_id ? (
                            <>
                              <Link component={RouterLink} to={`/runs/${row.run_id}`}>
                                {row.run_name}
                              </Link>
                              {row.review_result_id && (
                                <Box>
                                  <Link
                                    component={RouterLink}
                                    to={`/runs/${row.run_id}/tasks/${encodeURIComponent(row.task_id)}?member_id=${row.member_id}`}
                                    sx={{ fontSize: 13 }}
                                  >
                                    Open review
                                  </Link>
                                </Box>
                              )}
                            </>
                          ) : (
                            "Not run"
                          )}
                        </TableCell>
                        <TableCell>
                          <StatusTag value={row.status} />
                        </TableCell>
                        <TableCell>{row.review_result_id ? row.problem_count : "Not reviewed"}</TableCell>
                        <TableCell sx={{ minWidth: 200, maxWidth: 350 }}>
                          <Stack direction="row" gap={0.6} flexWrap="wrap">
                            {[...new Map(row.labels.map(label => [label.id, label])).values()].map(label => (
                              <Chip
                                size="small"
                                key={label.id}
                                label={label.name}
                                color="warning"
                                variant="outlined"
                                sx={{ height: "auto", "& .MuiChip-label": { whiteSpace: "normal", py: 0.4 } }}
                              />
                            ))}
                          </Stack>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
          </Panel>
        </>
      )}
      <SelectionDialog open={filterOpen} onClose={() => setFilterOpen(false)} value={selection} onApply={apply} />
    </>
  );
}
