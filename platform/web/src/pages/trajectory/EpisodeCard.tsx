import { Box, Chip, Paper, Stack, Typography } from "@mui/material";
import type { Episode, TaskRecord, TrajectoryStep } from "../../api/types";
import { StatusTag } from "../../components/StatusTag";
import { asRecord } from "../../lib/records";
import { LabelChip } from "./LabelChip";
import {
  type AnyRecord,
  getEpisodeId,
  idOf,
  labelDefinitionText,
  recoveryIds,
  refsWithRole,
  relatedIds,
  resolveEpisodeLabel,
  stepId,
  stepRefs,
  text,
} from "./trajectoryModel";
export function EpisodeCard({
  episode,
  index,
  steps,
  review,
  labels,
  proposals,
  onStep,
}: {
  episode: Episode;
  index: number;
  steps: TrajectoryStep[];
  review?: TaskRecord["review"];
  labels: AnyRecord[];
  proposals: AnyRecord[];
  onStep: (id: string) => void;
}) {
  const id = getEpisodeId(episode);
  const observedAnchor =
    String(review?.schema_version) === "2" &&
    episode.first_observed_step_id !== undefined &&
    episode.first_observed_step_id !== null;
  const onset = stepRefs(episode.onset_step_ids);
  const explicitAnchor = observedAnchor ? idOf(episode.first_observed_step_id) : "";
  const anchorId =
    explicitAnchor ||
    onset.slice().sort((a, b) => {
      const ai = steps.findIndex(step => stepId(step) === a);
      const bi = steps.findIndex(step => stepId(step) === b);
      return ai < 0 ? (bi < 0 ? 0 : 1) : bi < 0 ? -1 : ai - bi;
    })[0] ||
    "";
  const recovery = recoveryIds(episode);
  const explicitlyRelated = relatedIds(episode);
  const onsetSet = new Set(onset);
  const recoverySet = new Set(recovery);
  const relatedFromLinks = steps
    .filter(step => {
      if (!refsWithRole(step.episode_refs).some(ref => ref.episodeId === id)) return false;
      const linkedStep = stepId(step);
      const explicitRole = refsWithRole(step.episode_refs).find(ref => ref.episodeId === id)?.role;
      return (
        explicitRole === "related" ||
        (!onsetSet.has(linkedStep) && !recoverySet.has(linkedStep) && linkedStep !== anchorId)
      );
    })
    .map(stepId);
  const related = [...new Set([...explicitlyRelated, ...relatedFromLinks])];
  const resolvedLabel = resolveEpisodeLabel(episode, labels, proposals);
  const recordedLabel = resolvedLabel.rawName;
  return (
    <Paper variant="outlined" sx={{ p: 1.1, borderRadius: 2 }}>
      <Stack direction="row" justifyContent="space-between" gap={0.6} alignItems="flex-start">
        <Typography sx={{ fontWeight: 750, fontSize: 13.5 }}>
          Problem {Number(episode.problem_number) || index + 1}
        </Typography>
        <StatusTag value={episode.outcome_contribution} />
      </Stack>
      <Box sx={{ mt: 0.6 }}>
        <LabelChip id={resolvedLabel.id} label={resolvedLabel.displayName} />
      </Box>
      <Typography color="text.secondary" sx={{ mt: 0.6, fontSize: 13 }}>
        {labelDefinitionText(resolvedLabel)}
      </Typography>
      <Box component="details" sx={{ mt: 0.4 }}>
        <Box component="summary" sx={{ cursor: "pointer", color: "primary.main", fontSize: 12.5, fontWeight: 650 }}>
          Recorded label
        </Box>
        <Typography color="text.secondary" sx={{ mt: 0.3, fontSize: 12 }}>
          Name: {recordedLabel}
          {episode.label_id ? ` · ID: ${episode.label_id}` : " · ID: Not recorded"}
        </Typography>
      </Box>
      <Typography color="text.secondary" sx={{ mt: 0.45, fontSize: 13, whiteSpace: "pre-wrap" }}>
        {text(episode.mechanism, "Problem description not recorded.")}
      </Typography>
      <Stack gap={0.65} sx={{ mt: 0.9 }}>
        {!!(onset.length || anchorId) && (
          <Stack direction="row" gap={0.45} flexWrap="wrap">
            <StepJumpChip
              label={observedAnchor ? "First observed here" : "First flagged here"}
              id={anchorId}
              missing={!steps.some(step => stepId(step) === anchorId)}
              onClick={onStep}
            />
            <>
              {onset
                .filter(step => step !== anchorId)
                .map((step, i) => (
                  <StepJumpChip
                    key={`onset-${step}-${i}`}
                    label={observedAnchor ? "Also observed here" : "Also flagged here"}
                    id={step}
                    missing={!steps.some(item => stepId(item) === step)}
                    onClick={onStep}
                  />
                ))}
            </>
          </Stack>
        )}
        {!!recovery.length && (
          <Box>
            <Stack direction="row" gap={0.45} alignItems="center" flexWrap="wrap">
              <Typography color="success.dark" sx={{ fontSize: 12.5, fontWeight: 700 }}>
                Recovery steps
              </Typography>
              <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>
                First anchor:
              </Typography>
              <StepJumpChip
                label="Step"
                id={anchorId}
                missing={!steps.some(item => stepId(item) === anchorId)}
                onClick={onStep}
              />
            </Stack>
            <Stack direction="row" gap={0.45} flexWrap="wrap" sx={{ mt: 0.35 }}>
              {recovery.map((step, i) => (
                <StepJumpChip
                  key={`recovery-${step}-${i}`}
                  label="Recovery"
                  id={step}
                  missing={!steps.some(item => stepId(item) === step)}
                  onClick={onStep}
                  tone="success"
                />
              ))}
            </Stack>
          </Box>
        )}
        {!!related.length && (
          <Box component="details">
            <Box component="summary" sx={{ cursor: "pointer", color: "primary.main", fontSize: 12.5, fontWeight: 650 }}>
              Related steps · {related.length}
            </Box>
            <Stack direction="row" gap={0.45} flexWrap="wrap" sx={{ mt: 0.4 }}>
              <Typography color="text.secondary" sx={{ fontSize: 12.5, alignSelf: "center" }}>
                First anchor:
              </Typography>
              <StepJumpChip
                label="Step"
                id={anchorId}
                missing={!steps.some(item => stepId(item) === anchorId)}
                onClick={onStep}
              />
              {related.map((step, i) => (
                <StepJumpChip
                  key={`related-${step}-${i}`}
                  label="Related"
                  id={step}
                  missing={!steps.some(item => stepId(item) === step)}
                  onClick={onStep}
                />
              ))}
            </Stack>
          </Box>
        )}
        {!anchorId && !onset.length && !recovery.length && !related.length && (
          <Typography color="text.secondary" sx={{ fontSize: 13 }}>
            No exact step links recorded.
          </Typography>
        )}
      </Stack>
      <Typography color="text.secondary" sx={{ display: "block", mt: 0.8, fontSize: 12 }}>
        Recovery: {text(asRecord(episode.recovery).status, "Not recorded")}
        {asRecord(episode.recovery).rationale ? ` · ${text(asRecord(episode.recovery).rationale)}` : ""}
      </Typography>
      {episode.uncertainty && (
        <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: 12 }}>
          Uncertainty: {text(episode.uncertainty)}
        </Typography>
      )}
    </Paper>
  );
}

function StepJumpChip({
  label,
  id,
  missing,
  onClick,
  tone,
}: {
  label: string;
  id: string;
  missing: boolean;
  onClick: (id: string) => void;
  tone?: "success";
}) {
  if (!id)
    return <Chip size="small" variant="outlined" disabled label={`${label}: Not recorded`} sx={{ fontSize: 12 }} />;
  return (
    <Chip
      size="small"
      component="button"
      clickable={!missing}
      disabled={missing}
      color={missing ? "error" : tone}
      variant="outlined"
      label={missing ? `Step ${id} unavailable` : `${label} · ${id}`}
      onClick={() => !missing && onClick(id)}
      sx={{ fontSize: 12, fontWeight: 650 }}
    />
  );
}
