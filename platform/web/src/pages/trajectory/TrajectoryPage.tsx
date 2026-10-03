import { useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  Collapse,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  InputAdornment,
  Link,
  Paper,
  Stack,
  TextField,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import FormatListNumberedRounded from "@mui/icons-material/FormatListNumberedRounded";
import ArrowBackRounded from "@mui/icons-material/ArrowBackRounded";
import ArrowForwardRounded from "@mui/icons-material/ArrowForwardRounded";
import ExpandLessRounded from "@mui/icons-material/ExpandLessRounded";
import ExpandMoreRounded from "@mui/icons-material/ExpandMoreRounded";
import SearchRounded from "@mui/icons-material/SearchRounded";
import CloseRounded from "@mui/icons-material/CloseRounded";
import OpenInNewRounded from "@mui/icons-material/OpenInNewRounded";
import { apiRequest } from "../../api/client";
import { RUN_TASK_PAGING } from "../../api/pagination";
import type { BatchRecord, ReviewEvidenceProvenance, TaskRecord } from "../../api/types";
import { BenchmarkResult } from "../../components/BenchmarkResult";
import { PageBreadcrumbs, PageHeader, Panel, SectionTitle } from "../../components/Page";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { StatusTag } from "../../components/StatusTag";
import { StepFlag } from "../../components/StepFlag";
import { useApi } from "../../hooks/useApi";
import { formatDate, reviewProcessingError } from "../../lib/format";
import { asRecord } from "../../lib/records";
import { EpisodeCard } from "./EpisodeCard";
import { LabelChip } from "./LabelChip";
import {
  type AnyRecord,
  type BatchTaskRow,
  displayedLabel,
  episodesOf,
  firstProblemAnchor,
  getEpisodeId,
  idOf,
  labelDefinitionText,
  labelFor,
  outcomeLabel,
  resolveEpisodeLabel,
  reviewAssessmentLabel,
  reviewFor,
  reviewProcessingLabel,
  roleBadgeLabel,
  rolesForStep,
  stepId,
  stepRefs,
  stepsOf,
  taskKey,
  taskOutcome,
  taskProblemLinks,
  taskSummary,
  text,
  type TrajectoryResponse,
} from "./trajectoryModel";

export function TrajectoryPage() {
  const { id: batchId = "", taskId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const memberId = searchParams.get("member_id") || "";
  const requestedStepId = searchParams.get("step_id") || "";
  const batch = useApi<{ run?: BatchRecord; batch?: BatchRecord }>(
    batchId ? `/runs/${encodeURIComponent(batchId)}` : null,
  );
  const taxonomyState = useApi<{ releases?: AnyRecord[]; labels?: AnyRecord[]; proposals?: AnyRecord[] }>("/taxonomy");
  const tasksState = useApi<{ items?: BatchTaskRow[]; total?: number } | BatchTaskRow[]>(
    batchId ? `/runs/${encodeURIComponent(batchId)}/tasks` : null,
    0,
    RUN_TASK_PAGING,
  );
  const memberQuery = memberId ? `?member_id=${encodeURIComponent(memberId)}` : "";
  const detailState = useApi<TrajectoryResponse>(
    batchId && taskId ? `/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(taskId)}${memberQuery}` : null,
  );
  const tasks = Array.isArray(tasksState.data) ? tasksState.data : tasksState.data?.items || [];
  const response = detailState.data;
  const member = response?.member;
  const directTask =
    response && typeof response.task_id === "string" && Array.isArray(response.steps)
      ? (response as TaskRecord)
      : undefined;
  const task = response?.task || member?.task || (member && member.steps ? member : undefined) || directTask;
  const review = response?.review || task?.review || member?.review || directTask?.review;
  const normalizedTask: TaskRecord | undefined = task
    ? { ...task, task_id: taskKey(task) || taskId, review: review || task.review }
    : undefined;
  const batchRecord = batch.data?.run || batch.data?.batch || (batch.data as BatchRecord | null);
  const sourceDatasets = Array.isArray((batch.data as AnyRecord | null)?.source_datasets)
    ? ((batch.data as AnyRecord).source_datasets as AnyRecord[])
    : [];
  const datasetId = String(
    normalizedTask?.dataset_id ||
      asRecord(normalizedTask?.source).dataset_id ||
      sourceDatasets[0]?.id ||
      sourceDatasets[0]?.dataset_id ||
      batchRecord?.dataset_id ||
      "",
  );
  // The run already lists its source datasets by name; only fetch when that name is unknown, since
  // run-only access does not include reading the source dataset itself.
  const knownSource = sourceDatasets.find(item => String(item.id || item.dataset_id || "") === datasetId);
  const datasetState = useApi<{ dataset?: AnyRecord }>(
    datasetId && batch.data && !knownSource?.name ? `/datasets/${encodeURIComponent(datasetId)}` : null,
  );
  const selectedMemberId = memberId || idOf(normalizedTask?.member_id || member?.id);
  const selectedMemberQuery = selectedMemberId ? `?member_id=${encodeURIComponent(selectedMemberId)}` : "";
  const steps = useMemo(() => stepsOf(normalizedTask), [normalizedTask]);
  const episodes = useMemo(() => episodesOf(review), [review]);
  const [stepIndex, setStepIndex] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [stepPickerOpen, setStepPickerOpen] = useState(false);
  const theme = useTheme();
  const compactSteps = useMediaQuery(theme.breakpoints.down("lg"));
  const [taskPickerOpen, setTaskPickerOpen] = useState(false);
  const [taskSearch, setTaskSearch] = useState("");
  const [feedbackText, setFeedbackText] = useState("");
  const [feedback, setFeedback] = useState<AnyRecord[]>([]);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackError, setFeedbackError] = useState("");
  const [feedbackNotice, setFeedbackNotice] = useState("");
  const [screenshotLoadFailed, setScreenshotLoadFailed] = useState(false);
  const screenshotRef = useRef<HTMLDivElement>(null);
  const stepListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setStepIndex(0);
  }, [taskId, memberId]);
  useEffect(() => {
    if (detailState.loading) return;
    const index = requestedStepId ? steps.findIndex(step => stepId(step) === requestedStepId) : -1;
    setStepIndex(index >= 0 ? index : 0);
  }, [detailState.loading, requestedStepId, steps]);
  useEffect(() => {
    setFeedback(Array.isArray(response?.feedback) ? response.feedback : []);
  }, [response?.feedback, taskId, memberId]);
  useEffect(() => {
    if (detailState.loading) return;
    requestAnimationFrame(() => screenshotRef.current?.scrollIntoView({ block: "start" }));
  }, [taskId, memberId, detailState.loading]);
  const selectedStep = steps[stepIndex];
  const selectedStepId = selectedStep ? stepId(selectedStep) : "";
  useEffect(() => {
    if (selectedStepId) requestAnimationFrame(() => screenshotRef.current?.scrollIntoView({ block: "start" }));
  }, [selectedStepId]);
  useEffect(() => {
    setScreenshotLoadFailed(false);
  }, [selectedStepId]);
  useEffect(() => {
    if (stepPickerOpen)
      requestAnimationFrame(() =>
        stepListRef.current?.querySelector<HTMLElement>('[aria-current="step"]')?.scrollIntoView({ block: "center" }),
      );
  }, [stepPickerOpen]);
  const currentTask = normalizedTask;
  const reviewProvenance =
    response?.review_provenance ||
    currentTask?.review_provenance ||
    member?.review_provenance ||
    (Array.isArray(response?.review_history)
      ? (asRecord(response.review_history.at(-1)?.provenance) as ReviewEvidenceProvenance)
      : undefined);
  const currentJobs = Array.isArray(currentTask?.jobs) ? currentTask.jobs : [];
  const failedJob = [...currentJobs]
    .reverse()
    .find(job => String(job.status || "").toLowerCase() === "failed" || Boolean(job.error));
  const failureJobId = idOf(failedJob?.job_id || failedJob?.id || currentTask?.job_id);
  const reviewProcessingStatus = currentTask ? reviewProcessingLabel(currentTask) : "Review processing: not recorded";
  const reviewAssessmentStatus = currentTask ? reviewAssessmentLabel(currentTask, review) : "Not recorded";
  const summary = currentTask ? taskSummary(currentTask) : undefined;
  const filteredTasks = useMemo(() => {
    const query = taskSearch.trim().toLowerCase();
    if (!query) return tasks;
    return tasks.filter(row => {
      const review = reviewFor(row);
      const searchable = [
        row.title,
        row.task_id,
        row.instruction,
        ...episodesOf(review).flatMap(episode => [labelFor(episode), displayedLabel(labelFor(episode))]),
      ].map(value => String(value || "").toLowerCase());
      return searchable.some(value => value.includes(query));
    });
  }, [tasks, taskSearch]);
  const currentTaskIndex = tasks.findIndex(
    row => taskKey(row) === taskId && (!selectedMemberId || idOf(row.member_id) === selectedMemberId),
  );
  const moveToTask = (nextTaskId: string, nextStepId = "", nextMemberId = "") => {
    if (!nextTaskId) return;
    setTaskPickerOpen(false);
    setStepPickerOpen(false);
    const query = new URLSearchParams();
    if (nextMemberId) query.set("member_id", nextMemberId);
    if (nextStepId) query.set("step_id", nextStepId);
    navigate(
      `/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(nextTaskId)}${query.size ? `?${query.toString()}` : ""}`,
    );
  };
  const alignScreenshot = () => screenshotRef.current?.scrollIntoView({ block: "start" });
  const changeStep = (nextIndex: number) => {
    const boundedIndex = Math.max(0, Math.min(steps.length - 1, nextIndex));
    setStepIndex(boundedIndex);
    setStepPickerOpen(false);
    const nextId = steps[boundedIndex] ? stepId(steps[boundedIndex]) : "";
    const nextParams = new URLSearchParams(searchParams);
    if (selectedMemberId) nextParams.set("member_id", selectedMemberId);
    if (nextId) nextParams.set("step_id", nextId);
    else nextParams.delete("step_id");
    setSearchParams(nextParams, { replace: true });
    requestAnimationFrame(alignScreenshot);
  };
  const stepById = (id: string) => {
    const found = steps.findIndex(step => stepId(step) === id);
    if (found >= 0) changeStep(found);
  };
  const submitFeedback = async () => {
    if (!feedbackText.trim() || !taskId) return;
    setFeedbackBusy(true);
    setFeedbackError("");
    setFeedbackNotice("");
    try {
      const created = await apiRequest<AnyRecord>(
        `/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(taskId)}/feedback${selectedMemberQuery}`,
        {
          method: "POST",
          body: JSON.stringify({ text: feedbackText.trim(), ...(selectedStepId ? { step_id: selectedStepId } : {}) }),
        },
      );
      setFeedback(current => [
        ...current,
        created.feedback && typeof created.feedback === "object" ? (created.feedback as AnyRecord) : created,
      ]);
      setFeedbackText("");
      setFeedbackNotice("Feedback recorded.");
    } catch (reason) {
      setFeedbackError(reason instanceof Error ? reason.message : "Feedback could not be recorded.");
    } finally {
      setFeedbackBusy(false);
    }
  };
  const selectedReviewStep = (review?.steps || []).find(item => idOf(item.step_id) === selectedStepId);
  const provenance = asRecord(reviewProvenance);
  const suppliedImageIds = stepRefs(provenance.supplied_image_step_ids);
  const citedImageIds = stepRefs(provenance.cited_image_step_ids);
  const sourceImageIds = stepRefs(provenance.source_image_step_ids);
  const evidenceMode = String(provenance.evidence_mode || "");
  const deliveryRecorded = Array.isArray(provenance.supplied_image_step_ids) || evidenceMode === "text_only";
  const screenshotWasSent = suppliedImageIds.includes(selectedStepId);
  const screenshotCitationCount = citedImageIds.includes(selectedStepId) ? 1 : 0;
  const cannotConfirmFromEvidence =
    String(selectedReviewStep?.review_status || "").toLowerCase() === "insufficient_evidence";
  const stepRoles = selectedStepId ? rolesForStep(selectedStepId, steps, episodes, review) : [];
  const problemIdsAtSelectedStep = new Set(stepRoles.map(role => role.episodeId));
  const selectedProblemEpisodes = episodes.filter(episode => problemIdsAtSelectedStep.has(getEpisodeId(episode)));
  const screenshotUrl = selectedStep?.screenshot_url?.startsWith("/api/artifacts/")
    ? selectedStep.screenshot_url
    : undefined;
  const sourceScreenshotRecorded =
    selectedStep?.artifact_status === "missing" ||
    sourceImageIds.includes(selectedStepId) ||
    Boolean(selectedStep?.screenshot || selectedStep?.screenshot_path || selectedStep?.artifact_id || screenshotUrl);
  const sourceScreenshotAvailable =
    selectedStep?.artifact_status !== "missing" &&
    (sourceImageIds.includes(selectedStepId) ||
      Boolean(selectedStep?.screenshot || selectedStep?.screenshot_path || selectedStep?.artifact_id || screenshotUrl));
  const exportBase = `/api/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(taskId)}/export`;
  const exportHref = (format: "yaml" | "json") =>
    `${exportBase}?${new URLSearchParams({ format, ...(selectedMemberId ? { member_id: selectedMemberId } : {}) }).toString()}`;
  const recordedRawUrl = text(currentTask?.raw_url ?? member?.raw_url ?? response?.raw_url, "");

  if (batch.loading || tasksState.loading || detailState.loading)
    return <LoadingState label="Loading saved trajectory and review evidence…" />;
  if (batch.error) return <ErrorState message={batch.error} onRetry={batch.reload} />;
  if (tasksState.error) return <ErrorState message={tasksState.error} onRetry={tasksState.reload} />;
  if (detailState.error) return <ErrorState message={detailState.error} onRetry={detailState.reload} />;
  if (!currentTask)
    return (
      <EmptyState
        title="Task trajectory not found"
        description="This run task may no longer be available, or access may have changed."
        action={
          <Button component={RouterLink} to={`/runs/${encodeURIComponent(batchId)}`} variant="outlined">
            Back to run
          </Button>
        }
      />
    );
  const pinnedRelease = (batchRecord?.taxonomy_release ||
    taxonomyState.data?.releases?.find(item => String(item.id) === String(batchRecord?.taxonomy_release_id)) ||
    {}) as AnyRecord;
  const pinnedLabels = Array.isArray(pinnedRelease.labels)
    ? (pinnedRelease.labels as AnyRecord[])
    : Array.isArray(asRecord(pinnedRelease.content).labels)
      ? (asRecord(pinnedRelease.content).labels as AnyRecord[])
      : [];
  const draftProposals = taxonomyState.data?.proposals || [];

  const datasetRecord = datasetState.data?.dataset || (datasetState.data as AnyRecord | null);
  const datasetName = String(datasetRecord?.name || knownSource?.name || sourceDatasets[0]?.name || "Dataset");
  const sourceScreenshotMissing =
    selectedStep?.artifact_status === "missing" ||
    (!screenshotUrl && Boolean(selectedStep?.screenshot || selectedStep?.screenshot_path || selectedStep?.artifact_id));
  const screenshotMessage = screenshotUrl
    ? screenshotLoadFailed
      ? "Screenshot source exists, but it could not be loaded."
      : ""
    : sourceScreenshotAvailable
      ? "A source screenshot is available, but this review did not receive a viewer URL."
      : sourceScreenshotMissing
        ? "Screenshot file is missing from the saved source."
        : "No screenshot was recorded for this step.";

  const stepNavigator = (
    <>
      <Button
        fullWidth
        variant="outlined"
        startIcon={<SearchRounded />}
        onClick={() => setTaskPickerOpen(true)}
        sx={{ my: 1, justifyContent: "flex-start" }}
      >
        Search tasks in run
      </Button>
      <Stack direction="row" gap={0.6} flexWrap="wrap" sx={{ mb: 1.2 }}>
        <Chip size="small" label={`${summary?.problemCount ?? "Not recorded"} problems`} />
        <Chip size="small" label={`${summary?.flaggedCount ?? "Not recorded"} flagged steps`} />
        <Chip size="small" label={`${summary?.recoveryCount ?? "Not recorded"} recovery steps`} />
      </Stack>
      <Divider sx={{ mb: 1 }} />
      <Typography color="text.secondary" sx={{ px: 0.6, mb: 0.7, fontSize: 12.5, fontWeight: 700 }}>
        RECORDED STEPS
      </Typography>
      {!steps.length ? (
        <Typography color="text.secondary" sx={{ px: 0.6, py: 1, fontSize: 13 }}>
          No trajectory steps recorded.
        </Typography>
      ) : (
        <Stack
          ref={stepListRef}
          gap={0.45}
          sx={{ maxHeight: compactSteps ? "none" : "min(60vh, 680px)", overflowY: "auto", pr: 0.25 }}
        >
          {steps.map((step, index) => {
            const id = stepId(step);
            const roles = rolesForStep(id, steps, episodes, review);
            const selected = index === stepIndex;
            return (
              <Button
                disableRipple
                key={`${id || "missing"}-${index}`}
                onClick={() => changeStep(index)}
                aria-current={selected ? "step" : undefined}
                variant="text"
                color="inherit"
                sx={theme => ({
                  display: "block",
                  flexShrink: 0,
                  textAlign: "left",
                  p: 1,
                  textTransform: "none",
                  border: "1px solid",
                  borderColor: selected ? "primary.main" : "divider",
                  borderRadius: 1.5,
                  bgcolor: selected ? alpha(theme.palette.primary.main, 0.075) : "transparent",
                  color: "text.primary",
                  "&:hover": { bgcolor: "action.hover" },
                })}
              >
                <Stack direction="row" justifyContent="space-between" alignItems="center" gap={0.5}>
                  <Typography sx={{ fontWeight: 700, fontSize: 13 }}>Step {id || index + 1}</Typography>
                  {roles.length > 0 && (
                    <Typography color="text.secondary" sx={{ fontSize: 11.5 }}>
                      {roles.length} flag{roles.length === 1 ? "" : "s"}
                    </Typography>
                  )}
                </Stack>
                <Typography
                  sx={{
                    color: "text.secondary",
                    mt: 0.3,
                    fontSize: 12.5,
                    overflowWrap: "anywhere",
                    display: "-webkit-box",
                    WebkitBoxOrient: "vertical",
                    WebkitLineClamp: 2,
                    overflow: "hidden",
                  }}
                >
                  {text(step.action, text(step.intent, "Action not recorded"))}
                </Typography>
                {roles.length > 0 && (
                  <Stack component="span" gap={0.5} sx={{ mt: 0.75 }}>
                    {roles.map(role => {
                      const episode = episodes.find(item => getEpisodeId(item) === role.episodeId);
                      const anchor = episode ? firstProblemAnchor(currentTask, episode) : "";
                      return (
                        <StepFlag
                          key={`${role.episodeId}-${role.kind}`}
                          kind={role.kind === "recovery" ? "recovery" : role.kind === "related" ? "related" : "problem"}
                          number={role.number}
                          label={
                            episode
                              ? resolveEpisodeLabel(episode, pinnedLabels, draftProposals).displayName
                              : "Problem flagged"
                          }
                          relation={`${roleBadgeLabel(role.kind, role.firstObserved)}${role.kind !== "first" && anchor ? `, starts at step ${anchor}` : ""}`}
                        />
                      );
                    })}
                  </Stack>
                )}
              </Button>
            );
          })}
        </Stack>
      )}
      <Divider sx={{ my: 1.1 }} />
      <Typography color="text.secondary" sx={{ px: 0.6, mb: 0.8, fontSize: 12.5, fontWeight: 700 }}>
        PROBLEMS
      </Typography>
      {!!episodes.length && (
        <Typography color="text.secondary" sx={{ px: 0.6, mb: 0.9, fontSize: 12.5, lineHeight: 1.5 }}>
          “First observed” marks the agent’s earliest identified step in a version 2 review; “First flagged” marks the
          earliest explicit flag in a legacy review. A recovery link records an attempted fix or recovery evidence, not
          proof of success. Related steps add context without starting a new problem.
        </Typography>
      )}
      {!review ? (
        <Typography color="text.secondary" sx={{ px: 0.6, py: 0.5, fontSize: 13 }}>
          Not recorded
        </Typography>
      ) : !episodes.length ? (
        <Typography color="text.secondary" sx={{ px: 0.6, py: 0.5, fontSize: 13 }}>
          No problems recorded in this review.
        </Typography>
      ) : (
        <Stack gap={0.8}>
          {episodes.map((episode, index) => (
            <EpisodeCard
              key={getEpisodeId(episode) || index}
              episode={episode}
              index={index}
              steps={steps}
              review={review}
              labels={pinnedLabels}
              proposals={draftProposals}
              onStep={stepById}
            />
          ))}
        </Stack>
      )}
    </>
  );

  return (
    <Box className="trajectory-page">
      <Stack direction="row" justifyContent="space-between" alignItems="center" gap={1} sx={{ mb: 1.5 }}>
        <Button
          component={RouterLink}
          to={`/runs/${encodeURIComponent(batchId)}`}
          startIcon={<ArrowBackRounded />}
          sx={{ px: 0 }}
        >
          Back to run
        </Button>
        <Stack direction="row" gap={0.7} flexWrap="wrap" justifyContent="flex-end">
          <Button size="small" variant="outlined" href={exportHref("yaml")} startIcon={<OpenInNewRounded />}>
            Export YAML
          </Button>
          <Button size="small" variant="outlined" href={exportHref("json")}>
            Export JSON
          </Button>
          {recordedRawUrl && (
            <Button size="small" variant="text" href={recordedRawUrl}>
              Raw record
            </Button>
          )}
        </Stack>
      </Stack>
      {asRecord(currentTask.provenance).saved_replay === true ||
      (Array.isArray(response?.review_history) &&
        asRecord(response.review_history.at(-1)).backend === "saved_replay") ? (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          <strong>Saved replay.</strong> This review reuses retained evidence and made no new model calls.
        </Alert>
      ) : (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          The viewer displays the saved task and review. Opening evidence does not start new model calls.
        </Alert>
      )}
      <PageBreadcrumbs
        items={[
          { label: "Datasets", to: "/datasets" },
          { label: datasetName, to: datasetId ? `/datasets/${encodeURIComponent(datasetId)}` : undefined },
          {
            label: currentTask.title || currentTask.task_id,
            to: datasetId
              ? `/datasets/${encodeURIComponent(datasetId)}/tasks/${encodeURIComponent(String(currentTask.task_definition_id || taskId))}`
              : undefined,
          },
          { label: "Review" },
        ]}
      />
      <PageHeader
        eyebrow="TRAJECTORY REVIEW"
        title={currentTask.title || currentTask.task_id}
        description={`${currentTask.task_id} · ${batchRecord?.name || "Run"}`}
        action={
          <Stack gap={0.7} alignItems="flex-start">
            <BenchmarkResult task={currentTask} compact />
            <StatusTag value={reviewProcessingStatus} />
            <StatusTag value={`Review assessment: ${reviewAssessmentStatus}`} />
          </Stack>
        }
      />
      <Panel sx={{ mb: 2, p: { xs: 1.2, md: 1.5 } }}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          alignItems={{ md: "center" }}
          justifyContent="space-between"
          gap={1.2}
        >
          <Stack direction="row" alignItems="center" gap={1.2} flexWrap="wrap">
            <Button variant="outlined" onClick={() => setTaskPickerOpen(true)} startIcon={<SearchRounded />}>
              Choose task
            </Button>
            <Typography sx={{ fontWeight: 650, fontSize: 12, overflowWrap: "anywhere" }}>
              {currentTask.task_id}
            </Typography>
            <StatusTag value={review?.review_kind || member?.review_kind || "Review kind: not recorded"} />
            <StatusTag value={reviewProcessingStatus} />
          </Stack>
          <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
            <Button
              size="small"
              variant="outlined"
              startIcon={<ArrowBackRounded />}
              disabled={currentTaskIndex <= 0}
              onClick={() => {
                const previous = tasks[currentTaskIndex - 1];
                if (previous) moveToTask(taskKey(previous), "", idOf(previous.member_id));
              }}
            >
              Previous task
            </Button>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              {Math.max(0, currentTaskIndex + 1)} / {tasks.length}
            </Typography>
            <Button
              size="small"
              variant="outlined"
              endIcon={<ArrowForwardRounded />}
              disabled={currentTaskIndex < 0 || currentTaskIndex >= tasks.length - 1}
              onClick={() => {
                const next = tasks[currentTaskIndex + 1];
                if (next) moveToTask(taskKey(next), "", idOf(next.member_id));
              }}
            >
              Next task
            </Button>
          </Stack>
        </Stack>
      </Panel>
      {failedJob && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Review processing failed: {reviewProcessingError(failedJob.error)}
          {failureJobId && (
            <>
              {" "}
              ·{" "}
              <Link
                component={RouterLink}
                to={`/jobs/${encodeURIComponent(failureJobId)}`}
                color="inherit"
                fontWeight={700}
              >
                Job details
              </Link>
            </>
          )}
        </Alert>
      )}
      {requestedStepId && !steps.some(step => stepId(step) === requestedStepId) && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Step {requestedStepId} was requested, but it is not available in this recorded trajectory. The exact requested
          step ID remains in the address.
        </Alert>
      )}

      <Stack direction={{ xs: "column", lg: "row" }} gap={2} alignItems="stretch">
        {!compactSteps && (
          <Paper
            elevation={0}
            sx={{
              width: sidebarOpen ? 304 : 72,
              flex: "0 0 auto",
              border: "1px solid",
              borderColor: "divider",
              borderRadius: 2,
              p: 1,
              alignSelf: "flex-start",
            }}
          >
            <Stack direction="row" alignItems="center" justifyContent="space-between">
              <Typography sx={{ fontWeight: 700, fontSize: 13, pl: 0.5 }}>
                {sidebarOpen ? "Task and steps" : "Steps"}
              </Typography>
              <IconButton
                size="small"
                aria-label={sidebarOpen ? "Collapse task and step sidebar" : "Expand task and step sidebar"}
                onClick={() => setSidebarOpen(value => !value)}
              >
                {sidebarOpen ? <ExpandLessRounded /> : <ExpandMoreRounded />}
              </IconButton>
            </Stack>
            <Collapse in={sidebarOpen} unmountOnExit>
              {stepNavigator}
            </Collapse>
          </Paper>
        )}

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Panel sx={{ mb: 2 }}>
            <Stack
              ref={screenshotRef}
              direction={{ xs: "column", sm: "row" }}
              alignItems={{ xs: "stretch", sm: "center" }}
              justifyContent="space-between"
              gap={1}
              sx={{ mb: 1.2, scrollMarginTop: 16 }}
            >
              <Box>
                <SectionTitle
                  title={selectedStep ? `Step ${selectedStepId || stepIndex + 1}` : "Trajectory evidence"}
                  subtitle={
                    selectedStep
                      ? `${stepIndex + 1} of ${steps.length} recorded steps`
                      : "No saved trajectory step is available."
                  }
                />
              </Box>
              <Stack direction="row" gap={0.7} flexWrap="wrap" justifyContent={{ xs: "flex-start", sm: "flex-end" }}>
                {compactSteps ? (
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<FormatListNumberedRounded />}
                    onClick={() => setStepPickerOpen(true)}
                  >
                    All steps
                  </Button>
                ) : (
                  <Button size="small" variant="text" onClick={alignScreenshot}>
                    Screen ↑
                  </Button>
                )}
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<ArrowBackRounded />}
                  disabled={stepIndex <= 0}
                  onClick={() => changeStep(stepIndex - 1)}
                >
                  Previous
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  endIcon={<ArrowForwardRounded />}
                  disabled={stepIndex >= steps.length - 1}
                  onClick={() => changeStep(stepIndex + 1)}
                >
                  Next
                </Button>
              </Stack>
            </Stack>
            {selectedStep && (
              <>
                <Box
                  sx={{
                    width: "100%",
                    minHeight: screenshotUrl && !screenshotLoadFailed ? { xs: 140, md: 260 } : 112,
                    maxHeight: "72vh",
                    display: "grid",
                    placeItems: "center",
                    overflow: "auto",
                    bgcolor: "action.hover",
                    border: "1px solid",
                    borderColor: "divider",
                    borderRadius: 2.5,
                  }}
                >
                  {screenshotUrl && !screenshotLoadFailed ? (
                    <Link
                      href={screenshotUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Open screenshot for step ${selectedStepId} at full size`}
                      sx={{ display: "block", width: "100%", lineHeight: 0, cursor: "zoom-in" }}
                    >
                      <Box
                        component="img"
                        src={String(screenshotUrl)}
                        alt={`Recorded screenshot for step ${selectedStepId}`}
                        className="screenshot-full"
                        sx={{ maxHeight: "72vh", objectFit: "contain" }}
                        onError={() => setScreenshotLoadFailed(true)}
                      />
                    </Link>
                  ) : null}
                  {screenshotMessage && (
                    <Typography
                      sx={{
                        px: 2,
                        py: 2,
                        color: sourceScreenshotMissing ? "text.secondary" : "text.secondary",
                        textAlign: "center",
                        fontSize: 13,
                      }}
                    >
                      {screenshotMessage}
                    </Typography>
                  )}
                </Box>
                {screenshotUrl && !screenshotLoadFailed && (
                  <Link
                    href={screenshotUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, mt: 0.7, fontSize: 12 }}
                  >
                    Open screenshot at full size
                    <OpenInNewRounded sx={{ fontSize: 14 }} />
                  </Link>
                )}
                <Box sx={{ pt: 1.7 }}>
                  <Stack direction="row" gap={0.65} flexWrap="wrap" sx={{ mb: 1 }}>
                    <Chip
                      size="small"
                      variant="outlined"
                      color={sourceScreenshotAvailable ? "success" : "default"}
                      label={`Source screenshot: ${sourceScreenshotAvailable ? "available" : sourceScreenshotRecorded ? "file missing" : "not recorded"}`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      color={deliveryRecorded && screenshotWasSent ? "success" : "default"}
                      label={`Sent to reviewer: ${deliveryRecorded ? (screenshotWasSent ? "yes" : "no") : "not recorded"}`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      color={screenshotCitationCount ? "info" : "default"}
                      label={`Cited by assessment: ${Array.isArray(provenance.cited_image_step_ids) || evidenceMode === "text_only" ? (screenshotCitationCount ? "yes" : "no") : "not recorded"}`}
                    />
                  </Stack>
                  {deliveryRecorded && screenshotWasSent && (
                    <Typography color="text.secondary" sx={{ mb: 1, fontSize: 12.5 }}>
                      A screenshot sent to the reviewer does not establish whether it was examined.
                    </Typography>
                  )}
                  {cannotConfirmFromEvidence && (
                    <Alert severity="warning" sx={{ mb: 1.2 }}>
                      Cannot confirm from evidence. The saved review marked this step as insufficient evidence.
                    </Alert>
                  )}
                  {stepRoles.length > 0 && (
                    <Stack direction="row" gap={0.7} flexWrap="wrap" sx={{ mb: 1.2 }}>
                      {stepRoles.map(role => (
                        <Chip
                          key={`${role.episodeId}-${role.kind}`}
                          color={role.kind === "recovery" ? "success" : "warning"}
                          label={`Problem ${role.number}: ${roleBadgeLabel(role.kind, role.firstObserved)}`}
                        />
                      ))}
                    </Stack>
                  )}
                  {selectedProblemEpisodes.length > 0 && (
                    <Stack gap={0.8} sx={{ mb: 1.2 }}>
                      {selectedProblemEpisodes.map((episode, index) => {
                        const resolved = resolveEpisodeLabel(episode, pinnedLabels, draftProposals);
                        return (
                          <Paper
                            key={getEpisodeId(episode) || index}
                            variant="outlined"
                            sx={{ p: 1.1, borderRadius: 2, bgcolor: "background.paper" }}
                          >
                            <Stack direction="row" gap={0.8} alignItems="center" flexWrap="wrap">
                              <Typography sx={{ fontWeight: 750, fontSize: 14 }}>
                                Problem {Number(episode.problem_number) || episodes.indexOf(episode) + 1}
                              </Typography>
                              <LabelChip id={resolved.id} label={resolved.displayName} />
                            </Stack>
                            <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: 13 }}>
                              {labelDefinitionText(resolved)}
                            </Typography>
                          </Paper>
                        );
                      })}
                    </Stack>
                  )}
                  <Stack direction={{ xs: "column", md: "row" }} gap={1.2}>
                    <DetailField label="Intent" value={text(selectedReviewStep?.intent ?? selectedStep.intent)} />
                    <DetailField label="Action" value={text(selectedStep.action)} />
                    <DetailField
                      label="Observation"
                      value={text(
                        selectedReviewStep?.observed_ui ?? selectedStep.observation ?? selectedStep.observed_ui,
                      )}
                    />
                  </Stack>
                  {selectedReviewStep && (
                    <Stack direction={{ xs: "column", md: "row" }} gap={1.2} sx={{ mt: 1.2 }}>
                      <DetailField label="Effect" value={text(selectedReviewStep.effect)} />
                      <DetailField label="Assessment" value={text(selectedReviewStep.assessment)} />
                      <DetailField label="Review status" value={text(selectedReviewStep.review_status)} />
                    </Stack>
                  )}
                  {Array.isArray(selectedStep.evidence_refs) && selectedStep.evidence_refs.length > 0 && (
                    <Typography color="text.secondary" sx={{ mt: 1.1, fontSize: 12.5 }}>
                      Recorded evidence references: {selectedStep.evidence_refs.map(item => text(item)).join(", ")}
                    </Typography>
                  )}
                </Box>
              </>
            )}
          </Panel>

          {!review ? (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Review data: Not recorded. This does not mean the task has zero issues.
            </Alert>
          ) : (
            <Panel sx={{ mb: 2 }}>
              <SectionTitle title="Review summary" subtitle={text(review.review_kind, "Review kind not recorded")} />
              <Typography sx={{ whiteSpace: "pre-wrap" }}>
                {text(review.summary, "No review summary recorded.")}
              </Typography>
              <Stack direction="row" gap={0.7} flexWrap="wrap" sx={{ mt: 1.2 }}>
                <StatusTag value={review.result} />
                <StatusTag value={review.review_kind} />
                {review.schema_version && (
                  <Chip size="small" variant="outlined" label={`Schema v${review.schema_version}`} />
                )}
              </Stack>
              {Array.isArray(review.coverage_notes) && !!review.coverage_notes.length && (
                <Box sx={{ mt: 1.2 }}>
                  <Typography sx={{ fontWeight: 700, mb: 0.3 }}>Coverage notes</Typography>
                  {review.coverage_notes.map((note, index) => (
                    <Typography key={index} color="text.secondary" sx={{ fontSize: 13 }}>
                      {text(note)}
                    </Typography>
                  ))}
                </Box>
              )}
            </Panel>
          )}

          <Panel sx={{ mb: 2 }}>
            <SectionTitle
              title="Record reviewer feedback"
              subtitle="Feedback is attached to the selected task and step."
            />
            {feedbackError && (
              <Alert severity="error" sx={{ mb: 1 }}>
                {feedbackError}
              </Alert>
            )}
            {feedbackNotice && (
              <Alert severity="success" sx={{ mb: 1 }}>
                {feedbackNotice}
              </Alert>
            )}
            <Stack direction={{ xs: "column", sm: "row" }} gap={1} alignItems="flex-start">
              <TextField
                fullWidth
                multiline
                minRows={2}
                label="Feedback"
                value={feedbackText}
                onChange={event => setFeedbackText(event.target.value)}
              />
              <Button
                variant="contained"
                disabled={feedbackBusy || !feedbackText.trim()}
                onClick={() => void submitFeedback()}
              >
                {feedbackBusy ? "Saving…" : "Save feedback"}
              </Button>
            </Stack>
            {feedback.length > 0 && (
              <Stack gap={0.7} sx={{ mt: 1.5 }}>
                {feedback.map((entry, index) => (
                  <Paper key={String(entry.id || index)} variant="outlined" sx={{ p: 1.2, borderRadius: 2 }}>
                    <Typography sx={{ whiteSpace: "pre-wrap" }}>
                      {text(entry.text || entry.feedback, "Feedback text not recorded")}
                    </Typography>
                    <Typography color="text.secondary" sx={{ mt: 0.4, fontSize: 12 }}>
                      {text(entry.actor_name || entry.actor_email, "Reviewer")} · {formatDate(entry.created_at)}
                      {entry.step_id ? ` · Step ${entry.step_id}` : ""}
                    </Typography>
                  </Paper>
                ))}
              </Stack>
            )}
          </Panel>
        </Box>
      </Stack>

      <Dialog
        open={stepPickerOpen && compactSteps}
        fullScreen
        disableRestoreFocus
        slotProps={{ transition: { onExited: alignScreenshot } }}
        onClose={() => setStepPickerOpen(false)}
      >
        <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", py: 1.2 }}>
          Choose a step
          <IconButton aria-label="Close step picker" onClick={() => setStepPickerOpen(false)}>
            <CloseRounded />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers sx={{ p: 1.5 }}>
          {stepNavigator}
        </DialogContent>
      </Dialog>
      <Dialog
        open={taskPickerOpen}
        onClose={() => setTaskPickerOpen(false)}
        fullWidth
        fullScreen={compactSteps}
        maxWidth="md"
      >
        <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 1 }}>
          Choose a task in this run
          <IconButton onClick={() => setTaskPickerOpen(false)} aria-label="Close task selector">
            <CloseRounded />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          <TextField
            autoFocus
            fullWidth
            value={taskSearch}
            onChange={event => setTaskSearch(event.target.value)}
            placeholder="Search task name, ID, instruction, or label"
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRounded />
                </InputAdornment>
              ),
            }}
            sx={{ mb: 1.5 }}
          />
          {!filteredTasks.length ? (
            <Typography color="text.secondary" sx={{ py: 3, textAlign: "center" }}>
              No tasks match this search.
            </Typography>
          ) : (
            <Stack gap={1}>
              {filteredTasks.map((row, index) => {
                const taskIdValue = taskKey(row);
                const rowSummary = taskSummary(row);
                const rowReview = reviewFor(row);
                const rowMemberId = idOf(row.member_id);
                const active = taskIdValue === taskId && (!selectedMemberId || rowMemberId === selectedMemberId);
                const taskLinkGroups = rowSummary.episodes.map((episode, episodeIndex) => {
                  const links = taskProblemLinks(row, episode);
                  return {
                    episode,
                    number: Number(episode.problem_number) || episodeIndex + 1,
                    anchorId: firstProblemAnchor(row, episode),
                    flagged: links.filter(link => link.role.startsWith("First ") || link.role.startsWith("Also ")),
                    recovery: links.filter(link => link.role === "Recovery step"),
                    related: links.filter(link => link.role === "Related step"),
                  };
                });
                const taskPath = `/runs/${encodeURIComponent(batchId)}/tasks/${encodeURIComponent(taskIdValue)}${rowMemberId ? `?member_id=${encodeURIComponent(rowMemberId)}` : ""}`;
                return (
                  <Paper
                    key={`${taskIdValue}-${rowMemberId || index}`}
                    variant="outlined"
                    sx={theme => ({
                      p: 1.5,
                      borderRadius: 2,
                      position: "relative",
                      borderColor: active ? "primary.main" : "divider",
                      bgcolor: active ? alpha(theme.palette.primary.main, 0.075) : "background.paper",
                      "&:hover": { borderColor: "primary.main" },
                      "&:has(a:focus-visible)": {
                        outline: "2px solid",
                        outlineColor: "primary.main",
                        outlineOffset: 2,
                      },
                    })}
                  >
                    <Stack direction={{ xs: "column", sm: "row" }} gap={1.2} alignItems={{ sm: "center" }}>
                      <Avatar
                        sx={{
                          width: 38,
                          height: 38,
                          bgcolor: outcomeLabel(taskOutcome(row)).toLowerCase().includes("fail")
                            ? "error.light"
                            : "primary.light",
                          color: "primary.dark",
                          fontWeight: 800,
                        }}
                      >
                        {index + 1}
                      </Avatar>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography
                          component={RouterLink}
                          to={taskPath}
                          onClick={() => setTaskPickerOpen(false)}
                          className="task-card-title"
                          sx={{
                            fontWeight: 650,
                            color: "text.primary",
                            textDecoration: "none",
                            overflowWrap: "anywhere",
                            "&::after": { content: '""', position: "absolute", inset: 0, borderRadius: 2, zIndex: 1 },
                          }}
                        >
                          {row.title || taskIdValue}
                        </Typography>
                        <Typography color="text.secondary" sx={{ fontSize: 12.5, overflowWrap: "anywhere" }}>
                          {taskIdValue} · {row.steps?.length ?? row.total_steps ?? "Not recorded"} source steps
                        </Typography>
                        <Stack direction="row" gap={0.55} flexWrap="wrap" sx={{ mt: 0.8 }}>
                          <BenchmarkResult task={row} compact />
                          <StatusTag value={reviewProcessingLabel(row)} />
                          <StatusTag value={`Review assessment: ${reviewAssessmentLabel(row, rowReview)}`} />
                          <Chip size="small" variant="outlined" label={`${rowSummary.problemCount} problems`} />
                          <Chip size="small" variant="outlined" label={`${rowSummary.flaggedCount} flagged steps`} />
                          <Chip size="small" variant="outlined" label={`${rowSummary.recoveryCount} recovery steps`} />
                          <Chip size="small" variant="outlined" label={`${rowSummary.labelCount} labels`} />
                        </Stack>
                        {!!rowSummary.labels.length && (
                          <Stack direction="row" gap={0.55} flexWrap="wrap" sx={{ mt: 0.8 }}>
                            {rowSummary.labels.map(group => (
                              <LabelChip
                                key={group.id || group.label}
                                id={group.id}
                                label={group.label}
                                count={group.count}
                              />
                            ))}
                          </Stack>
                        )}
                        {!!taskLinkGroups.some(
                          group => group.flagged.length || group.recovery.length || group.related.length,
                        ) && (
                          <Stack gap={0.9} sx={{ mt: 0.9 }}>
                            {taskLinkGroups
                              .filter(group => group.flagged.length || group.recovery.length || group.related.length)
                              .map(({ episode, number, anchorId, flagged, recovery, related }) => {
                                const renderStepChip = (stepIdValue: string, label: string, key: string) => {
                                  const missing =
                                    Array.isArray(row.steps) && !row.steps.some(step => stepId(step) === stepIdValue);
                                  return (
                                    <Chip
                                      key={key}
                                      size="small"
                                      component="button"
                                      clickable={!missing}
                                      disabled={missing}
                                      color={missing ? "error" : undefined}
                                      variant="outlined"
                                      label={missing ? `Step ${stepIdValue} unavailable` : `${label} · ${stepIdValue}`}
                                      onClick={() => !missing && moveToTask(taskIdValue, stepIdValue, rowMemberId)}
                                      sx={{ fontSize: 12, fontWeight: 650, position: "relative", zIndex: 2 }}
                                    />
                                  );
                                };
                                return (
                                  <Box key={`${getEpisodeId(episode)}-${number}`}>
                                    <Typography
                                      color="text.secondary"
                                      sx={{ mb: 0.4, fontSize: 12.5, fontWeight: 700 }}
                                    >
                                      Problem {number}
                                    </Typography>
                                    {!!flagged.length && (
                                      <Stack direction="row" gap={0.45} flexWrap="wrap">
                                        {flagged.map((link, linkIndex) =>
                                          renderStepChip(link.id, link.role, `flag-${link.id}-${linkIndex}`),
                                        )}
                                      </Stack>
                                    )}
                                    {!!recovery.length && (
                                      <Box sx={{ mt: 0.45 }}>
                                        <Stack direction="row" gap={0.5} alignItems="center" flexWrap="wrap">
                                          <Typography color="success.dark" sx={{ fontSize: 12.5, fontWeight: 700 }}>
                                            Recovery
                                          </Typography>
                                          {anchorId ? (
                                            renderStepChip(anchorId, "First anchor", `recovery-anchor-${anchorId}`)
                                          ) : (
                                            <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>
                                              First anchor: Not recorded
                                            </Typography>
                                          )}
                                        </Stack>
                                        <Stack direction="row" gap={0.45} flexWrap="wrap" sx={{ mt: 0.35 }}>
                                          {recovery.map((link, linkIndex) =>
                                            renderStepChip(
                                              link.id,
                                              "Recovery step",
                                              `recovery-${link.id}-${linkIndex}`,
                                            ),
                                          )}
                                        </Stack>
                                      </Box>
                                    )}
                                    {!!related.length && (
                                      <Box component="details" sx={{ mt: 0.45, position: "relative", zIndex: 2 }}>
                                        <Box
                                          component="summary"
                                          sx={{
                                            cursor: "pointer",
                                            color: "primary.main",
                                            fontSize: 12.5,
                                            fontWeight: 650,
                                          }}
                                        >
                                          Related steps · {related.length}
                                        </Box>
                                        <Stack direction="row" gap={0.45} flexWrap="wrap" sx={{ mt: 0.4 }}>
                                          {anchorId ? (
                                            renderStepChip(anchorId, "First anchor", `related-anchor-${anchorId}`)
                                          ) : (
                                            <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>
                                              First anchor: Not recorded
                                            </Typography>
                                          )}
                                          {related.map((link, linkIndex) =>
                                            renderStepChip(link.id, "Related step", `related-${link.id}-${linkIndex}`),
                                          )}
                                        </Stack>
                                      </Box>
                                    )}
                                  </Box>
                                );
                              })}
                          </Stack>
                        )}
                      </Box>
                      <Button
                        variant={active ? "contained" : "outlined"}
                        sx={{ position: "relative", zIndex: 2 }}
                        onClick={() => moveToTask(taskIdValue, "", rowMemberId)}
                      >
                        {active ? "Current task" : "Open task"}
                      </Button>
                    </Stack>
                  </Paper>
                );
              })}
            </Stack>
          )}
        </DialogContent>
      </Dialog>
    </Box>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.2, borderRadius: 2, flex: 1, minWidth: 0 }}>
      <Typography
        color="text.secondary"
        sx={{ mb: 0.3, fontSize: 12, fontWeight: 750, textTransform: "uppercase", letterSpacing: ".055em" }}
      >
        {label}
      </Typography>
      <Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 13 }}>{value}</Typography>
    </Paper>
  );
}
