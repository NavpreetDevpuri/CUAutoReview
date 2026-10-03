import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddRounded from "@mui/icons-material/AddRounded";
import { Alert as MuiAlert } from "@mui/material";
import { apiRequest } from "../api/client";
import { type ModelCatalog, ModelPicker, preferredModel, suggestedBudget } from "../components/ModelPicker";
import { PageHeader, Panel, SectionTitle } from "../components/Page";
import { ErrorState, LoadingState } from "../components/States";
import { StatusTag } from "../components/StatusTag";
import { useApi } from "../hooks/useApi";
import { useResourceList } from "../hooks/useResourceList";
import { displayValue, formatDate } from "../lib/format";

interface Preset {
  id: string;
  name: string;
  backend?: string;
  model?: string;
  reasoning?: string;
  budget_usd?: number;
  revision?: number;
  configuration?: Record<string, unknown>;
  [key: string]: unknown;
}
type ProviderChoice =
  | string
  | {
      id?: string;
      name?: string;
      configured?: boolean;
      supported?: boolean;
      available?: boolean;
      status?: string;
      capabilities?: string[];
    };
interface ProviderInfo {
  backends?: ProviderChoice[];
  providers?: ProviderChoice[];
  default_backend?: string;
  [key: string]: unknown;
}
interface WorkflowStage {
  id: string;
  name?: string;
  kind?: string;
  prompt?: string;
  [key: string]: unknown;
}
interface Workflow {
  id: string;
  revision_id?: string;
  name?: string;
  version?: number;
  description?: string;
  supported_backends?: string[];
  stages?: WorkflowStage[];
  [key: string]: unknown;
}
interface WorkflowList {
  items?: Workflow[];
}

export function PresetsPage() {
  const presets = useResourceList<Preset>("presets");
  const workflows = useApi<WorkflowList | Workflow[]>("/workflows");
  const providers = useApi<ProviderInfo>("/providers");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [backend, setBackend] = useState("");
  const [model, setModel] = useState("");
  const modelCatalog = useApi<ModelCatalog>(
    open && backend && backend !== "saved_replay" ? `/providers/models?backend=${encodeURIComponent(backend)}` : null,
  );
  const [reasoning, setReasoning] = useState("low");
  const [budget, setBudget] = useState("0.10");
  const [configurationText, setConfigurationText] = useState("{}");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const providerOptions = useMemo(() => {
    const values: ProviderChoice[] = providers.data?.backends || providers.data?.providers || [];
    return values.map(value =>
      typeof value === "string"
        ? { id: value, name: value, configured: true, supported: true }
        : {
            id: String(value.id || value.name || "unknown"),
            name: String(value.name || value.id || "unknown"),
            configured: value.configured ?? value.available ?? false,
            supported: value.supported ?? true,
            status: value.status,
          },
    );
  }, [providers.data]);
  const availableModels = modelCatalog.data?.backend === backend ? modelCatalog.data.models : [];
  const selectedModel = availableModels.find(item => item.id === model);
  // Suggest the provider's preferred model once its catalog loads, until the user picks one.
  if (open && !model && !modelCatalog.loading && modelCatalog.data?.backend === backend) {
    const next = preferredModel(availableModels, backend);
    if (next) {
      setModel(next.id);
      setBudget(suggestedBudget(next).toFixed(2));
    }
  }
  const replay = backend === "saved_replay";
  const validBudget = replay || (Number(budget) > 0 && Number(budget) <= 0.5);
  const canCreate =
    !!name.trim() &&
    !!backend &&
    !busy &&
    (replay || (!!selectedModel && !modelCatalog.loading && !modelCatalog.error && validBudget));
  const create = async () => {
    setError("");
    let configuration: unknown;
    try {
      configuration = JSON.parse(configurationText);
    } catch {
      setError("Configuration must be valid JSON.");
      return;
    }
    setBusy(true);
    try {
      const chosen = providerOptions.find(item => item.id === backend);
      if (chosen?.supported === false || (backend !== "saved_replay" && chosen?.configured === false)) {
        setError(chosen?.status || "This backend is unavailable. Choose a configured backend.");
        return;
      }
      if (backend !== "saved_replay" && (!selectedModel || !validBudget)) {
        setError("Choose a discovered model and a positive per-task budget up to $0.50.");
        return;
      }
      const selectedModelId = backend === "saved_replay" ? "retained-poc" : model.trim();
      const result = await apiRequest<Record<string, unknown>>("/presets", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          backend,
          model: selectedModelId,
          reasoning,
          budget_usd: backend === "saved_replay" ? 0 : Number(budget),
          configuration,
        }),
      });
      setNotice(`New immutable preset revision created: ${displayValue(result.revision ?? result.id)}.`);
      setOpen(false);
      setName("");
      presets.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Preset could not be created.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHeader
        eyebrow="WORKFLOW AND EXECUTION"
        title="Workflows and presets"
        description="A workflow controls the review stages and exact prompt text. A preset supplies the harness and model settings used by a run."
        action={
          <Button
            variant="contained"
            startIcon={<AddRounded />}
            onClick={() => {
              setError("");
              setBackend("");
              setModel("");
              setBudget("0.10");
              setConfigurationText("{}");
              setOpen(true);
            }}
          >
            New execution preset
          </Button>
        }
      />
      {notice && (
        <MuiAlert severity="success" onClose={() => setNotice("")} sx={{ mb: 2 }}>
          {notice}
        </MuiAlert>
      )}
      {providers.error && (
        <ErrorState message={`Provider capabilities are unavailable: ${providers.error}`} onRetry={providers.reload} />
      )}
      {providers.data && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Default backend: <strong>{providers.data.default_backend || "saved_replay"}</strong>. Provider status reports
          availability and capabilities only; credentials are never shown.
        </Alert>
      )}
      {error && !open && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {workflows.loading && <LoadingState label="Loading review workflows…" />}
      {workflows.error && (
        <ErrorState message={`Workflow definitions are unavailable: ${workflows.error}`} onRetry={workflows.reload} />
      )}
      {!!workflows.data && (
        <Panel sx={{ mb: 2.2 }}>
          <SectionTitle
            title="Review workflows"
            subtitle="Stages and prompt text define what the reviewer does. Runs pin the exact workflow revision."
          />
          {(() => {
            const rows = Array.isArray(workflows.data) ? workflows.data : workflows.data.items || [];
            return !rows.length ? (
              <Typography color="text.secondary">No workflow definitions are available.</Typography>
            ) : (
              <Stack gap={1.2}>
                {rows.map(workflow => (
                  <Paper
                    key={workflow.revision_id || workflow.id}
                    variant="outlined"
                    sx={{ p: 1.5, borderRadius: 2.2 }}
                  >
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      alignItems={{ sm: "center" }}
                      justifyContent="space-between"
                      gap={1}
                    >
                      <Box>
                        <Typography sx={{ fontWeight: 780 }}>{workflow.name || workflow.id}</Typography>
                        <Typography color="text.secondary" sx={{ mt: 0.3, fontSize: 12.5 }}>
                          {workflow.revision_id || workflow.id} · version {workflow.version ?? "not recorded"}
                        </Typography>
                      </Box>
                      <Stack direction="row" gap={0.5} flexWrap="wrap">
                        {(workflow.supported_backends || []).map(backendName => (
                          <StatusTag key={backendName} value={backendName} />
                        ))}
                      </Stack>
                    </Stack>
                    {workflow.description && (
                      <Typography color="text.secondary" sx={{ mt: 1, fontSize: 13.5 }}>
                        {workflow.description}
                      </Typography>
                    )}
                    <Grid container spacing={1.2} sx={{ mt: 0.3 }}>
                      {(workflow.stages || []).map((stage, index) => (
                        <Grid key={stage.id || index} size={{ xs: 12, md: 6 }}>
                          <Paper
                            variant="outlined"
                            sx={{ height: "100%", p: 1.2, borderRadius: 2, bgcolor: "background.default" }}
                          >
                            <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1}>
                              <Typography sx={{ fontWeight: 750, fontSize: 14 }}>
                                {stage.name || stage.id || `Stage ${index + 1}`}
                              </Typography>
                              <StatusTag value={stage.kind || stage.id} />
                            </Stack>
                            <Box component="details" sx={{ mt: 0.8 }}>
                              <Box
                                component="summary"
                                sx={{ cursor: "pointer", color: "primary.main", fontWeight: 700, fontSize: 13 }}
                              >
                                Stage instructions
                              </Box>
                              <Typography color="text.secondary" sx={{ mt: 0.6, fontSize: 12.5 }}>
                                The reviewer also receives the shared evidence rules, output schema, and selected task.
                              </Typography>
                              <Typography
                                component="pre"
                                sx={{
                                  mt: 0.7,
                                  mb: 0,
                                  p: 1.1,
                                  maxHeight: 300,
                                  overflow: "auto",
                                  whiteSpace: "pre-wrap",
                                  overflowWrap: "anywhere",
                                  bgcolor: "action.hover",
                                  color: "text.primary",
                                  borderRadius: 1.5,
                                  fontSize: 12.5,
                                }}
                              >
                                {stage.prompt || "Stage instructions not recorded."}
                              </Typography>
                            </Box>
                          </Paper>
                        </Grid>
                      ))}
                    </Grid>
                  </Paper>
                ))}
              </Stack>
            );
          })()}
        </Panel>
      )}
      <SectionTitle
        title="Execution presets"
        subtitle="Harness and model settings are separate from workflow prompts. Creating an execution preset adds an immutable configuration revision."
      />
      {presets.loading && <LoadingState label="Loading preset revisions…" />}
      {presets.error && <ErrorState message={presets.error} onRetry={presets.reload} />}
      {!presets.loading && !presets.error && !presets.data.length && (
        <Panel>
          <SectionTitle title="Saved replay" subtitle="No configurable preset revisions exist yet." />
          <Typography color="text.secondary">
            Saved replay is the default. It reads retained evidence and makes no model calls. Create a preset revision
            only when you need a different approved workflow or backend.
          </Typography>
        </Panel>
      )}
      {!!presets.data.length && (
        <Grid container spacing={1.8}>
          {presets.data.map(preset => {
            const revision = (preset.latest_revision || {}) as Record<string, unknown>;
            const backendValue = String(revision.backend || preset.backend || "saved_replay");
            const reasoningValue = String(revision.reasoning || preset.reasoning || "Reasoning not recorded");
            const modelValue = String(revision.model || preset.model || "No hosted model");
            const budgetValue = revision.budget_usd ?? preset.budget_usd;
            const budgetLabel = backendValue === "saved_replay" ? "Cost" : "Per-task budget estimate";
            return (
              <Grid key={preset.id} size={{ xs: 12, md: 6, xl: 4 }}>
                <Panel sx={{ height: "100%" }}>
                  <Stack direction="row" justifyContent="space-between" gap={1}>
                    <Typography sx={{ fontSize: 15, fontWeight: 700, overflowWrap: "anywhere", minWidth: 0 }}>
                      {preset.name}
                    </Typography>
                    <StatusTag value={`Revision ${String(revision.revision ?? preset.revision ?? 1)}`} />
                  </Stack>
                  <Stack direction="row" gap={0.8} flexWrap="wrap" sx={{ mt: 1.3 }}>
                    <StatusTag value={backendValue} />
                    <StatusTag value={reasoningValue} />
                  </Stack>
                  <Box
                    component="dl"
                    sx={{
                      display: "grid",
                      gridTemplateColumns: "minmax(76px, .65fr) minmax(0, 1.35fr)",
                      columnGap: 1.2,
                      rowGap: 0.7,
                      mt: 1.4,
                      mb: 0,
                      fontSize: 13,
                    }}
                  >
                    <Box component="dt" sx={{ color: "text.secondary" }}>
                      Model
                    </Box>
                    <Box component="dd" sx={{ m: 0, fontWeight: 600, overflowWrap: "anywhere" }}>
                      {modelValue}
                    </Box>
                    <Box component="dt" sx={{ color: "text.secondary" }}>
                      {budgetLabel}
                    </Box>
                    <Box component="dd" sx={{ m: 0, overflowWrap: "anywhere" }}>
                      {backendValue === "saved_replay"
                        ? "Free replay, no new model call"
                        : budgetValue === undefined || budgetValue === null
                          ? "Not recorded"
                          : `$${Number(budgetValue).toFixed(2)} USD`}
                    </Box>
                  </Box>
                  <Typography color="text.secondary" sx={{ mt: 0.7, fontSize: 13 }}>
                    Created {formatDate(preset.created_at)}
                  </Typography>
                  <Box component="details" sx={{ mt: 1.2 }}>
                    <Box component="summary" sx={{ cursor: "pointer", color: "primary.main", fontWeight: 700 }}>
                      Configuration JSON
                    </Box>
                    <Box
                      component="pre"
                      sx={{
                        maxHeight: 220,
                        overflow: "auto",
                        p: 1.2,
                        borderRadius: 1.5,
                        bgcolor: "action.hover",
                        color: "text.primary",
                        fontSize: 12,
                      }}
                    >
                      {JSON.stringify(revision.configuration || preset.configuration || {}, null, 2)}
                    </Box>
                  </Box>
                </Panel>
              </Grid>
            );
          })}
        </Grid>
      )}
      <Dialog open={open} onClose={() => !busy && setOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>Create an execution preset revision</DialogTitle>
        <DialogContent>
          <Stack gap={2} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <Alert severity="info">
              This creates an immutable harness/model configuration. Workflow stage prompts are managed as a separate
              versioned workflow. Credentials are configured outside the UI and are never returned by the API.
            </Alert>
            <TextField
              autoFocus
              required
              label="Execution preset name"
              value={name}
              onChange={event => setName(event.target.value)}
            />
            <Grid container spacing={1.5}>
              <Grid size={{ xs: 12, md: 6 }}>
                <FormControl fullWidth>
                  <InputLabel id="preset-backend-label">Backend</InputLabel>
                  <Select
                    labelId="preset-backend-label"
                    label="Backend"
                    value={backend}
                    onChange={event => {
                      setBackend(String(event.target.value));
                      setModel("");
                      setBudget("0.10");
                    }}
                  >
                    <MenuItem value="" disabled>
                      Choose a harness
                    </MenuItem>
                    <MenuItem value="saved_replay">Saved replay · no model calls</MenuItem>
                    {providerOptions
                      .filter(item => item.id !== "saved_replay")
                      .map(item => (
                        <MenuItem
                          key={item.id}
                          value={item.id}
                          disabled={item.supported === false || item.configured === false}
                        >
                          {item.name} · {item.status || (item.configured ? "available" : "not configured")}
                        </MenuItem>
                      ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <ModelPicker
                  backend={backend}
                  value={model}
                  catalog={modelCatalog}
                  onChange={item => {
                    setModel(item?.id || "");
                    setBudget(suggestedBudget(item || undefined).toFixed(2));
                  }}
                />
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <FormControl fullWidth>
                  <InputLabel id="preset-reasoning-label">Reasoning effort</InputLabel>
                  <Select
                    labelId="preset-reasoning-label"
                    label="Reasoning effort"
                    value={reasoning}
                    onChange={event => setReasoning(String(event.target.value))}
                  >
                    <MenuItem value="none">None</MenuItem>
                    <MenuItem value="low">Low</MenuItem>
                    <MenuItem value="medium">Medium</MenuItem>
                    <MenuItem value="high">High</MenuItem>
                    <MenuItem value="xhigh">Extra high</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <TextField
                  fullWidth
                  type="number"
                  label="Estimated budget per task (USD)"
                  value={replay ? "0" : budget}
                  onChange={event => setBudget(event.target.value)}
                  inputProps={{ min: 0.01, max: 0.5, step: 0.01 }}
                  disabled={backend === "saved_replay"}
                  helperText={
                    replay
                      ? "Free: saved replay makes no new model call."
                      : selectedModel?.budget_basis === "pricing_estimate"
                        ? "Suggested from 12k input + 4k output tokens with headroom; adjust for your task."
                        : "Starts at $0.10 per task. A planning allowance, not a measured price. CLI billing is not capped."
                  }
                />
              </Grid>
              <Grid size={12}>
                <Box component="details">
                  <Box component="summary" sx={{ cursor: "pointer", fontWeight: 700, color: "primary.main", mb: 1 }}>
                    Advanced settings (optional)
                  </Box>
                  <TextField
                    fullWidth
                    label="Configuration JSON"
                    value={configurationText}
                    onChange={event => setConfigurationText(event.target.value)}
                    helperText="Leave empty settings to use the bounded defaults. Credentials belong in server configuration."
                    multiline
                    minRows={4}
                    sx={{ fontFamily: "ui-monospace, monospace" }}
                  />
                </Box>
              </Grid>
            </Grid>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="contained" onClick={create} disabled={!canCreate}>
            {busy ? "Saving…" : "Create immutable revision"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
