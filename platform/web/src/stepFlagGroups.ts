interface DisplayedStepFlag {
  kind: string;
  label: string;
  relation: string;
}

export function stepFlagEvidence(provenance: Record<string, unknown>, stepId: string) {
  const ids = (value: unknown) => Array.isArray(value) ? value.map(String) : null;
  const source = ids(provenance.source_image_step_ids);
  const supplied = ids(provenance.supplied_image_step_ids);
  const cited = ids(provenance.cited_image_step_ids);
  const legacyTextOnly = !provenance.evidence_mode && Array.isArray(provenance.inspected_image_step_ids) && provenance.inspected_image_step_ids.length === 0 && !supplied;
  const textOnly = provenance.evidence_mode === "text_only" || legacyTextOnly;
  const delivery = supplied ? supplied.includes(stepId) ? "Frame sent" : "Frame not sent" : textOnly ? "Frame not sent" : "Delivery unknown";
  return [
    delivery,
    legacyTextOnly ? "legacy text-only review" : textOnly ? "text-only review" : "",
    source && !source.includes(stepId) ? "no source frame listed" : "",
    cited ? cited.includes(stepId) ? "frame cited" : "not cited" : "",
  ].filter(Boolean).join(" · ");
}

/** Display-only grouping; each review occurrence and its provenance stay intact. */
export function groupStepFlags<T extends DisplayedStepFlag>(flags: readonly T[]) {
  const groups = new Map<string, { key: string; flags: T[] }>();
  for (const flag of flags) {
    const key = JSON.stringify([flag.kind, flag.label, flag.relation]);
    const group = groups.get(key);
    if (group) group.flags.push(flag);
    else groups.set(key, { key, flags: [flag] });
  }
  return [...groups.values()];
}
