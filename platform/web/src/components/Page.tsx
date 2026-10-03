import type { ReactNode } from "react";
import { Box, Breadcrumbs, Link, Paper, Stack, Typography } from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

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

export function SectionTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} justifyContent="space-between" gap={1} sx={{ mb: 1.5, minWidth: 0 }}>
    <Box sx={{ minWidth: 0 }}><Typography variant="h3" sx={{ overflowWrap: "anywhere" }}>{title}</Typography>{subtitle && <Typography color="text.secondary" sx={{ mt: .35, fontSize: 13, overflowWrap: "anywhere" }}>{subtitle}</Typography>}</Box>
    {action}
  </Stack>;
}
