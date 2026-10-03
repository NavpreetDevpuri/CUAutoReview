import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  InputAdornment,
  Link,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import SearchRounded from "@mui/icons-material/SearchRounded";
import OpenInNewRounded from "@mui/icons-material/OpenInNewRounded";
import { Panel } from "./Page";
import { ErrorState, LoadingState } from "./States";
import { StatusTag } from "./StatusTag";
import { useApi } from "../hooks/useApi";
import { countLabel } from "../lib/format";

export interface Selection {
  datasetIds: string[];
  runIds: string[];
  taskDefinitionIds: string[];
}
export interface CatalogItem {
  id: string;
  name?: string;
  title?: string;
  dataset_id?: string;
  dataset_ids?: string[];
  task_id?: string;
  task_definition_id?: string;
  task_count?: number;
  run_count?: number;
  step_count?: number;
  problem_count?: number | null;
  outcome?: string;
  status?: string;
  partial_access?: boolean;
}
export interface Catalog {
  datasets: CatalogItem[];
  runs: CatalogItem[];
  tasks: CatalogItem[];
}
export const emptySelection = (): Selection => ({ datasetIds: [], runIds: [], taskDefinitionIds: [] });
export const definitionId = (task: CatalogItem) => task.task_definition_id || task.id;
export function selectionSummary(value: Selection): string {
  const parts = [
    value.datasetIds.length && countLabel(value.datasetIds.length, "dataset"),
    value.runIds.length && countLabel(value.runIds.length, "run"),
    value.taskDefinitionIds.length && countLabel(value.taskDefinitionIds.length, "task"),
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "All accessible data";
}

export function SelectionDialog({
  open,
  onClose,
  value,
  onApply,
  mode = "analytics",
}: {
  open: boolean;
  onClose: () => void;
  value: Selection;
  onApply: (value: Selection) => void;
  mode?: "analytics" | "scope";
}) {
  const catalog = useApi<Catalog>(open ? "/catalog" : null);
  const [draft, setDraft] = useState<Selection>(value);
  const [tab, setTab] = useState("datasets");
  const [query, setQuery] = useState("");
  useEffect(() => {
    if (open) {
      setDraft(value);
      setQuery("");
      setTab("datasets");
    }
  }, [open]);
  const data = catalog.data || { datasets: [], runs: [], tasks: [] };
  const scope = mode === "scope";
  const datasetNames = new Map(data.datasets.map(item => [item.id, item.name]));
  const effectiveTaskIds = useMemo(
    () =>
      new Set(
        draft.taskDefinitionIds.length
          ? draft.taskDefinitionIds
          : scope
            ? data.tasks.filter(task => draft.datasetIds.includes(task.dataset_id || "")).map(definitionId)
            : [],
      ),
    [draft, scope, data.tasks],
  );
  const effectiveDatasetIds = useMemo(
    () => [
      ...new Set(
        data.tasks
          .filter(task => effectiveTaskIds.has(definitionId(task)))
          .map(task => task.dataset_id)
          .filter((id): id is string => Boolean(id)),
      ),
    ],
    [data.tasks, effectiveTaskIds],
  );
  const scopeSummary = `${countLabel(effectiveTaskIds.size, "task")} selected${effectiveDatasetIds.length || !effectiveTaskIds.size ? ` across ${countLabel(effectiveDatasetIds.length, "dataset")}` : ""}`;
  const matching = useMemo(() => {
    let items = tab === "datasets" ? data.datasets : tab === "runs" ? data.runs : data.tasks;
    if (!scope && tab === "tasks" && draft.datasetIds.length)
      items = items.filter(item => draft.datasetIds.includes(item.dataset_id || ""));
    const q = query.trim().toLowerCase();
    return items.filter(
      item =>
        !q ||
        [item.name, item.title, item.task_id, datasetNames.get(item.dataset_id || "")].some(text =>
          String(text || "")
            .toLowerCase()
            .includes(q),
        ),
    );
  }, [tab, data, query, draft.datasetIds]);
  const checked = (item: CatalogItem) => {
    if (scope && tab === "datasets") {
      const ids = data.tasks.filter(task => task.dataset_id === item.id).map(definitionId);
      return ids.length > 0 && ids.every(id => effectiveTaskIds.has(id));
    }
    return tab === "tasks"
      ? scope
        ? effectiveTaskIds.has(definitionId(item))
        : draft.taskDefinitionIds.includes(definitionId(item))
      : (tab === "runs" ? draft.runIds : draft.datasetIds).includes(item.id);
  };
  const applyItems = (items: CatalogItem[], add: boolean) => {
    if (scope) {
      const ids = new Set(effectiveTaskIds);
      const affected =
        tab === "datasets"
          ? data.tasks.filter(task => items.some(item => item.id === task.dataset_id)).map(definitionId)
          : items.map(definitionId);
      affected.forEach(id => (add ? ids.add(id) : ids.delete(id)));
      const datasetIds = [
        ...new Set(
          data.tasks
            .filter(task => ids.has(definitionId(task)))
            .map(task => task.dataset_id || "")
            .filter(Boolean),
        ),
      ];
      setDraft({ datasetIds, runIds: [], taskDefinitionIds: [...ids] });
    } else {
      const field = tab === "datasets" ? "datasetIds" : tab === "runs" ? "runIds" : "taskDefinitionIds";
      const ids = new Set(draft[field]);
      items.forEach(item =>
        add
          ? ids.add(tab === "tasks" ? definitionId(item) : item.id)
          : ids.delete(tab === "tasks" ? definitionId(item) : item.id),
      );
      setDraft({ ...draft, [field]: [...ids] });
    }
  };
  return (
    <Dialog open={open} onClose={onClose} fullScreen>
      <DialogTitle>
        <Stack direction="row" alignItems="center" justifyContent="space-between" gap={2}>
          <Box>
            {scope ? "Choose tasks to analyze" : "Filter analytics"}
            <Typography color="text.secondary" sx={{ fontSize: 14, mt: 0.5 }}>
              {scope ? scopeSummary : selectionSummary(draft)}
            </Typography>
          </Box>
          <Button onClick={onClose}>Cancel</Button>
        </Stack>
      </DialogTitle>
      <DialogContent dividers sx={{ bgcolor: "background.default" }}>
        <Alert severity="info" sx={{ mb: 2 }}>
          {scope
            ? "Select whole datasets or individual tasks. You will choose the workflow and model before anything runs."
            : "Selections within one group are combined. Different groups narrow each other. An empty group includes all accessible records in that group."}
        </Alert>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          gap={2}
          justifyContent="space-between"
          alignItems={{ sm: "center" }}
        >
          <Tabs
            value={tab}
            onChange={(_, next) => setTab(next)}
            variant="scrollable"
            scrollButtons="auto"
            allowScrollButtonsMobile
            sx={{ minWidth: 0, maxWidth: "100%" }}
          >
            <Tab label={`Datasets (${data.datasets.length})`} value="datasets" />
            {!scope && <Tab label={`Runs (${data.runs.length})`} value="runs" />}
            <Tab label={`Tasks (${data.tasks.length})`} value="tasks" />
          </Tabs>
          <TextField
            label="Search name or task ID"
            value={query}
            onChange={event => setQuery(event.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRounded />
                </InputAdornment>
              ),
            }}
          />
        </Stack>
        <Stack direction="row" gap={1} sx={{ my: 2 }} flexWrap="wrap">
          <Button onClick={() => applyItems(matching, true)}>Select all shown ({matching.length})</Button>
          <Button onClick={() => applyItems(matching, false)}>Unselect shown</Button>
          <Button color="inherit" onClick={() => setDraft(emptySelection())}>
            {scope ? "Clear selection" : "Clear all filters"}
          </Button>
        </Stack>
        {catalog.loading && <LoadingState label="Loading accessible datasets, runs and tasks…" />}
        {catalog.error && <ErrorState message={catalog.error} onRetry={catalog.reload} />}
        {!catalog.loading && !matching.length && (
          <Typography color="text.secondary">No records match this search.</Typography>
        )}
        <Grid container spacing={1.6}>
          {matching.map(item => {
            const selected = checked(item);
            const selectedCount =
              scope && tab === "datasets"
                ? data.tasks.filter(task => task.dataset_id === item.id && effectiveTaskIds.has(definitionId(task)))
                    .length
                : 0;
            const href =
              tab === "datasets"
                ? `#/datasets/${item.id}`
                : tab === "runs"
                  ? `#/runs/${item.id}`
                  : `#/datasets/${item.dataset_id}/tasks/${definitionId(item)}`;
            return (
              <Grid key={item.id} size={{ xs: 12, md: 6, xl: 4 }}>
                <Panel
                  sx={{
                    position: "relative",
                    minWidth: 0,
                    height: "100%",
                    borderColor: selected ? "primary.main" : "divider",
                    bgcolor: selected ? "action.selected" : "background.paper",
                    p: 1.5,
                    "&:hover": { borderColor: "primary.main" },
                    "&:has(:focus-visible)": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 },
                  }}
                >
                  <Stack direction="row" gap={1} alignItems="flex-start">
                    <Checkbox
                      checked={selected}
                      indeterminate={scope && tab === "datasets" && selectedCount > 0 && !selected}
                      onChange={(_, add) => applyItems([item], add)}
                      inputProps={{ "aria-label": `Select ${item.name || item.title || item.task_id}` }}
                      sx={{ p: 0.4, position: "relative", zIndex: 2 }}
                    />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography
                        component="button"
                        type="button"
                        aria-pressed={selected}
                        onClick={() => applyItems([item], !selected)}
                        sx={{
                          "&::after": { content: '""', position: "absolute", inset: 0, zIndex: 1, borderRadius: 2 },
                          "&:focus-visible": { outline: "none" },
                          appearance: "none",
                          border: 0,
                          p: 0,
                          bgcolor: "transparent",
                          color: "text.primary",
                          textAlign: "left",
                          cursor: "pointer",
                          font: "inherit",
                          fontSize: 14,
                          lineHeight: 1.4,
                          fontWeight: 700,
                          overflowWrap: "anywhere",
                        }}
                      >
                        {item.name || item.title || item.task_id}
                      </Typography>
                      <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: 13 }}>
                        {tab === "tasks"
                          ? datasetNames.get(item.dataset_id || "")
                          : item.dataset_ids
                              ?.map(id => datasetNames.get(id))
                              .filter(Boolean)
                              .join(", ")}
                      </Typography>
                    </Box>
                    <Link
                      href={href}
                      target="_blank"
                      rel="noopener"
                      sx={{
                        position: "relative",
                        zIndex: 2,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                        width: 32,
                        height: 32,
                        borderRadius: 1,
                        "&:hover": { bgcolor: "action.hover" },
                      }}
                      aria-label={`Open ${item.name || item.title || item.task_id} in new tab`}
                    >
                      <OpenInNewRounded fontSize="small" />
                    </Link>
                  </Stack>
                  <Stack direction="row" gap={0.8} flexWrap="wrap" sx={{ mt: 1.5 }}>
                    {item.partial_access && <Chip size="small" label="Access through run" />}
                    {item.task_count !== undefined && (
                      <Chip
                        size="small"
                        label={
                          scope && tab === "datasets"
                            ? `${selectedCount}/${item.task_count} tasks selected`
                            : `${item.task_count} tasks`
                        }
                      />
                    )}
                    {item.run_count !== undefined && <Chip size="small" label={`${item.run_count} runs`} />}
                    {item.step_count !== undefined && <Chip size="small" label={`${item.step_count} steps`} />}
                    <Chip
                      size="small"
                      variant="outlined"
                      label={
                        item.problem_count == null ? "Issues not recorded" : `${item.problem_count} recorded problems`
                      }
                    />
                    {(item.outcome || item.status) && <StatusTag value={item.outcome || item.status} />}
                  </Stack>
                </Panel>
              </Grid>
            );
          })}
        </Grid>
      </DialogContent>
      <DialogActions sx={{ p: 2, gap: 1, flexWrap: "wrap" }}>
        <Typography sx={{ mr: "auto", color: "text.secondary", fontSize: 13, flexBasis: { xs: "100%", sm: "auto" } }}>
          {scope ? `${countLabel(effectiveTaskIds.size, "task")} selected` : selectionSummary(draft)}
        </Typography>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={catalog.loading || !!catalog.error || (scope && !effectiveTaskIds.size)}
          onClick={() => {
            onApply(
              scope ? { ...draft, datasetIds: effectiveDatasetIds, taskDefinitionIds: [...effectiveTaskIds] } : draft,
            );
            onClose();
          }}
        >
          {scope ? "Use selected tasks" : "Apply filters"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
