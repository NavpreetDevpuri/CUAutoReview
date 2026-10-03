import type { ReactNode } from "react";
import { Alert, Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import { Panel } from "./Page";

export function LoadingState({ label = "Loading saved workspace data…" }: { label?: string }) {
  return (
    <Stack alignItems="center" justifyContent="center" gap={1.5} sx={{ minHeight: 210, color: "text.secondary" }}>
      <CircularProgress size={25} />
      <Typography>{label}</Typography>
    </Stack>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Alert
      severity="error"
      action={
        onRetry ? (
          <Button color="inherit" startIcon={<RefreshRounded />} onClick={onRetry}>
            Retry
          </Button>
        ) : undefined
      }
    >
      {message}
    </Alert>
  );
}

/** Explains when a paged list stopped before the server's total, instead of silently hiding records. */
export function TruncationNote({ list, noun }: { list: unknown; noun: string }) {
  const page = list as { items?: unknown[]; total?: number; truncated?: boolean } | null;
  if (!page?.truncated || !Array.isArray(page.items)) return null;
  return (
    <Alert severity="info" sx={{ mb: 2 }}>
      Showing the first {page.items.length} of {page.total} {noun}.
    </Alert>
  );
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <Panel sx={{ py: 5, textAlign: "center", bgcolor: "background.default", borderStyle: "dashed" }}>
      <Typography variant="h3">{title}</Typography>
      <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 570, mx: "auto" }}>
        {description}
      </Typography>
      {action && <Box sx={{ mt: 2.3 }}>{action}</Box>}
    </Panel>
  );
}
