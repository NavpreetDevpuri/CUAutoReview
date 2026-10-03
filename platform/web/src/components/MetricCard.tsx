import type { ReactNode } from "react";
import { Box, Paper, Stack, Typography } from "@mui/material";
import { useTheme } from "@mui/material/styles";

export function MetricCard({
  label,
  value,
  detail,
  icon,
  tint = "blue",
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  icon?: ReactNode;
  tint?: "blue" | "green" | "amber" | "red" | "violet";
}) {
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
  return (
    <Paper
      elevation={0}
      sx={{
        minWidth: 0,
        height: "100%",
        p: { xs: 1.5, sm: 2 },
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "8px",
        bgcolor: "background.paper",
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}>
        <Box sx={{ minWidth: 0 }}>
          <Typography
            color="text.secondary"
            sx={{ minHeight: "2.8em", fontWeight: 600, fontSize: 12, lineHeight: 1.4 }}
          >
            {label}
          </Typography>
          <Typography
            variant="h2"
            sx={{ mt: 0.5, fontSize: { xs: 21, sm: 24 }, overflowWrap: "anywhere", fontVariantNumeric: "tabular-nums" }}
          >
            {value}
          </Typography>
          {detail && (
            <Typography color="text.secondary" sx={{ mt: 0.5, fontSize: 12, overflowWrap: "anywhere" }}>
              {detail}
            </Typography>
          )}
        </Box>
        {icon && (
          <Box
            sx={{
              flexShrink: 0,
              display: "grid",
              placeItems: "center",
              width: 32,
              height: 32,
              borderRadius: "6px",
              bgcolor: iconBackground,
              color: iconForeground,
              "& svg": { fontSize: 19 },
            }}
          >
            {icon}
          </Box>
        )}
      </Stack>
    </Paper>
  );
}
