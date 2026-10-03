import { useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  Grid,
  MenuItem,
  Paper,
  Radio,
  RadioGroup,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddRounded from "@mui/icons-material/AddRounded";
import MergeTypeRounded from "@mui/icons-material/MergeTypeRounded";
import { apiRequest } from "../api/client";
import type { TaxonomyResponse } from "../api/types";
import { PageHeader, Panel, SectionTitle } from "../components/Page";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { StatusTag } from "../components/StatusTag";
import { useApi } from "../hooks/useApi";
import { useResourceList } from "../hooks/useResourceList";
import { displayValue, formatDate } from "../lib/format";

interface TaxonomyData extends TaxonomyResponse {
  releases?: Record<string, unknown>[];
  proposals?: Record<string, unknown>[];
  candidates?: Record<string, unknown>[];
  labels?: Record<string, unknown>[];
}
interface TaxonomyPreset extends Record<string, unknown> {
  id: string;
  name: string;
  latest_revision?: Record<string, unknown> | null;
}
interface ProviderInfo extends Record<string, unknown> {
  items?: Record<string, unknown>[];
  backends?: Record<string, unknown>[];
}
function candidateHash(candidate: Record<string, unknown>): string | undefined {
  const value = candidate.content_hash ?? candidate.hash;
  return typeof value === "string" && value ? value : undefined;
}

export function TaxonomyPage() {
  const state = useApi<TaxonomyData>("/taxonomy");
  const presets = useResourceList<TaxonomyPreset>("presets");
  const providers = useApi<ProviderInfo>("/providers");
  const [proposalOpen, setProposalOpen] = useState(false);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateMode, setCandidateMode] = useState<"deterministic" | "model">("deterministic");
  const [presetRevisionId, setPresetRevisionId] = useState("");
  const [budgetConfirmed, setBudgetConfirmed] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState("label");
  const [labelId, setLabelId] = useState("");
  const [evidenceText, setEvidenceText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const proposals = state.data?.proposals || [];
  const candidates = state.data?.candidates || [];
  const releases = state.data?.releases || [];
  const labels = state.data?.labels || [];
  const providerRows = providers.data?.items || providers.data?.backends || [];
  const apiProviderReady = providerRows.some(
    provider =>
      ["model_api", "litellm"].includes(String(provider.id)) &&
      provider.supported !== false &&
      provider.configured === true,
  );
  const eligiblePresets = presets.data.flatMap(preset => {
    const revision = preset.latest_revision || {};
    const backend = String(revision.backend || preset.backend || "");
    const revisionId = String(revision.id || "");
    const budget = Number(revision.budget_usd ?? preset.budget_usd);
    if (
      !revisionId ||
      !["model_api", "api", "litellm"].includes(backend) ||
      !Number.isFinite(budget) ||
      budget <= 0 ||
      budget > 5
    )
      return [];
    return [{ preset, revision, revisionId, budget }];
  });
  const usablePresets = apiProviderReady ? eligiblePresets : [];
  const selectedPreset = usablePresets.find(item => item.revisionId === presetRevisionId) || usablePresets[0];

  const submitProposal = async () => {
    setBusy(true);
    setError("");
    try {
      const payload: Record<string, unknown> = { name: name.trim(), description: description.trim(), kind };
      if (labelId) payload.label_id = labelId;
      const evidence_refs = evidenceText
        .split(/\n|,/)
        .map(value => value.trim())
        .filter(Boolean);
      if (evidence_refs.length) payload.evidence_refs = evidence_refs;
      await apiRequest("/taxonomy/proposals", { method: "POST", body: JSON.stringify(payload) });
      setProposalOpen(false);
      setName("");
      setDescription("");
      setLabelId("");
      setEvidenceText("");
      setNotice("Proposal revision added. The approved release is unchanged.");
      state.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Proposal could not be saved.");
    } finally {
      setBusy(false);
    }
  };
  const openCandidateBuilder = () => {
    setError("");
    setNotice("");
    setCandidateMode("deterministic");
    setPresetRevisionId("");
    setBudgetConfirmed(false);
    setCandidateOpen(true);
  };
  const consolidate = async () => {
    setBusy(true);
    setError("");
    try {
      const payload =
        candidateMode === "deterministic"
          ? {}
          : {
              preset_revision_id: selectedPreset?.revisionId,
              confirm_budget: true,
              expected_budget_usd: selectedPreset?.budget,
            };
      const result = await apiRequest<Record<string, unknown>>("/taxonomy/consolidate", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setCandidateOpen(false);
      setNotice(
        `Candidate ${displayValue(result.version || result.id)} created for human review. It has not been published.`,
      );
      state.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Taxonomy consolidation failed.");
    } finally {
      setBusy(false);
    }
  };
  const addFeedback = async (proposalId: string, text: string, clear: () => void) => {
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/taxonomy/proposals/${encodeURIComponent(proposalId)}/feedback`, {
        method: "POST",
        body: JSON.stringify({ text: text.trim() }),
      });
      clear();
      setNotice("Feedback appended to the proposal history.");
      state.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Feedback could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  if (state.loading) return <LoadingState label="Loading taxonomy releases and proposals…" />;
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  return (
    <>
      <PageHeader
        eyebrow="SHARED LABELS"
        title="Taxonomy"
        description="Proposals, consolidation candidates, and approved immutable releases are separate. Every candidate needs human review; admin approval publishes only the exact candidate hash shown."
        action={
          <Stack direction="row" gap={1} flexWrap="wrap">
            <Button variant="outlined" startIcon={<MergeTypeRounded />} disabled={busy} onClick={openCandidateBuilder}>
              Build candidate
            </Button>
            <Button
              variant="contained"
              startIcon={<AddRounded />}
              onClick={() => {
                setError("");
                setProposalOpen(true);
              }}
            >
              New proposal
            </Button>
          </Stack>
        }
      />
      {notice && (
        <Alert severity="success" onClose={() => setNotice("")} sx={{ mb: 1.6 }}>
          {notice}
        </Alert>
      )}
      {error && (
        <Alert severity="error" onClose={() => setError("")} sx={{ mb: 1.6 }}>
          {error}
        </Alert>
      )}
      <Grid container spacing={2} alignItems="flex-start">
        <Grid size={{ xs: 12, lg: 4 }}>
          <Panel>
            <SectionTitle title="Approved releases" subtitle="Pinned by a run when it is created." />
            {releases.length ? (
              <Stack gap={1}>
                {releases.map((release, i) => (
                  <Paper key={String(release.id || i)} variant="outlined" sx={{ p: 1.4, borderRadius: 2 }}>
                    <Stack direction="row" justifyContent="space-between">
                      <Typography sx={{ fontWeight: 750 }}>
                        {displayValue(release.name || release.version || `Release ${i + 1}`)}
                      </Typography>
                      <StatusTag value={release.status || "Approved"} />
                    </Stack>
                    <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: 13 }}>
                      {displayValue(
                        release.label_count ?? (Array.isArray(release.labels) ? release.labels.length : undefined),
                        "Not recorded",
                      )}{" "}
                      labels · {formatDate(release.created_at)}
                    </Typography>
                    <Typography color="text.secondary" sx={{ mt: 0.4, fontSize: 12 }}>
                      ID: {displayValue(release.id)}
                    </Typography>
                  </Paper>
                ))}
              </Stack>
            ) : (
              <Typography color="text.secondary">
                No approved releases have been published. Draft candidates do not change existing labels.
              </Typography>
            )}
          </Panel>
          <Panel sx={{ mt: 2 }}>
            <SectionTitle title="Canonical labels" subtitle={`${labels.length} recorded categories`} />
            {labels.length ? (
              <Stack gap={1}>
                {labels.map((label, i) => (
                  <Box
                    key={String(label.id || i)}
                    sx={{
                      p: 1.3,
                      borderLeft: "3px solid",
                      borderColor: "primary.main",
                      bgcolor: "action.hover",
                      borderRadius: 1.5,
                    }}
                  >
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      gap={0.5}
                      alignItems={{ sm: "baseline" }}
                      sx={{ overflowWrap: "anywhere" }}
                    >
                      <Typography sx={{ fontWeight: 750 }}>{displayValue(label.name)}</Typography>
                      <Typography color="text.secondary" sx={{ fontFamily: "monospace", fontSize: 12 }}>
                        {displayValue(label.id)}
                      </Typography>
                    </Stack>
                    <Typography color="text.secondary" sx={{ mt: 0.3, fontSize: 13 }}>
                      {displayValue(label.description, "No definition recorded.")}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            ) : (
              <Typography color="text.secondary">No categories recorded.</Typography>
            )}
          </Panel>
        </Grid>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Stack gap={2}>
            <Panel>
              <SectionTitle
                title="Proposals"
                subtitle="New and edited drafts append revisions without changing the approved release."
              />
              {proposals.length ? (
                <Stack gap={1.2}>
                  {proposals.map((proposal, i) => (
                    <ProposalCard
                      key={String(proposal.id || i)}
                      proposal={proposal}
                      labels={labels}
                      disabled={busy}
                      onFeedback={addFeedback}
                    />
                  ))}
                </Stack>
              ) : (
                <Typography color="text.secondary">
                  No proposals yet. Add an evidence-linked proposal or create a consolidation candidate after review
                  work.
                </Typography>
              )}
            </Panel>
            <Panel>
              <SectionTitle
                title="Consolidation candidates"
                subtitle="Review mappings, definitions, rationale, base release, and exact hash before publication."
              />
              {candidates.length ? (
                <Grid container spacing={1.2}>
                  {candidates.map((candidate, i) => {
                    const content = (candidate.content || {}) as Record<string, unknown>;
                    const candidateLabels = Array.isArray(candidate.labels)
                      ? candidate.labels
                      : Array.isArray(content.labels)
                        ? (content.labels as unknown[])
                        : undefined;
                    const candidateMappings = Array.isArray(candidate.mappings)
                      ? candidate.mappings
                      : Array.isArray(content.mappings)
                        ? (content.mappings as unknown[])
                        : undefined;
                    return (
                      <Grid key={String(candidate.id || i)} size={{ xs: 12, md: 6 }}>
                        <Paper
                          component={RouterLink}
                          to={`/taxonomy/candidates/${encodeURIComponent(String(candidate.id))}`}
                          variant="outlined"
                          sx={{
                            display: "block",
                            height: "100%",
                            p: 1.5,
                            borderRadius: 2,
                            color: "text.primary",
                            textDecoration: "none",
                            "&:hover": { borderColor: "primary.main", bgcolor: "action.hover" },
                            "&:focus-visible": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 2 },
                          }}
                        >
                          <Stack direction="row" justifyContent="space-between" gap={1}>
                            <Typography sx={{ fontWeight: 700 }}>{displayValue(candidate.version, "?")}</Typography>
                            <StatusTag value={candidate.status || (candidate.stale ? "stale" : "pending review")} />
                          </Stack>
                          <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: 13 }}>
                            {displayValue(candidateLabels?.length, "Not recorded")} labels ·{" "}
                            {displayValue(candidateMappings?.length, "Not recorded")} mappings
                          </Typography>
                          <Typography sx={{ mt: 0.6, color: "text.secondary", fontSize: 12, overflowWrap: "anywhere" }}>
                            Hash {displayValue(candidateHash(candidate), "Not recorded")}
                          </Typography>
                          <Typography color="primary.main" sx={{ mt: 1, fontSize: 12.5, fontWeight: 600 }}>
                            Review candidate →
                          </Typography>
                        </Paper>
                      </Grid>
                    );
                  })}
                </Grid>
              ) : (
                <Typography color="text.secondary">No candidates to review.</Typography>
              )}
            </Panel>
          </Stack>
        </Grid>
      </Grid>
      <Dialog open={candidateOpen} onClose={() => !busy && setCandidateOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Build a taxonomy candidate</DialogTitle>
        <DialogContent>
          <Stack gap={1.8} sx={{ pt: 1 }}>
            <Alert severity="info">
              Candidate creation never publishes a release. An admin must review and approve the exact candidate
              afterward.
            </Alert>
            <RadioGroup
              value={candidateMode}
              onChange={event => {
                setCandidateMode(event.target.value as "deterministic" | "model");
                setBudgetConfirmed(false);
              }}
            >
              <Paper variant="outlined" sx={{ p: 1.2, borderRadius: 2, mb: 1 }}>
                <FormControlLabel
                  value="deterministic"
                  control={<Radio />}
                  label="Assemble without model (no charge)"
                />
                <Typography color="text.secondary" sx={{ pl: 4.5, mt: -0.4, fontSize: 13 }}>
                  Build a candidate from the proposals and base release without a provider call. Near-duplicate labels
                  are not merged automatically.
                </Typography>
              </Paper>
              <Paper variant="outlined" sx={{ p: 1.2, borderRadius: 2 }}>
                <FormControlLabel
                  value="model"
                  control={<Radio />}
                  disabled={!usablePresets.length}
                  label="Ask model to consolidate"
                />
                <Typography color="text.secondary" sx={{ pl: 4.5, mt: -0.4, fontSize: 13 }}>
                  Makes one bounded API curation request with a pinned preset revision. Any returned candidate still
                  needs human review.
                </Typography>
              </Paper>
            </RadioGroup>
            {(!apiProviderReady || providers.error) && (
              <Alert severity="warning">
                Hosted taxonomy curation is unavailable because no configured, enabled LiteLLM API provider was
                reported. No request will be sent. Enable hosted inference and configure a provider to use model
                curation.
              </Alert>
            )}
            {presets.error && (
              <Alert severity="warning">
                Could not load preset revisions: {presets.error}. The no-charge option remains available.
              </Alert>
            )}
            {!presets.loading && !presets.error && apiProviderReady && !eligiblePresets.length && (
              <Alert severity="warning">
                Create an immutable Model API or LiteLLM preset revision with a budget from $0.01 to $5.00 to enable
                one-shot curation. The no-charge option remains available.
              </Alert>
            )}
            {presets.loading && (
              <Typography color="text.secondary" sx={{ fontSize: 13 }}>
                Checking configured API preset revisions…
              </Typography>
            )}
            {candidateMode === "model" && !!usablePresets.length && (
              <>
                <FormControl fullWidth size="small">
                  <Typography id="taxonomy-preset-label" sx={{ mb: 0.7, fontSize: 13, fontWeight: 700 }}>
                    Pinned curation preset revision
                  </Typography>
                  <Select
                    labelId="taxonomy-preset-label"
                    value={selectedPreset?.revisionId || ""}
                    onChange={event => {
                      setPresetRevisionId(String(event.target.value));
                      setBudgetConfirmed(false);
                    }}
                  >
                    {usablePresets.map(item => (
                      <MenuItem key={item.revisionId} value={item.revisionId}>
                        {item.preset.name} · {String(item.revision.backend || item.preset.backend)} ·{" "}
                        {String(item.revision.model || item.preset.model)} · cap ${item.budget.toFixed(2)}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                {selectedPreset && (
                  <>
                    <Alert severity="warning">
                      This will send one taxonomy curation request. The pinned maximum is $
                      {selectedPreset.budget.toFixed(2)} USD. Actual cost can be lower or reported as unknown. No
                      request runs until you confirm below and choose the send button.
                    </Alert>
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={budgetConfirmed}
                          onChange={event => setBudgetConfirmed(event.target.checked)}
                        />
                      }
                      label={`I confirm one curation request with a maximum budget of $${selectedPreset.budget.toFixed(2)} USD.`}
                    />
                  </>
                )}
              </>
            )}
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setCandidateOpen(false)} disabled={busy}>
            Cancel
          </Button>
          {candidateMode === "deterministic" ? (
            <Button variant="contained" onClick={() => void consolidate()} disabled={busy}>
              {busy ? "Building…" : "Build no-charge candidate"}
            </Button>
          ) : (
            <Button
              variant="contained"
              onClick={() => void consolidate()}
              disabled={busy || !selectedPreset || !budgetConfirmed}
            >
              {busy ? "Requesting…" : "Send one curation request"}
            </Button>
          )}
        </DialogActions>
      </Dialog>
      <Dialog open={proposalOpen} onClose={() => !busy && setProposalOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>Propose a taxonomy change</DialogTitle>
        <DialogContent>
          <Stack gap={2} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <Alert severity="info">Submitting a proposal never publishes it. Approved releases are immutable.</Alert>
            <TextField
              autoFocus
              required
              label="Label name"
              value={name}
              onChange={event => setName(event.target.value)}
            />
            <TextField
              required
              label="Definition"
              value={description}
              onChange={event => setDescription(event.target.value)}
              multiline
              minRows={3}
            />
            <TextField label="Change kind" select value={kind} onChange={event => setKind(String(event.target.value))}>
              <MenuItem value="label">New label proposal</MenuItem>
              <MenuItem value="edit">Edit existing label</MenuItem>
              <MenuItem value="merge">Merge suggestion</MenuItem>
              <MenuItem value="retire">Retirement suggestion</MenuItem>
            </TextField>
            {kind !== "label" && (
              <TextField
                label="Target label ID"
                value={labelId}
                onChange={event => setLabelId(event.target.value)}
                helperText="Changes append a draft revision. Approved releases remain unchanged."
              />
            )}
            <TextField
              label="Evidence references"
              value={evidenceText}
              onChange={event => setEvidenceText(event.target.value)}
              multiline
              minRows={2}
              helperText="One reference per line or comma-separated. These are identifiers, not uploaded paths."
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setProposalOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={submitProposal} disabled={busy || !name.trim() || !description.trim()}>
            Append proposal
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

function ProposalCard({
  proposal,
  labels,
  disabled,
  onFeedback,
}: {
  proposal: Record<string, unknown>;
  labels: Record<string, unknown>[];
  disabled: boolean;
  onFeedback: (id: string, text: string, clear: () => void) => void;
}) {
  const [feedback, setFeedback] = useState("");
  const id = String(proposal.id || proposal.proposal_id || "");
  const latest = (proposal.latest_revision || {}) as Record<string, unknown>;
  const exactRevisionHash = latest.content_hash ?? proposal.content_hash;
  const target = labels.find(label => String(label.id) === String(proposal.label_id));
  const history = Array.isArray(proposal.revisions)
    ? (proposal.revisions as Record<string, unknown>[])
    : latest.id
      ? [latest]
      : [];
  const feedbackHistory = Array.isArray(proposal.feedback) ? (proposal.feedback as Record<string, unknown>[]) : [];
  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2.2 }}>
      <Stack direction="row" justifyContent="space-between" gap={1} alignItems="flex-start">
        <Box>
          <Typography sx={{ fontWeight: 750 }}>{String(proposal.name || latest.name || "Unnamed proposal")}</Typography>
          <Typography color="text.secondary" sx={{ fontSize: 12 }}>
            {id} · {String(proposal.kind || "proposal")} · {target ? `Targets ${target.id}` : "New category"}
          </Typography>
        </Box>
        <StatusTag value={proposal.status || "draft"} />
      </Stack>
      <Typography sx={{ mt: 1, fontSize: 14 }}>
        {displayValue(proposal.description ?? latest.description, "No definition recorded.")}
      </Typography>
      <Typography
        color="text.secondary"
        sx={{ mt: 0.5, fontFamily: "monospace", fontSize: 12, overflowWrap: "anywhere" }}
      >
        Latest revision content hash: {displayValue(exactRevisionHash, "Not recorded")}
      </Typography>
      {!!(proposal.evidence_refs || latest.evidence_refs) && (
        <Typography color="text.secondary" sx={{ mt: 0.7, fontSize: 12.5 }}>
          Evidence: {displayValue(proposal.evidence_refs ?? latest.evidence_refs)}
        </Typography>
      )}
      {!!history.length && (
        <Box component="details" sx={{ mt: 0.8 }}>
          <Box component="summary" sx={{ cursor: "pointer", color: "primary.main", fontWeight: 650, fontSize: 13 }}>
            Revision history · {history.length}
          </Box>
          <Stack gap={0.5} sx={{ mt: 0.7 }}>
            {history.map((revision, i) => (
              <Box key={String(revision.id || i)}>
                <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                  Revision {String(revision.revision ?? i + 1)} · {formatDate(revision.created_at)} ·{" "}
                  {displayValue(revision.change_summary || revision.description)}
                </Typography>
                <Typography
                  color="text.secondary"
                  sx={{ fontFamily: "monospace", fontSize: 11.5, overflowWrap: "anywhere" }}
                >
                  Content hash: {displayValue(revision.content_hash, "Not recorded")}
                </Typography>
              </Box>
            ))}
          </Stack>
        </Box>
      )}
      {!!feedbackHistory.length && (
        <Box sx={{ mt: 1 }}>
          <Typography sx={{ fontSize: 12.5, fontWeight: 700 }}>Curator feedback</Typography>
          {feedbackHistory.map((entry, index) => (
            <Typography key={String(entry.id || index)} color="text.secondary" sx={{ mt: 0.3, fontSize: 12.5 }}>
              {displayValue(entry.text)} · {formatDate(entry.created_at)}
            </Typography>
          ))}
        </Box>
      )}
      <Stack direction={{ xs: "column", sm: "row" }} gap={1} sx={{ mt: 1.3 }}>
        <TextField
          fullWidth
          size="small"
          label="Add curator feedback"
          value={feedback}
          onChange={event => setFeedback(event.target.value)}
        />
        <Button
          variant="outlined"
          sx={{ whiteSpace: "nowrap", flexShrink: 0 }}
          disabled={disabled || !feedback.trim()}
          onClick={() => onFeedback(id, feedback, () => setFeedback(""))}
        >
          Append feedback
        </Button>
      </Stack>
    </Paper>
  );
}

interface CandidateData extends TaxonomyData {
  candidate?: Record<string, unknown>;
}
export function CandidatePage() {
  const { id = "" } = useParams();
  const state = useApi<CandidateData>("/taxonomy");
  const navigate = useNavigate();
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const candidate = state.data?.candidate || state.data?.candidates?.find(item => String(item.id) === id);
  const approve = async () => {
    if (!candidate) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/taxonomy/candidates/${encodeURIComponent(id)}/approve`, {
        method: "POST",
        body: JSON.stringify({ expected_hash: candidateHash(candidate), version: candidate.version }),
      });
      setApproveOpen(false);
      navigate("/taxonomy");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Candidate approval failed.");
    } finally {
      setBusy(false);
    }
  };
  const reject = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/taxonomy/candidates/${encodeURIComponent(id)}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      setRejectOpen(false);
      navigate("/taxonomy");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Candidate rejection failed.");
    } finally {
      setBusy(false);
    }
  };
  if (state.loading) return <LoadingState label="Loading exact taxonomy candidate…" />;
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (!candidate)
    return (
      <EmptyState
        title="Candidate not found"
        description="This candidate may have been replaced or you may not have access."
      />
    );
  const stale = Boolean(candidate.stale) || String(candidate.status).toLowerCase() === "stale";
  const candidateContent = (candidate.content || {}) as Record<string, unknown>;
  const candidateLabels = Array.isArray(candidate.labels)
    ? (candidate.labels as Record<string, unknown>[])
    : Array.isArray(candidateContent.labels)
      ? (candidateContent.labels as Record<string, unknown>[])
      : [];
  const mappings = Array.isArray(candidate.mappings)
    ? (candidate.mappings as Record<string, unknown>[])
    : Array.isArray(candidateContent.mappings)
      ? (candidateContent.mappings as Record<string, unknown>[])
      : [];
  const unresolvedItems = Array.isArray(candidate.unresolved)
    ? (candidate.unresolved as unknown[])
    : Array.isArray(candidateContent.unresolved)
      ? (candidateContent.unresolved as unknown[])
      : [];
  const exactCandidateHash = candidateHash(candidate);
  const base = candidate.base_release_id;
  return (
    <>
      <PageHeader
        eyebrow="TAXONOMY CANDIDATE"
        title={`${displayValue(candidate.version, "?")}`}
        description="This page reviews an immutable candidate snapshot. Approve publishes only the exact hash shown and its base release."
        action={
          <Stack direction={{ xs: "column", sm: "row" }} gap={1} flexWrap="wrap">
            <Button
              color="error"
              variant="outlined"
              disabled={busy || candidate.status === "approved" || candidate.status === "rejected"}
              onClick={() => {
                setError("");
                setRejectOpen(true);
              }}
            >
              Reject
            </Button>
            <Button
              variant="contained"
              disabled={
                busy ||
                stale ||
                candidate.status === "approved" ||
                candidate.status === "rejected" ||
                !exactCandidateHash
              }
              onClick={() => {
                setError("");
                setApproveOpen(true);
              }}
            >
              Approve exact version
            </Button>
          </Stack>
        }
      />
      {error && (
        <Alert severity="error" onClose={() => setError("")} sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      {stale && (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          This candidate is stale against its base or draft revisions. Rebuild it before approval.
        </Alert>
      )}
      <Panel sx={{ mb: 2 }}>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 3 }}>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              Candidate status
            </Typography>
            <StatusTag value={candidate.status || "pending review"} />
          </Grid>
          <Grid size={{ xs: 12, md: 3 }}>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              Base release
            </Typography>
            <Typography sx={{ fontWeight: 750 }}>{displayValue(base)}</Typography>
          </Grid>
          <Grid size={{ xs: 12, md: 3 }}>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              Version
            </Typography>
            <Typography sx={{ fontWeight: 750 }}>{displayValue(candidate.version)}</Typography>
          </Grid>
          <Grid size={{ xs: 12, md: 3 }}>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              Exact candidate hash
            </Typography>
            <Typography sx={{ mt: 0.2, fontFamily: "monospace", fontSize: 13, overflowWrap: "anywhere" }}>
              {displayValue(exactCandidateHash, "Not recorded")}
            </Typography>
          </Grid>
        </Grid>
      </Panel>
      <Grid container spacing={2} alignItems="flex-start">
        <Grid size={{ xs: 12, lg: 7 }}>
          <Panel>
            <SectionTitle
              title="Definitions in this candidate"
              subtitle={`${candidateLabels.length} labels; definitions and lineage are part of the published snapshot.`}
            />
            {candidateLabels.length ? (
              <Stack gap={1}>
                {candidateLabels.map((label, index) => (
                  <Paper key={String(label.id || index)} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      gap={0.5}
                      alignItems={{ sm: "baseline" }}
                      sx={{ overflowWrap: "anywhere" }}
                    >
                      <Typography sx={{ fontWeight: 750 }}>{displayValue(label.name)}</Typography>
                      <Typography color="text.secondary" sx={{ fontFamily: "monospace", fontSize: 12 }}>
                        {displayValue(label.id)}
                      </Typography>
                      <StatusTag value={label.status || "draft"} />
                    </Stack>
                    <Typography sx={{ mt: 0.6, fontSize: 14 }}>
                      {displayValue(label.description, "No definition recorded.")}
                    </Typography>
                    {Array.isArray(label.examples) && !!label.examples.length && (
                      <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: 13 }}>
                        Examples: {displayValue(label.examples)}
                      </Typography>
                    )}
                  </Paper>
                ))}
              </Stack>
            ) : (
              <Typography color="text.secondary">This candidate contains no labels.</Typography>
            )}
          </Panel>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Stack gap={2}>
            <Panel>
              <SectionTitle title="Mappings and rationale" />
              {mappings.length ? (
                <Stack gap={1}>
                  {mappings.map((mapping, index) => (
                    <Paper key={String(mapping.id || index)} variant="outlined" sx={{ p: 1.3, borderRadius: 2 }}>
                      <Typography sx={{ fontWeight: 700, fontSize: 14 }}>
                        {displayValue(mapping.from || mapping.proposal_id)} →{" "}
                        {displayValue(mapping.to || mapping.canonical_label_id)}
                      </Typography>
                      <Typography color="text.secondary" sx={{ mt: 0.4, fontSize: 13 }}>
                        {displayValue(mapping.rationale, "No rationale recorded.")}
                      </Typography>
                    </Paper>
                  ))}
                </Stack>
              ) : (
                <Typography color="text.secondary">No mappings recorded.</Typography>
              )}
            </Panel>
            <Panel>
              <SectionTitle title="Unresolved items" />
              {unresolvedItems.length ? (
                <Stack gap={0.8}>
                  {unresolvedItems.map((item, index) => (
                    <Typography key={index} color="text.secondary">
                      • {displayValue(item)}
                    </Typography>
                  ))}
                </Stack>
              ) : (
                <Typography color="text.secondary">No unresolved items recorded.</Typography>
              )}
            </Panel>
            <Panel>
              <SectionTitle title="Candidate content" />
              <Typography color="text.secondary" sx={{ mb: 0.8, fontSize: 13 }}>
                The exact stored snapshot used for approval.
              </Typography>
              <Box
                component="pre"
                sx={{
                  maxHeight: 330,
                  overflow: "auto",
                  p: 1.4,
                  bgcolor: "action.hover",
                  color: "text.primary",
                  borderRadius: 2,
                  fontSize: 12,
                }}
              >
                {JSON.stringify(candidate, null, 2)}
              </Box>
            </Panel>
          </Stack>
        </Grid>
      </Grid>
      <Dialog open={approveOpen} onClose={() => setApproveOpen(false)}>
        <DialogTitle>Approve this exact candidate?</DialogTitle>
        <DialogContent>
          <Stack gap={1.5} sx={{ pt: 1 }}>
            <Alert severity="warning">
              Approval publishes a new immutable release from {String(candidate.version)}. Exact candidate hash:{" "}
              {String(exactCandidateHash)}. Existing releases and pinned runs remain unchanged.
            </Alert>
            <Typography>
              Continue only if the definitions, mappings, unresolved items, and base release are correct.
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setApproveOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={approve}>
            Publish exact candidate
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={rejectOpen} onClose={() => setRejectOpen(false)}>
        <DialogTitle>Reject candidate</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={3}
            label="Reason"
            value={reason}
            onChange={event => setReason(event.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" disabled={busy || !reason.trim()} onClick={reject}>
            Record rejection
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
