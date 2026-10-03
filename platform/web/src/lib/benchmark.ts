import { asRecord } from "./records";

export function benchmarkResultLabel(task: Record<string, unknown>): string {
  const source = asRecord(task.source);
  const datasets = Array.isArray(task.source_datasets) ? task.source_datasets.map(item => {
    const dataset = asRecord(item);
    return dataset.name || dataset.dataset_name || dataset.source_adapter;
  }) : [];
  const origin = [source.dataset, source.benchmark, source.name, task.benchmark, task.source_adapter, ...datasets]
    .filter(value => value !== null && value !== undefined).map(String).join(" ").toLowerCase();
  return origin.includes("osworld") ? "OSWorld result" : "Framework result";
}

export function benchmarkValue(value: unknown): unknown {
  if (value === true) return "passed";
  if (value === false) return "failed";
  return value;
}

export function scoreText(value: unknown): string | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}
