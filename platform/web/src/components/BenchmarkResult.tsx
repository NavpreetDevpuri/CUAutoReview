import { Chip, Stack, Typography } from "@mui/material";
import { StatusTag } from "./StatusTag";
import { benchmarkResultLabel, benchmarkValue, scoreText } from "../lib/benchmark";

export function BenchmarkResult({ task, compact = false }: { task: Record<string, unknown>; compact?: boolean }) {
  const label = benchmarkResultLabel(task);
  const result = benchmarkValue(task.benchmark_result ?? task.outcome ?? task.evaluator_outcome);
  const score = scoreText(task.benchmark_score ?? task.score);
  return <Stack direction={compact ? "row" : "column"} alignItems={compact ? "center" : "flex-start"} gap={.45} flexWrap="wrap" sx={{ minWidth: 0 }}>
    <Typography color="text.secondary" sx={{ fontSize: 11.5, fontWeight: 700 }}>{label}</Typography>
    <Stack direction="row" gap={.45} alignItems="center" flexWrap="wrap"><StatusTag value={result} />{score !== undefined && <Chip size="small" variant="outlined" label={`Score ${score}`} />}</Stack>
  </Stack>;
}
