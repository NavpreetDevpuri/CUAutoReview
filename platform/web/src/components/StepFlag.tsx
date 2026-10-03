import { Box, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";

export interface StepFlagData {
  kind: "problem" | "related" | "recovery";
  number: string | number;
  label: string;
  relation: string;
  review?: string;
  model?: string;
  evidence?: string;
}

export interface StepFlagOccurrence extends StepFlagData {
  key: string;
  review: string;
  model: string;
  run: string;
}

/** Shared text is compacted without treating review-local problems as one issue. */
export function StepFlagGroup({ flags }: { flags: StepFlagOccurrence[] }) {
  const first = flags[0];
  if (!first) return null;
  const tone = first.kind === "recovery" ? "success" : first.kind === "related" ? "info" : "warning";
  return <Box component="span" sx={theme => ({
    display: "block", p: .75, borderRadius: 1, border: "1px solid",
    borderColor: alpha(theme.palette[tone].main, .28),
    bgcolor: alpha(theme.palette[tone].main, theme.palette.mode === "dark" ? .10 : .055),
    color: "text.primary", textAlign: "left", lineHeight: 1.35,
  })}>
    <Typography component="span" sx={{ display: "block", fontSize: 12, fontWeight: 650, lineHeight: 1.4, overflowWrap: "anywhere" }}>{first.label}</Typography>
    <Typography component="span" sx={{ display: "block", mt: .2, fontSize: 11.5, color: `${tone}.main`, lineHeight: 1.4 }}>{first.relation}</Typography>
    {flags.map((flag, index) => <Box component="span" key={`${flag.key}-${index}`} sx={{
      display: "grid", gridTemplateColumns: "64px minmax(0, 1fr)", columnGap: .8, rowGap: .2,
      mt: .55, pt: .55, borderTop: "1px solid", borderColor: "divider",
      "& .MuiTypography-root": { fontSize: 11.5, lineHeight: 1.4, overflowWrap: "anywhere" },
    }}>
      <Typography component="span" sx={{ fontWeight: 650 }}>Review {flag.review}</Typography><Typography component="span" sx={{ color: `${tone}.main`, fontWeight: 650 }}>Problem {flag.number}</Typography>
      <Typography component="span" color="text.secondary">Model</Typography><Typography component="span">{flag.model}</Typography>
      {flag.evidence && <><Typography component="span" color="text.secondary">Input</Typography><Typography component="span">{flag.evidence}</Typography></>}
    </Box>)}
  </Box>;
}

/** The same grid keeps problem, relation, and reviewer details aligned in every step. */
export function StepFlag({ kind, number, label, relation, review, model, evidence }: StepFlagData) {
  const tone = kind === "recovery" ? "success" : kind === "related" ? "info" : "warning";
  return <Box component="span" sx={theme => ({
    display: "grid", gridTemplateColumns: "64px minmax(0, 1fr)", columnGap: .8, rowGap: .25,
    p: .75, borderRadius: 1, border: "1px solid", borderColor: alpha(theme.palette[tone].main, .28),
    bgcolor: alpha(theme.palette[tone].main, theme.palette.mode === "dark" ? .10 : .055),
    color: "text.primary", textAlign: "left", lineHeight: 1.35,
  })}>
    <Typography component="span" sx={{ fontSize: 11.5, fontWeight: 750, color: `${tone}.main`, whiteSpace: "nowrap", lineHeight: 1.4 }}>Problem {number}</Typography>
    <Typography component="span" sx={{ fontSize: 12, fontWeight: 650, lineHeight: 1.4, overflowWrap: "anywhere" }}>{label}</Typography>
    <Typography component="span" sx={{ gridColumn: 2, fontSize: 11.5, color: "text.secondary", lineHeight: 1.4 }}>{relation}</Typography>
    {review && <><Typography component="span" sx={{ fontSize: 11, color: "text.secondary", lineHeight: 1.4 }}>Review</Typography><Typography component="span" sx={{ fontSize: 11.5, lineHeight: 1.4 }}>{review}</Typography></>}
    {model && <><Typography component="span" sx={{ fontSize: 11, color: "text.secondary", lineHeight: 1.4 }}>Model</Typography><Typography component="span" sx={{ fontSize: 11.5, lineHeight: 1.4, overflowWrap: "anywhere" }}>{model}</Typography></>}
    {evidence && <><Typography component="span" sx={{ fontSize: 11, color: "text.secondary", lineHeight: 1.4 }}>Input</Typography><Typography component="span" sx={{ fontSize: 11.5, lineHeight: 1.4 }}>{evidence}</Typography></>}
  </Box>;
}
