import { Box } from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";

export function StatusTag({ value, tone }: { value?: unknown; tone?: string }) {
  const theme = useTheme();
  const text = value === null || value === undefined || value === "" ? "Not recorded" : String(value).replaceAll("_", " ");
  const normalized = (tone || text).toLowerCase();
  const color = /fail|error|cancel|reject|blocked/.test(normalized) ? "error" : /pass|success|complete|recovered|approved/.test(normalized) ? "success" : /running|queue|pending|partial|review|pause|draft/.test(normalized) ? "warning" : null;
  const palette = color ? theme.palette[color] : null;
  return <Box component="span" sx={{ display: "inline-flex", alignItems: "center", maxWidth: "100%", minHeight: 24, px: .85, py: .2, borderRadius: "5px", border: "1px solid", borderColor: palette ? alpha(palette.main, .35) : "divider", bgcolor: palette ? alpha(palette.main, theme.palette.mode === "dark" ? .12 : .07) : "action.hover", color: palette ? palette.dark : "text.secondary", fontSize: 12, lineHeight: 1.4, fontWeight: 600, textTransform: "capitalize", overflowWrap: "anywhere" }}>{text}</Box>;
}
