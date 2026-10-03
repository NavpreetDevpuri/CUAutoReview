import type { ReactNode } from "react";
import { Alert, Box, Button, Chip, CircularProgress, Paper, Stack, Typography } from "@mui/material";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import { alpha, useTheme, type SxProps, type Theme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";
import { Breadcrumbs, Link } from "@mui/material";

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return <Stack direction={{ xs: "column", md: "row" }} alignItems={{ md: "flex-start" }} justifyContent="space-between" gap={1.5} sx={{ mb: 2.4, minWidth: 0 }}>
    <Box sx={{ minWidth: 0, flex: "1 1 auto" }}>
      {eyebrow && <Typography variant="overline" color="primary.main">{eyebrow}</Typography>}
      <Typography variant="h1" sx={{ mt: .25, overflowWrap: "anywhere" }}>{title}</Typography>
      {description && <Typography color="text.secondary" sx={{ mt: .6, maxWidth: 830, fontSize: 13, overflowWrap: "anywhere" }}>{description}</Typography>}
    </Box>
    {action && <Box className="page-header-actions" sx={{ flex: "0 1 auto", minWidth: 0, maxWidth: { xs: "100%", md: "48%" }, "& > .MuiStack-root": { flexWrap: "wrap" }, "& .MuiButton-root": { maxWidth: "100%" } }}>{action}</Box>}
  </Stack>;
}

export function countLabel(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function runStatusLabel(run: { status?: unknown; processing_status?: unknown; archived?: unknown; archived_at?: unknown; progress?: unknown; failed_task_count?: unknown }) {
  if (run.archived || run.archived_at) return "archived";
  const status = String(run.status || run.processing_status || "unknown");
  const progress = run.progress && typeof run.progress === "object" ? run.progress as Record<string, unknown> : {};
  return status.toLowerCase() === "completed" && Number(progress.failed ?? run.failed_task_count ?? 0) > 0 ? "finished with errors" : status;
}

export function PageBreadcrumbs({ items }: { items: { label: string; to?: string }[] }) {
  return <Breadcrumbs aria-label="Breadcrumb" sx={{ mb: 1.3, fontSize: 12, "& .MuiBreadcrumbs-ol": { flexWrap: "wrap" }, "& .MuiBreadcrumbs-li": { minWidth: 0, overflowWrap: "anywhere" } }}>
    {items.map((item, index) => item.to && index < items.length - 1
      ? <Link key={`${item.label}-${index}`} component={RouterLink} to={item.to} underline="hover" color="text.secondary">{item.label}</Link>
      : <Typography key={`${item.label}-${index}`} color={index === items.length - 1 ? "text.primary" : "text.secondary"} sx={{ fontSize: 12, fontWeight: index === items.length - 1 ? 600 : 500 }}>{item.label}</Typography>)}
  </Breadcrumbs>;
}

export function Panel({ children, sx }: { children: ReactNode; sx?: SxProps<Theme> }) {
  return <Paper elevation={0} sx={{ minWidth: 0, border: "1px solid", borderColor: "divider", borderRadius: "8px", p: { xs: 1.5, sm: 2 }, bgcolor: "background.paper", ...sx }}>{children}</Paper>;
}

export function LoadingState({ label = "Loading saved workspace data…" }: { label?: string }) {
  return <Stack alignItems="center" justifyContent="center" gap={1.5} sx={{ minHeight: 210, color: "text.secondary" }}><CircularProgress size={25} /><Typography>{label}</Typography></Stack>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <Alert severity="error" action={onRetry ? <Button color="inherit" startIcon={<RefreshRounded />} onClick={onRetry}>Retry</Button> : undefined}>{message}</Alert>;
}

/** Explains when a paged list stopped before the server's total, instead of silently hiding records. */
export function TruncationNote({ list, noun }: { list: unknown; noun: string }) {
  const page = list as { items?: unknown[]; total?: number; truncated?: boolean } | null;
  if (!page?.truncated || !Array.isArray(page.items)) return null;
  return <Alert severity="info" sx={{ mb: 2 }}>Showing the first {page.items.length} of {page.total} {noun}.</Alert>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <Panel sx={{ py: 5, textAlign: "center", bgcolor: "background.default", borderStyle: "dashed" }}>
    <Typography variant="h3">{title}</Typography><Typography color="text.secondary" sx={{ mt: 1, maxWidth: 570, mx: "auto" }}>{description}</Typography>
    {action && <Box sx={{ mt: 2.3 }}>{action}</Box>}
  </Panel>;
}

export function MetricCard({ label, value, detail, icon, tint = "blue" }: { label: string; value: ReactNode; detail?: string; icon?: ReactNode; tint?: "blue" | "green" | "amber" | "red" | "violet" }) {
  const theme = useTheme();
  const colors = {
    blue: ["#eaf1ff", "#345fc0", "#253a60", "#c1d4ff"],
    green: ["#e7f5ee", "#19704d", "#214638", "#b8e8d0"],
    amber: ["#fff2da", "#946311", "#49391f", "#f3d18c"],
    red: ["#ffebeb", "#aa3a40", "#4a2c32", "#ffc1c6"],
    violet: ["#f0eaff", "#6845a7", "#392f52", "#d6c6ff"],
  } as const;
  const tintColors = colors[tint];
  const iconBackground = theme.palette.mode === "dark" ? tintColors[2] : tintColors[0];
  const iconForeground = theme.palette.mode === "dark" ? tintColors[3] : tintColors[1];
  return <Paper elevation={0} sx={{ minWidth: 0, height: "100%", p: { xs: 1.5, sm: 2 }, border: "1px solid", borderColor: "divider", borderRadius: "8px", bgcolor: "background.paper" }}>
    <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}>
      <Box sx={{ minWidth: 0 }}><Typography color="text.secondary" sx={{ minHeight: "2.8em", fontWeight: 600, fontSize: 12, lineHeight: 1.4 }}>{label}</Typography><Typography variant="h2" sx={{ mt: .5, fontSize: { xs: 21, sm: 24 }, overflowWrap: "anywhere", fontVariantNumeric: "tabular-nums" }}>{value}</Typography>{detail && <Typography color="text.secondary" sx={{ mt: .5, fontSize: 12, overflowWrap: "anywhere" }}>{detail}</Typography>}</Box>
      {icon && <Box sx={{ flexShrink: 0, display: "grid", placeItems: "center", width: 32, height: 32, borderRadius: "6px", bgcolor: iconBackground, color: iconForeground, "& svg": { fontSize: 19 } }}>{icon}</Box>}
    </Stack>
  </Paper>;
}

export function StatusTag({ value, tone }: { value?: unknown; tone?: string }) {
  const theme = useTheme();
  const text = value === null || value === undefined || value === "" ? "Not recorded" : String(value).replaceAll("_", " ");
  const normalized = (tone || text).toLowerCase();
  const color = /fail|error|cancel|reject|blocked/.test(normalized) ? "error" : /pass|success|complete|recovered|approved/.test(normalized) ? "success" : /running|queue|pending|partial|review|pause|draft/.test(normalized) ? "warning" : null;
  const palette = color ? theme.palette[color] : null;
  return <Box component="span" sx={{ display: "inline-flex", alignItems: "center", maxWidth: "100%", minHeight: 24, px: .85, py: .2, borderRadius: "5px", border: "1px solid", borderColor: palette ? alpha(palette.main, .35) : "divider", bgcolor: palette ? alpha(palette.main, theme.palette.mode === "dark" ? .12 : .07) : "action.hover", color: palette ? palette.dark : "text.secondary", fontSize: 12, lineHeight: 1.4, fontWeight: 600, textTransform: "capitalize", overflowWrap: "anywhere" }}>{text}</Box>;
}

function sourceRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function benchmarkResultLabel(task: Record<string, unknown>): string {
  const source = sourceRecord(task.source);
  const datasets = Array.isArray(task.source_datasets) ? task.source_datasets.map(item => {
    const dataset = sourceRecord(item);
    return dataset.name || dataset.dataset_name || dataset.source_adapter;
  }) : [];
  const origin = [source.dataset, source.benchmark, source.name, task.benchmark, task.source_adapter, ...datasets]
    .filter(value => value !== null && value !== undefined).map(String).join(" ").toLowerCase();
  return origin.includes("osworld") ? "OSWorld result" : "Framework result";
}

function benchmarkValue(value: unknown): unknown {
  if (value === true) return "passed";
  if (value === false) return "failed";
  return value;
}

function scoreText(value: unknown): string | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

export function BenchmarkResult({ task, compact = false }: { task: Record<string, unknown>; compact?: boolean }) {
  const label = benchmarkResultLabel(task);
  const result = benchmarkValue(task.benchmark_result ?? task.outcome ?? task.evaluator_outcome);
  const score = scoreText(task.benchmark_score ?? task.score);
  return <Stack direction={compact ? "row" : "column"} alignItems={compact ? "center" : "flex-start"} gap={.45} flexWrap="wrap" sx={{ minWidth: 0 }}>
    <Typography color="text.secondary" sx={{ fontSize: 11.5, fontWeight: 700 }}>{label}</Typography>
    <Stack direction="row" gap={.45} alignItems="center" flexWrap="wrap"><StatusTag value={result} />{score !== undefined && <Chip size="small" variant="outlined" label={`Score ${score}`} />}</Stack>
  </Stack>;
}

export function reviewProcessingError(value: unknown): string {
  const message = value === null || value === undefined ? "" : String(value);
  if (/invalid structured output|invalid json|schema validation|structured output file/i.test(message)) {
    const retryNote = /no (?:application )?retry was made/i.test(message) ? " No automatic retry was made." : "";
    return `The model response could not be parsed as the required review format (JSON). This is a review-processing error, separate from the original benchmark result.${retryNote}`;
  }
  return message || "No error reason recorded";
}

export function SectionTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} justifyContent="space-between" gap={1} sx={{ mb: 1.5, minWidth: 0 }}>
    <Box sx={{ minWidth: 0 }}><Typography variant="h3" sx={{ overflowWrap: "anywhere" }}>{title}</Typography>{subtitle && <Typography color="text.secondary" sx={{ mt: .35, fontSize: 13, overflowWrap: "anywhere" }}>{subtitle}</Typography>}</Box>
    {action}
  </Stack>;
}

export function formatDate(value: unknown): string {
  if (!value) return "Not recorded";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function displayValue(value: unknown, fallback = "Not recorded"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}
