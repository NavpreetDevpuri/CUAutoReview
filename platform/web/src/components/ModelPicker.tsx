import { Alert, Autocomplete, Box, Button, TextField, Typography } from "@mui/material";
import type { LoadState } from "../hooks/useApi";

export interface ModelChoice {
  id: string;
  display_name?: string;
  provider?: string;
  recommended?: boolean;
  suggested_budget_usd?: number;
  budget_basis?: string;
  input_cost_per_million?: number;
  output_cost_per_million?: number;
}
export interface ModelCatalog {
  backend: string;
  models: ModelChoice[];
  source?: string;
  status?: string;
  fetched_at?: string;
  note?: string;
}
export function preferredModel(models: ModelChoice[], backend: string) {
  const preferred = backend === "codex" ? "gpt-6-sol" : backend === "gemini_cli" ? "gemini-3.8-flash" : "gemini/gemini-3.8-flash";
  return models.find(item => item.id === preferred) || models.find(item => item.recommended) || models[0];
}
export function suggestedBudget(model?: ModelChoice) {
  return Number.isFinite(model?.suggested_budget_usd) && Number(model?.suggested_budget_usd) > 0
    ? Math.min(.5, Number(model?.suggested_budget_usd)) : .10;
}
export function ModelPicker({ backend, value, onChange, catalog, disabled = false }: {
  backend: string; value: string; onChange: (model: ModelChoice | null) => void;
  catalog: LoadState<ModelCatalog>; disabled?: boolean;
}) {
  const replay = backend === "saved_replay";
  const models = catalog.data?.backend === backend ? catalog.data.models : [];
  const selected = models.find(item => item.id === value) || null;
  return <Box>
    <Autocomplete options={models} value={selected} onChange={(_, item) => onChange(item)}
      disabled={disabled || !backend || replay || catalog.loading} loading={catalog.loading}
      getOptionLabel={item => item.display_name && item.display_name !== item.id ? `${item.display_name} (${item.id})` : item.id}
      isOptionEqualToValue={(a, b) => a.id === b.id}
      noOptionsText="No models discovered for this harness"
      renderInput={params => <TextField {...params} label="Model" required={!!backend && !replay}
        helperText={replay ? "Saved replay uses the original model's result. No new model or cost." : !backend ? "Choose a harness first." : catalog.loading ? "Loading discovered models…" : "Search and choose a model reported by the configured provider."} />}
    />
    {!replay && !!backend && catalog.error && <Alert severity="error" sx={{ mt: 1 }} action={<Button onClick={catalog.reload}>Retry</Button>}>{catalog.error}</Alert>}
    {!replay && !!backend && !catalog.loading && !catalog.error && !models.length && <Alert severity="warning" sx={{ mt: 1 }}>No model catalog is available. Refresh provider metadata on the local server before starting a run.</Alert>}
    {!replay && catalog.data?.backend === backend && catalog.data?.note && <Typography color="text.secondary" sx={{ mt: .6, fontSize: 12.5 }}>{catalog.data.note}</Typography>}
    {!replay && value && !selected && !catalog.loading && <Alert severity="warning" sx={{ mt: 1 }}>The previous model ({value}) is not in the current list. Select an available model to continue.</Alert>}
  </Box>;
}
