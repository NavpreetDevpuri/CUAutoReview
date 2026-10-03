import { Chip } from "@mui/material";
import { useTheme } from "@mui/material/styles";

const labelPalette = [
  {
    light: { bg: "#eaf1ff", fg: "#345fc0", border: "#b8c9ef" },
    dark: { bg: "#253a60", fg: "#c1d4ff", border: "#5272a7" },
  },
  {
    light: { bg: "#e7f5ee", fg: "#19704d", border: "#b1dbc6" },
    dark: { bg: "#214638", fg: "#b8e8d0", border: "#497961" },
  },
  {
    light: { bg: "#fff2da", fg: "#946311", border: "#e8d2a4" },
    dark: { bg: "#49391f", fg: "#f3d18c", border: "#896b35" },
  },
  {
    light: { bg: "#f0eaff", fg: "#6845a7", border: "#d2c2ed" },
    dark: { bg: "#392f52", fg: "#d6c6ff", border: "#7462a4" },
  },
  {
    light: { bg: "#ffebeb", fg: "#aa3a40", border: "#e5b7b9" },
    dark: { bg: "#4a2c32", fg: "#ffc1c6", border: "#97575e" },
  },
  {
    light: { bg: "#e5f5f6", fg: "#176d73", border: "#acd9dc" },
    dark: { bg: "#1e4144", fg: "#b9e9eb", border: "#4c8386" },
  },
  {
    light: { bg: "#fce9f2", fg: "#9b3c6b", border: "#e8bfd2" },
    dark: { bg: "#482c3b", fg: "#f7c4db", border: "#985b79" },
  },
  {
    light: { bg: "#eef1f4", fg: "#495766", border: "#c7cdd4" },
    dark: { bg: "#303945", fg: "#d0d7df", border: "#687583" },
  },
];
function labelColor(key: string): (typeof labelPalette)[number] {
  const canonical = /^c(\d+)$/i.exec(key);
  const index = canonical
    ? Number(canonical[1]) - 1
    : [...key].reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 0);
  return labelPalette[Math.abs(index) % labelPalette.length];
}
export function LabelChip({ id, label, count }: { id?: string; label: string; count?: number }) {
  const theme = useTheme();
  const colors = labelColor(id || label);
  const color = theme.palette.mode === "dark" ? colors.dark : colors.light;
  return (
    <Chip
      size="small"
      label={count === undefined ? label : `${label} · ${count}`}
      sx={{
        maxWidth: "100%",
        fontWeight: 750,
        bgcolor: color.bg,
        color: color.fg,
        border: "1px solid",
        borderColor: color.border,
      }}
    />
  );
}
