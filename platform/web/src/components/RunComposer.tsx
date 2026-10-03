import { useEffect, useMemo, useState } from "react";
import { Alert, Autocomplete, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControl, FormControlLabel, Grid, InputLabel, MenuItem, Select, Stack, TextField, Typography, useMediaQuery, useTheme } from "@mui/material";
import PlayArrowRounded from "@mui/icons-material/PlayArrowRounded";
import TuneRounded from "@mui/icons-material/TuneRounded";
import { apiRequest } from "../api/client";
import { CATALOG_PAGING } from "../api/pagination";
import { type ModelCatalog, ModelPicker, preferredModel, suggestedBudget } from "./ModelPicker";
import { Panel } from "./Page";
import { type Catalog, emptySelection, type Selection, SelectionDialog } from "./SelectionDialog";
import { ErrorState, LoadingState } from "./States";
import { useApi } from "../hooks/useApi";
import { countLabel } from "../lib/format";

interface Workflow { id: string; revision_id: string; name: string; description: string; stages: { id: string; name: string; kind: string; prompt: string }[] }
interface Provider { id: string; name: string; configured?: boolean; supported?: boolean; available?: boolean; description?: string; suggested_models?: string[] }
interface Person { id: string; name: string; email?: string }
interface Run { id: string; name: string; status: string; dataset_ids?: string[]; member_count?: number; progress?: { total: number }; counts?: Record<string, number>; configuration?: { workflow_revision_id?: string; execution_snapshot?: Execution } }
interface SavedExecution extends Partial<Execution> { id: string; name: string; latest_revision?: Partial<Execution> }
interface Execution { backend: string; model: string; reasoning: string; budget_usd: number; configuration?: Record<string, unknown> }
const MAX_REVIEW_ATTEMPTS = 4;

export function RunComposer({ open, onClose, initialDatasetIds = [], initialTaskDefinitionIds = [], sourceRunId, onCreated }: { open: boolean; onClose: () => void; initialDatasetIds?: string[]; initialTaskDefinitionIds?: string[]; sourceRunId?: string; onCreated?: (id: string) => void }) {
  const compact = useMediaQuery(useTheme().breakpoints.down("sm"));
  const catalog = useApi<Catalog>(open ? "/catalog" : null);
  const workflows = useApi<{ items: Workflow[] }>(open ? "/workflows" : null);
  const providers = useApi<{ backends: Provider[] }>(open ? "/providers" : null);
  const savedPresets = useApi<{ items: SavedExecution[] }>(open ? "/presets" : null, 0, CATALOG_PAGING);
  const [savedPresetId, setSavedPresetId] = useState("");
  const source = useApi<Run>(open && sourceRunId ? `/runs/${sourceRunId}` : null);
  const [personSearch, setPersonSearch] = useState("");
  const directory = useApi<{ users: Person[]; teams: Person[] }>(open ? `/directory?q=${encodeURIComponent(personSearch)}` : null);
  const [selection, setSelection] = useState<Selection>(emptySelection());
  const [selectOpen, setSelectOpen] = useState(false);
  const [name, setName] = useState("");
  const [workflow, setWorkflow] = useState("trajectory_review@1");
  const [backend, setBackend] = useState("");
  const [model, setModel] = useState("");
  const modelCatalog = useApi<ModelCatalog>(open && backend && backend !== "saved_replay" ? `/providers/models?backend=${encodeURIComponent(backend)}` : null);
  const [reasoning, setReasoning] = useState("low");
  const [budget, setBudget] = useState("0.10");
  const [maxImages, setMaxImages] = useState(32);
  const [executionConfiguration, setExecutionConfiguration] = useState<Record<string, unknown>>({});
  const [teams, setTeams] = useState<Person[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preparedId, setPreparedId] = useState<string | null>(null);
  useEffect(() => { if (!open) return; setSelection({ datasetIds: initialDatasetIds, taskDefinitionIds: initialTaskDefinitionIds, runIds: [] }); setName(`Review ${new Date().toLocaleDateString()}`); setBackend(""); setModel(""); setBudget("0.10"); setAccepted(false); setError(""); setPreparedId(null); setSavedPresetId(""); setTeams([]); setPeople([]); setMaxImages(32); setExecutionConfiguration({}); }, [open, sourceRunId]);
  useEffect(() => { if (!source.data) return; const run = source.data; const execution = run.configuration?.execution_snapshot; setName(run.status === "draft" ? run.name : `${run.name} · new review`); setWorkflow(run.configuration?.workflow_revision_id || "trajectory_review@1"); if (execution) { setBackend(execution.backend); setModel(execution.model || ""); setReasoning(execution.reasoning || "low"); setBudget(String(execution.budget_usd ?? .1)); setMaxImages(Number(execution.configuration?.max_images ?? 32)); setExecutionConfiguration(execution.configuration || {}); } }, [source.data]);
  const selectedTasks = useMemo(() => (catalog.data?.tasks || []).filter(task => selection.taskDefinitionIds.length ? selection.taskDefinitionIds.includes(task.task_definition_id || task.id) : selection.datasetIds.includes(task.dataset_id || "")), [selection, catalog.data]);
  const sourceTaskCount = source.data ? (source.data.progress?.total ?? source.data.member_count ?? Object.values(source.data.counts || {}).reduce((a, b) => a + b, 0)) : 0;
  const taskCount = sourceRunId ? sourceTaskCount : selectedTasks.length;
  const chosenProvider = providers.data?.backends.find(item => item.id === backend);
  const availableModels = modelCatalog.data?.backend === backend ? modelCatalog.data.models : [];
  const selectedModel = availableModels.find(item => item.id === model);
  useEffect(() => {
    if (!open || model || sourceRunId || modelCatalog.loading || modelCatalog.data?.backend !== backend) return;
    const next = preferredModel(availableModels, backend);
    if (next) { setModel(next.id); setBudget(suggestedBudget(next).toFixed(2)); }
  }, [open, backend, model, modelCatalog.data, modelCatalog.loading, sourceRunId]);
  const chosenWorkflow = workflows.data?.items.find(item => item.revision_id === workflow);
  const replay = backend === "saved_replay";
  const available = !!chosenProvider && chosenProvider.configured !== false && chosenProvider.supported !== false;
  const live = !!backend && !replay;
  const validBudget = replay || (Number(budget) > 0 && Number(budget) <= .5);
  const plannedRetryAllowance = Number(budget || 0) * taskCount * MAX_REVIEW_ATTEMPTS;
  const draft = source.data?.status === "draft";
  const canSubmit = !!name.trim() && (!!sourceRunId || taskCount > 0) && available && !!workflow && (replay || (!!selectedModel && !modelCatalog.loading && !modelCatalog.error)) && validBudget && accepted && !busy && !source.loading;
  const chooseSavedPreset = (id: string) => {
    setSavedPresetId(id); setAccepted(false);
    const preset = savedPresets.data?.items.find(item => item.id === id);
    if (!preset) return;
    const execution = preset.latest_revision || preset;
    setBackend(execution.backend || ""); setModel(execution.model || "");
    setReasoning(execution.reasoning || "low");
    setBudget(String(execution.budget_usd && execution.budget_usd > 0 ? execution.budget_usd : .1));
    setMaxImages(Number(execution.configuration?.max_images ?? 32)); setExecutionConfiguration(execution.configuration || {});
  };
  const start = async () => {
    setBusy(true); setError("");
    try {
      const execution: Execution = { backend, model: replay ? "retained-poc" : model.trim(), reasoning: replay ? "none" : reasoning, budget_usd: replay ? 0 : Number(budget), configuration: { ...executionConfiguration, timeout_seconds: Number(executionConfiguration.timeout_seconds || 120), max_output_tokens: Number(executionConfiguration.max_output_tokens || 4096), max_images: ["model_api", "litellm", "codex", "gemini_cli"].includes(backend) ? maxImages : 0 } };
      let id = preparedId;
      if (!id && sourceRunId) {
        const result = await apiRequest<{ id: string }>(`/runs/${sourceRunId}/${draft ? "configure" : "rerun"}`, { method: "POST", body: JSON.stringify({ ...(!draft ? { name: name.trim() } : {}), workflow_revision_id: workflow, execution }) });
        id = result.id || (draft ? sourceRunId : null);
      } else if (!id) {
        const result = await apiRequest<{ id: string }>("/runs", { method: "POST", body: JSON.stringify({ name: name.trim(), task_definition_ids: selectedTasks.map(task => task.task_definition_id || task.id), workflow_revision_id: workflow, execution, team_ids: teams.map(team => team.id), user_ids: people.map(person => person.id) }) });
        id = result.id;
      }
      if (!id) throw new Error("The server did not return a run ID.");
      setPreparedId(id);
      await apiRequest(`/runs/${id}/start`, { method: "POST", body: JSON.stringify({ confirm_budget: true, expected_budget_usd: execution.budget_usd }) });
      onCreated?.(id); onClose();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start analysis."); }
    finally { setBusy(false); }
  };
  return <><Dialog open={open} onClose={() => !busy && onClose()} maxWidth="md" fullWidth fullScreen={compact}>
    <DialogTitle sx={{ pb: 1 }}>Configure {sourceRunId && !draft ? "a new run" : "analysis"}<Typography color="text.secondary" sx={{ fontSize: 14, mt: .5 }}>Choose the scope, prompt workflow and execution settings. Nothing runs until you confirm below.</Typography></DialogTitle>
    <DialogContent dividers><Stack gap={2.5}>
      {error && <Alert severity="error">{error}{preparedId && <Box sx={{ mt: .5 }}>The draft is saved. Retrying starts this same draft instead of creating a duplicate.</Box>}</Alert>}
      {[catalog, workflows, providers, source].filter(item => item.error).map((item, index) => <ErrorState key={index} message={item.error} onRetry={item.reload} />)}
      {(source.loading || workflows.loading || providers.loading) ? <LoadingState label="Loading run configuration…" /> : <>
      <Panel sx={{ p: 2 }}><Stack direction={{ xs: "column", sm: "row" }} alignItems={{ xs: "stretch", sm: "center" }} justifyContent="space-between" gap={2}><Box><Typography fontWeight={750}>1. Tasks to review</Typography><Typography color="text.secondary">{sourceRunId ? "Uses the source run's pinned tasks and revisions." : `${countLabel(taskCount, "task")} across ${countLabel(new Set(selectedTasks.map(task => task.dataset_id)).size, "dataset")}`}</Typography></Box>{!sourceRunId && <Button variant="outlined" startIcon={<TuneRounded />} onClick={() => setSelectOpen(true)} sx={{ width: { xs: "100%", sm: "auto" } }}>Choose tasks</Button>}</Stack>{!sourceRunId && !!selectedTasks.length && <Stack direction="row" gap={.8} flexWrap="wrap" sx={{ mt: 1 }}>{[...new Set(selectedTasks.map(task => task.dataset_id))].map(id => <Chip key={id} size="small" label={catalog.data?.datasets.find(item => item.id === id)?.name || "Dataset"} />)}</Stack>}</Panel>
      <TextField label="Run name" value={name} onChange={event => setName(event.target.value)} disabled={!!preparedId || (!!sourceRunId && draft)} required />
      <Box><Typography fontWeight={750} sx={{ mb: 1.3 }}>2. Prompt workflow</Typography><FormControl fullWidth><InputLabel id="run-workflow-label">Workflow preset</InputLabel><Select labelId="run-workflow-label" label="Workflow preset" value={workflow} disabled={!!preparedId} onChange={event => { setWorkflow(event.target.value); setAccepted(false); }}>{workflows.data?.items.map(item => <MenuItem key={item.revision_id} value={item.revision_id}>{item.name} · {item.revision_id}</MenuItem>)}</Select></FormControl>{chosenWorkflow && <><Typography color="text.secondary" sx={{ mt: 1, fontSize: 14 }}>{chosenWorkflow.description}</Typography><Stack direction="row" gap={.8} flexWrap="wrap" sx={{ mt: 1 }}><Chip size="small" label="Recorded outcome" /><Typography>→</Typography><Chip size="small" label="Failure analysis OR pass recovery" /><Typography>→</Typography><Chip size="small" label="Problem labels & evidence" /><Typography>→</Typography><Chip size="small" label="Human taxonomy review" /></Stack><Box component="details" sx={{ mt: 1 }}><Box component="summary" sx={{ cursor: "pointer", fontWeight: 650, color: "primary.main" }}>Read the stage instructions</Box><Typography color="text.secondary" sx={{ fontSize: 12.5, mt: .5 }}>The reviewer also receives shared evidence rules, the output schema and selected task.</Typography>{chosenWorkflow.stages.map(stage => <Box key={stage.id} sx={{ mt: 1.5 }}><Typography fontWeight={700}>{stage.name}</Typography><Typography sx={{ fontSize: 13, whiteSpace: "pre-wrap", maxHeight: 180, overflow: "auto", mt: .5 }}>{stage.prompt}</Typography></Box>)}</Box></>}</Box>
      <Divider /><Box><Typography fontWeight={750} sx={{ mb: 1.3 }}>3. Harness and model</Typography>
      {!!savedPresets.data?.items.length && <TextField select fullWidth label="Saved execution preset" value={savedPresetId} disabled={!!preparedId} onChange={event => chooseSavedPreset(event.target.value)} helperText="Optional shortcut. You can adjust its model and budget for this new run." sx={{ mb: 1.8 }}><MenuItem value="">Custom settings</MenuItem>{savedPresets.data.items.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}</TextField>}
      <Grid container spacing={1.6}>
        <Grid size={{ xs: 12, sm: 6 }}><FormControl fullWidth required><InputLabel id="run-harness-label">Harness</InputLabel><Select labelId="run-harness-label" label="Harness" value={backend} disabled={!!preparedId} onChange={event => { setSavedPresetId(""); setExecutionConfiguration({}); setMaxImages(32); setBackend(event.target.value); setModel(""); setBudget("0.10"); setAccepted(false); }}><MenuItem value="" disabled>Choose how to run</MenuItem>{providers.data?.backends.filter(item => item.id !== "litellm").map(item => <MenuItem key={item.id} value={item.id} disabled={item.supported === false || item.configured === false}>{item.id === "saved_replay" ? "Open saved diagnosis (no new analysis)" : item.name}{(item.supported === false || item.configured === false) ? " · not configured" : ""}</MenuItem>)}</Select></FormControl></Grid>
        <Grid size={{ xs: 12, sm: 6 }}><ModelPicker backend={backend} value={model} catalog={modelCatalog} disabled={!!preparedId} onChange={item => { setModel(item?.id || ""); setBudget(suggestedBudget(item || undefined).toFixed(2)); setAccepted(false); }} /></Grid>
        {live && <><Grid size={{ xs: 12, sm: 6 }}><FormControl fullWidth><InputLabel id="run-reasoning-label">Reasoning effort</InputLabel><Select labelId="run-reasoning-label" label="Reasoning effort" value={reasoning} disabled={!!preparedId} onChange={event => { setReasoning(event.target.value); setAccepted(false); }}>{["none", "low", "medium", "high"].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}</Select></FormControl></Grid><Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="Estimated budget per task (USD)" type="number" value={budget} disabled={!!preparedId} onChange={event => { setBudget(event.target.value); setAccepted(false); }} inputProps={{ min: .01, max: .5, step: .01 }} helperText={selectedModel?.budget_basis === "pricing_estimate" ? "Suggested from 12k input + 4k output tokens with headroom. Adjust for your task." : "Starts at $0.10 per task. This is a planning allowance, not a measured price; maximum $0.50."} /></Grid>{["model_api", "litellm", "codex", "gemini_cli"].includes(backend) && <Grid size={12}><TextField select fullWidth label="Screenshot evidence" value={maxImages} disabled={!!preparedId} onChange={event => { setMaxImages(Number(event.target.value)); setAccepted(false); }} helperText="Source screenshots are supplied to supported image models, up to this count. Sent does not mean the reviewer examined every image."><MenuItem value={0}>Text only: send no screenshots</MenuItem><MenuItem value={3}>Send up to 3 sampled screenshots</MenuItem><MenuItem value={5}>Send up to 5 sampled screenshots</MenuItem><MenuItem value={32}>Send all available screenshots (up to 32)</MenuItem></TextField></Grid>}</>}
      </Grid>{live && <Typography color="text.secondary" sx={{ mt: 1, fontSize: 13 }}>Per invocation: up to {Number(executionConfiguration.timeout_seconds || 120)} seconds; {Number(executionConfiguration.max_output_tokens || 4096).toLocaleString()} output-token setting. CLI token-limit enforcement depends on the harness.</Typography>}{chosenProvider?.description && <Typography color="text.secondary" sx={{ mt: 1, fontSize: 14 }}>{chosenProvider.description}</Typography>}{["codex", "gemini_cli", "claude_code"].includes(backend) && <Alert severity="info" sx={{ mt: 1 }}>Codex and Gemini CLI receive the selected screenshot evidence with the task text. Unavailable or omitted frames stay explicit. The budget is an estimate; the CLI cannot guarantee a hard dollar cap.</Alert>}</Box>
      {!sourceRunId && <><Divider /><Box><Typography fontWeight={750} sx={{ mb: 1.3 }}>4. Share this run</Typography><Grid container spacing={1.6}><Grid size={{ xs: 12, sm: 6 }}><Autocomplete multiple options={directory.data?.teams || []} value={teams} onChange={(_, value) => setTeams(value)} getOptionLabel={item => item.name} isOptionEqualToValue={(a, b) => a.id === b.id} onInputChange={(_, value) => setPersonSearch(value)} renderInput={params => <TextField {...params} label="Teams" placeholder="Search teams" />} /></Grid><Grid size={{ xs: 12, sm: 6 }}><Autocomplete multiple filterOptions={values => values} options={directory.data?.users || []} value={people} onChange={(_, value) => setPeople(value)} getOptionLabel={item => `${item.name} (${item.email})`} isOptionEqualToValue={(a, b) => a.id === b.id} onInputChange={(_, value) => setPersonSearch(value)} renderInput={params => <TextField {...params} label="People" placeholder="Name or email" />} /></Grid></Grid><Typography color="text.secondary" sx={{ fontSize: 13, mt: 1 }}>Selected teams and people receive reviewer access. Dataset sharing is managed on the dataset page.</Typography></Box></>}
      <Alert severity={replay ? "info" : "warning"}>{replay ? "Saved replay reuses an existing diagnosis. It does not evaluate new tasks or make a model call." : `This starts new analysis. Per-attempt allowance: $${Number(budget || 0).toFixed(2)} per task${taskCount ? ` · $${(Number(budget || 0) * taskCount).toFixed(2)} for ${countLabel(taskCount, "task")}` : ""}. Planned allowance, including retries: $${plannedRetryAllowance.toFixed(2)} for up to ${MAX_REVIEW_ATTEMPTS} attempts per task. Billing estimate, not a provider spending cap. Unknown actual cost stays unknown.`}</Alert>
      <FormControlLabel control={<Checkbox checked={accepted} disabled={!!preparedId} onChange={(_, value) => setAccepted(value)} />} label={replay ? "Use the saved diagnoses for these tasks." : "I reviewed the task selection, model, evidence and estimated budget."} />
      </>}
    </Stack></DialogContent><DialogActions sx={{ p: 2, flexDirection: { xs: "column-reverse", sm: "row" }, alignItems: { xs: "stretch", sm: "center" }, gap: { xs: 1, sm: 0 }, "& .MuiButton-root": { whiteSpace: "normal", width: { xs: "100%", sm: "auto" } } }}><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="contained" startIcon={<PlayArrowRounded />} disabled={!canSubmit} onClick={start}>{busy ? "Starting…" : preparedId ? "Retry starting saved draft" : replay ? "Open saved diagnoses" : "Start analysis"}</Button></DialogActions>
  </Dialog><SelectionDialog open={selectOpen} onClose={() => setSelectOpen(false)} value={selection} onApply={value => { setSelection(value); setAccepted(false); }} mode="scope" /></>;
}
