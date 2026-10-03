import { useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { Alert, Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import FileUploadRounded from "@mui/icons-material/FileUploadRounded";
import DownloadRounded from "@mui/icons-material/DownloadRounded";
import { ApiError, apiRequest } from "../api/client";
import type { TaskRecord } from "../api/types";

interface ImportIssue {
  path: string;
  message: string;
  code?: string;
}
interface PreviewTask {
  task_id: string;
  title?: string;
  step_count: number;
  outcome?: string;
}
interface ImportPreview {
  valid: boolean;
  task_count: number;
  screenshot_count: number;
  tasks: PreviewTask[];
  warnings: ImportIssue[];
}
export interface PreparedImport {
  kind: "zip" | "json";
  file: File;
  tasks?: TaskRecord[];
  preview: ImportPreview;
}
export interface ImportResult {
  created: number;
  revised: number;
  unchanged: number;
  warnings?: ImportIssue[];
}

export function importSummary(result: ImportResult): string {
  return `${result.created} added, ${result.revised} revised, ${result.unchanged} unchanged. No review run started.`;
}

export function uploadPreparedImport(datasetId: string, prepared: PreparedImport): Promise<ImportResult> {
  const path = `/datasets/${encodeURIComponent(datasetId)}`;
  return prepared.kind === "zip"
    ? apiRequest(`${path}/import-zip`, {
        method: "POST",
        body: prepared.file,
        headers: { "Content-Type": "application/zip" },
      })
    : apiRequest(`${path}/import`, {
        method: "POST",
        body: JSON.stringify({ format: "cuautoreview", tasks: prepared.tasks }),
      });
}

export function useTaskImport() {
  const [prepared, setPrepared] = useState<PreparedImport | null>(null);
  const [fileName, setFileName] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [issues, setIssues] = useState<ImportIssue[]>([]);
  const selection = useRef(0);
  const reset = () => {
    selection.current++;
    setPrepared(null);
    setFileName("");
    setChecking(false);
    setError("");
    setIssues([]);
  };
  const choose = async (file?: File) => {
    reset();
    if (!file) return;
    const revision = selection.current;
    setFileName(file.name);
    setChecking(true);
    try {
      if (file.size > 32 * 1024 * 1024) throw new Error("This file exceeds 32 MB. Split it into smaller imports.");
      const kind = file.name.toLowerCase().endsWith(".zip")
        ? "zip"
        : file.name.toLowerCase().endsWith(".json")
          ? "json"
          : null;
      if (!kind) throw new Error("Choose a .zip archive or a .json task file.");
      let preview: ImportPreview;
      let tasks: TaskRecord[] | undefined;
      if (kind === "zip") {
        preview = await apiRequest<ImportPreview>("/imports/zip/validate", {
          method: "POST",
          body: file,
          headers: { "Content-Type": "application/zip" },
        });
      } else {
        const parsed = JSON.parse(await file.text());
        tasks = Array.isArray(parsed) ? parsed : parsed?.tasks;
        if (
          !Array.isArray(tasks) ||
          !tasks.length ||
          !tasks.every(
            task => task && typeof task === "object" && typeof task.task_id === "string" && task.task_id.trim(),
          )
        ) {
          throw new Error(
            "JSON needs a nonempty tasks array, or a task array, with a nonempty task_id for each record.",
          );
        }
        if (new Set(tasks.map(task => task.task_id)).size !== tasks.length)
          throw new Error("Each task_id must be unique within one import.");
        if (tasks.some(task => task.steps !== undefined && !Array.isArray(task.steps)))
          throw new Error("Each task's steps must be an array.");
        preview = {
          valid: true,
          task_count: tasks.length,
          screenshot_count: 0,
          warnings: [],
          tasks: tasks.map(task => ({
            task_id: task.task_id,
            title: task.title,
            step_count: task.steps?.length || 0,
            outcome: typeof task.outcome === "string" ? task.outcome : "unknown",
          })),
        };
      }
      if (selection.current === revision) setPrepared({ file, kind, tasks, preview });
    } catch (reason) {
      if (selection.current !== revision) return;
      setError(reason instanceof Error ? reason.message : "The file could not be validated.");
      if (reason instanceof ApiError) {
        const detail = (reason.payload as { detail?: { errors?: ImportIssue[] } })?.detail;
        if (Array.isArray(detail?.errors)) setIssues(detail.errors);
      }
    } finally {
      if (selection.current === revision) setChecking(false);
    }
  };
  return { prepared, fileName, checking, error, issues, choose, reset };
}

export function TaskImportPicker({
  state,
  disabled = false,
  optional = false,
}: {
  state: ReturnType<typeof useTaskImport>;
  disabled?: boolean;
  optional?: boolean;
}) {
  const { prepared, checking, fileName, error, issues } = state;
  const fileInput = useRef<HTMLInputElement>(null);
  return (
    <Stack gap={1.5}>
      <Typography sx={{ fontWeight: 750 }}>{optional ? "Initial tasks (optional)" : "Choose task records"}</Typography>
      <Typography color="text.secondary" sx={{ fontSize: 14 }}>
        Upload a ZIP with its task manifest and screenshots, or a saved JSON task file. ZIP selection sends the file to
        this local server for validation; nothing is saved until you confirm.
      </Typography>
      <Stack direction="row" gap={1} flexWrap="wrap">
        <Button
          variant="outlined"
          disabled={disabled || checking}
          startIcon={<FileUploadRounded />}
          onClick={() => fileInput.current?.click()}
        >
          Choose ZIP or JSON
        </Button>
        <input
          ref={fileInput}
          aria-label="Task ZIP or JSON file"
          hidden
          type="file"
          accept=".zip,.json,application/zip,application/json"
          onChange={event => {
            void state.choose(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <Button component="a" href="/examples/trajectory-import.zip" download startIcon={<DownloadRounded />}>
          Example ZIP
        </Button>
        {fileName && (
          <Button disabled={disabled || checking} onClick={state.reset}>
            Remove file
          </Button>
        )}
      </Stack>
      {fileName && (
        <Typography color="text.secondary" sx={{ overflowWrap: "anywhere", fontSize: 14 }}>
          {fileName}
        </Typography>
      )}
      {checking && (
        <Stack direction="row" alignItems="center" gap={1}>
          <CircularProgress size={18} />
          <Typography role="status">Checking structure and screenshots…</Typography>
        </Stack>
      )}
      {error && (
        <Alert severity="error">
          <strong>{error}</strong>
          {issues.length > 0 && (
            <Box component="ul" sx={{ pl: 2.3, mb: 0 }}>
              {issues.map((issue, index) => (
                <li key={index}>
                  <code>{issue.path}</code>: {issue.message}
                </li>
              ))}
            </Box>
          )}
        </Alert>
      )}
      {prepared && (
        <>
          <Alert severity="success">
            {prepared.preview.task_count} tasks ready
            {prepared.kind === "zip"
              ? ` with ${prepared.preview.screenshot_count} screenshots`
              : " for server validation on import"}
            .
          </Alert>
          {prepared.preview.warnings?.length > 0 && (
            <Alert severity="warning">
              Review these warnings before importing.
              <Box component="ul" sx={{ pl: 2.3, mb: 0 }}>
                {prepared.preview.warnings.map((issue, index) => (
                  <li key={index}>
                    <code>{issue.path}</code>: {issue.message}
                  </li>
                ))}
              </Box>
            </Alert>
          )}
          <Box sx={{ maxHeight: 210, overflow: "auto", border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
            {prepared.preview.tasks.slice(0, 50).map(task => (
              <Box key={task.task_id} sx={{ p: 1.2, borderBottom: "1px solid", borderColor: "divider" }}>
                <Typography sx={{ fontWeight: 700 }}>{task.title || task.task_id}</Typography>
                <Typography color="text.secondary" sx={{ fontSize: 13 }}>
                  {task.task_id} · {task.step_count} steps · {task.outcome || "unknown"}
                </Typography>
              </Box>
            ))}
          </Box>
          {prepared.preview.task_count > 50 && (
            <Typography color="text.secondary">Showing the first 50 tasks.</Typography>
          )}
        </>
      )}
      <Box component="details" sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 1.5 }}>
        <Box component="summary" sx={{ cursor: "pointer", fontWeight: 700 }}>
          Expected ZIP structure and limits
        </Box>
        <Box
          component="pre"
          sx={{ bgcolor: "action.hover", p: 1.3, overflow: "auto", fontSize: 13 }}
        >{`tasks.zip\n├── dataset.json  (or dataset.yaml, one only)\n└── assets/\n    └── task-1/\n        └── step-1.png`}</Box>
        <Box component="pre" sx={{ bgcolor: "action.hover", p: 1.3, overflow: "auto", fontSize: 13 }}>
          {JSON.stringify(
            {
              format: "cuautoreview",
              tasks: [
                {
                  task_id: "task-1",
                  title: "Open the application",
                  instruction: "Open the application from the desktop.",
                  outcome: "unknown",
                  steps: [{ step_id: "1", action: "Click the app icon", screenshot: "assets/task-1/step-1.png" }],
                },
              ],
            },
            null,
            2,
          )}
        </Box>
        <Typography color="text.secondary" sx={{ fontSize: 14 }}>
          Keep the manifest at the archive root. Each task ID and each step ID within a task must be unique. Screenshot
          references must match included PNG, JPEG or WebP files. Screenshots are optional; missing visual evidence is
          reported as a warning. An explicit reference to a missing file is an error.
        </Typography>
        <Typography color="text.secondary" sx={{ mt: 1, fontSize: 14 }}>
          Maximum: 32 MB ZIP, 128 MB expanded, 1,000 entries and 10 MB / 16 million pixels per screenshot. Nested ZIPs,
          scripts, HTML, SVG, encrypted files, links and paths outside the archive are rejected. The import guide lists
          record and step limits.
        </Typography>
        <Button component={RouterLink} to="/docs/datasets" sx={{ mt: 1 }}>
          Read the import guide
        </Button>
      </Box>
    </Stack>
  );
}
