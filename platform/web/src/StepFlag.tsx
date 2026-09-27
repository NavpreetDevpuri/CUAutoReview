import { Box, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";

export interface StepFlagData {
  kind: "problem" | "related" | "recovery";
  number: string | number;
  label: string;
  relation: string;
  review?: string;
  model?: string;
}

/** The same grid keeps problem, relation, and reviewer details aligned in every step. */
export function StepFlag({ kind, number, label, relation, review, model }: StepFlagData) {
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
  </Box>;
}
