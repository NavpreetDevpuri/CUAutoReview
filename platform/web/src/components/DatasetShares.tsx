import { useEffect, useMemo, useState } from "react";
import {
  Autocomplete,
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import PersonAddAlt1Rounded from "@mui/icons-material/PersonAddAlt1Rounded";
import { apiRequest } from "../api/client";
import { Panel, SectionTitle } from "./Page";
import { ErrorState, LoadingState } from "./States";
import { useApi } from "../hooks/useApi";

type ShareRole = "viewer" | "reviewer" | "manager";
type Row = Record<string, unknown>;
interface DirectoryRecord {
  id: string;
  kind: "user" | "team";
  name: string;
  detail?: string;
  role?: ShareRole;
}
interface ShareState {
  workspace_shared?: boolean;
  users?: Record<string, unknown>[];
  teams?: Record<string, unknown>[];
}
function parseRows(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) return value as Record<string, unknown>[];
  if (value && typeof value === "object") {
    const body = value as { items?: unknown[]; users?: unknown[]; teams?: unknown[] };
    if (Array.isArray(body.items)) return body.items as Record<string, unknown>[];
    return [
      ...(Array.isArray(body.users) ? body.users : []),
      ...(Array.isArray(body.teams) ? body.teams : []),
    ] as Record<string, unknown>[];
  }
  return [];
}
function sharesToDirectory(shares: ShareState): DirectoryRecord[] {
  return [
    ...(shares.users || []).map(row => ({
      id: String(row.user_id || row.target_id || row.id || ""),
      kind: "user" as const,
      name: String(row.name || row.email || row.user_id || "Workspace user"),
      detail: String(row.email || ""),
      role: (row.role || "reviewer") as ShareRole,
    })),
    ...(shares.teams || []).map(row => ({
      id: String(row.team_id || row.target_id || row.id || ""),
      kind: "team" as const,
      name: String(row.name || row.team_id || "Team"),
      detail: "Team",
      role: (row.role || "reviewer") as ShareRole,
    })),
  ].filter(row => row.id);
}

export function DatasetShares({ datasetId }: { datasetId: string }) {
  const sharesState = useApi<ShareState>(`/datasets/${encodeURIComponent(datasetId)}/shares`);
  const shares = sharesState.data;
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [open, setOpen] = useState(false);
  // Optimistic value while a workspace-sharing change is saving; otherwise the saved state is shown.
  const [pendingWorkspace, setPendingWorkspace] = useState<boolean | null>(null);
  const workspaceShared = pendingWorkspace ?? Boolean(shares?.workspace_shared);
  const [selected, setSelected] = useState<DirectoryRecord | null>(null);
  const [role, setRole] = useState<ShareRole>("reviewer");
  const [query, setQuery] = useState("");
  const [directory, setDirectory] = useState<DirectoryRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const existing = useMemo(() => sharesToDirectory(shares || {}), [shares]);
  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      const suffix = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
      apiRequest<unknown>(`/directory${suffix}`)
        .then(result => {
          if (!active) return;
          const body = result && typeof result === "object" ? (result as { users?: Row[]; teams?: Row[] }) : {};
          const classified = [
            ...(Array.isArray(body.users) ? body.users.map(row => ({ row, kind: "user" as const })) : []),
            ...(Array.isArray(body.teams) ? body.teams.map(row => ({ row, kind: "team" as const })) : []),
          ];
          const fallback = classified.length
            ? []
            : parseRows(result).map(row => ({
                row,
                kind:
                  String(row.kind || row.type || (row.team_id ? "team" : "user")).toLowerCase() === "team"
                    ? ("team" as const)
                    : ("user" as const),
              }));
          setDirectory(
            [...classified, ...fallback]
              .map(({ row, kind }) => {
                const id = String(row.id || row.user_id || row.team_id || "");
                return {
                  id,
                  kind,
                  name: String(row.name || row.email || row.display_name || id),
                  detail: String(row.email || (kind === "team" ? "Team" : "User")),
                };
              })
              .filter(row => row.id),
          );
        })
        .catch(() => {
          if (active) setDirectory([]);
        });
    }, 180);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query]);
  const save = async (nextWorkspace = workspaceShared, nextRows = existing) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const users = nextRows
        .filter(row => row.kind === "user")
        .map(row => ({ target_id: row.id, role: row.role || "reviewer" }));
      const teams = nextRows
        .filter(row => row.kind === "team")
        .map(row => ({ target_id: row.id, role: row.role || "reviewer" }));
      await apiRequest<ShareState>(`/datasets/${encodeURIComponent(datasetId)}/shares`, {
        method: "PUT",
        body: JSON.stringify({ workspace_shared: nextWorkspace, users, teams }),
      });
      await sharesState.refreshQuietly();
      setNotice("Dataset access updated.");
      setOpen(false);
      setSelected(null);
      setQuery("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Dataset access could not be updated.");
    } finally {
      setBusy(false);
    }
  };
  const add = () => {
    if (!selected || existing.some(row => row.kind === selected.kind && row.id === selected.id)) return;
    void save(workspaceShared, [...existing, { ...selected, role }]);
  };
  const remove = (record: DirectoryRecord) =>
    void save(
      workspaceShared,
      existing.filter(row => !(row.kind === record.kind && row.id === record.id)),
    );
  const setWorkspace = (value: boolean) => {
    setPendingWorkspace(value);
    void save(value, existing).finally(() => setPendingWorkspace(null));
  };

  return (
    <>
      <Panel>
        <SectionTitle
          title="Dataset access"
          subtitle="Share with the workspace, specific people, or teams."
          action={
            <Button
              size="small"
              startIcon={<PersonAddAlt1Rounded />}
              onClick={() => {
                setError("");
                setOpen(true);
              }}
            >
              Add people or teams
            </Button>
          }
        />
        {(error || sharesState.error) && (
          <ErrorState
            message={error || sharesState.error}
            onRetry={() => {
              setError("");
              sharesState.reload();
            }}
          />
        )}
        {notice && (
          <Alert severity="success" onClose={() => setNotice("")} sx={{ mb: 1.2 }}>
            {notice}
          </Alert>
        )}
        {sharesState.loading ? (
          <LoadingState label="Loading dataset access…" />
        ) : (
          <Stack gap={1.1}>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              alignItems={{ sm: "center" }}
              justifyContent="space-between"
              gap={1}
              sx={{ p: 1.2, border: "1px solid", borderColor: "divider", borderRadius: 2 }}
            >
              <Box>
                <Typography sx={{ fontWeight: 700 }}>Workspace access</Typography>
                <Typography color="text.secondary" sx={{ fontSize: 13 }}>
                  All active workspace members can discover this dataset.
                </Typography>
              </Box>
              <Checkbox
                checked={workspaceShared}
                onChange={event => setWorkspace(event.target.checked)}
                inputProps={{ "aria-label": "Share dataset with all workspace members" }}
              />
            </Stack>
            {existing.map(row => (
              <Grid
                key={`${row.kind}:${row.id}`}
                container
                alignItems="center"
                spacing={1}
                sx={{ p: 1.1, border: "1px solid", borderColor: "divider", borderRadius: 2 }}
              >
                <Grid size={{ xs: 12, sm: 6 }}>
                  <Typography sx={{ fontWeight: 700 }}>{row.name}</Typography>
                  <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                    {row.kind === "team" ? "Team" : row.detail || "User"}
                  </Typography>
                </Grid>
                <Grid size={{ xs: 7, sm: 4 }}>
                  <Typography sx={{ fontSize: 13, textTransform: "capitalize" }}>{row.role || "reviewer"}</Typography>
                </Grid>
                <Grid size={{ xs: 5, sm: 2 }}>
                  <Button size="small" color="error" onClick={() => remove(row)} disabled={busy}>
                    Remove
                  </Button>
                </Grid>
              </Grid>
            ))}
            {!existing.length && !workspaceShared && (
              <Typography color="text.secondary" sx={{ fontSize: 14 }}>
                No additional people or teams have access.
              </Typography>
            )}
          </Stack>
        )}
      </Panel>
      <Dialog open={open} onClose={() => !busy && setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Share dataset</DialogTitle>
        <DialogContent>
          <Stack gap={2} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <Autocomplete
              options={directory}
              value={selected}
              onChange={(_, value) => setSelected(value)}
              inputValue={query}
              onInputChange={(_, value) => setQuery(value)}
              getOptionLabel={option => option.name}
              isOptionEqualToValue={(a, b) => a.kind === b.kind && a.id === b.id}
              renderOption={(props, option) => (
                <li {...props} key={`${option.kind}:${option.id}`}>
                  <Box>
                    <Typography sx={{ fontWeight: 650 }}>{option.name}</Typography>
                    <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                      {option.kind === "team" ? "Team" : option.detail || "User"}
                    </Typography>
                  </Box>
                </li>
              )}
              renderInput={params => (
                <TextField
                  {...params}
                  autoFocus
                  label="Find a person or team"
                  placeholder="Search active people and teams"
                />
              )}
            />
            <FormControl fullWidth>
              <InputLabel id="dataset-share-role">Role</InputLabel>
              <Select
                labelId="dataset-share-role"
                label="Role"
                value={role}
                onChange={event => setRole(event.target.value as ShareRole)}
              >
                <MenuItem value="manager">Manager</MenuItem>
                <MenuItem value="reviewer">Reviewer</MenuItem>
                <MenuItem value="viewer">Viewer</MenuItem>
              </Select>
            </FormControl>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              Existing access is retained when a new grant is added.
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={add}
            disabled={busy || !selected || existing.some(row => row.kind === selected.kind && row.id === selected.id)}
          >
            Add access
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
