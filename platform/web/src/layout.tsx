import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useGetIdentity, useLogout } from "react-admin";
import { AppBar, Avatar, Box, Button, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Stack, Toolbar, Tooltip, Typography, useMediaQuery } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import MenuRounded from "@mui/icons-material/MenuRounded";
import ChevronLeftRounded from "@mui/icons-material/ChevronLeftRounded";
import ChevronRightRounded from "@mui/icons-material/ChevronRightRounded";
import DashboardRounded from "@mui/icons-material/DashboardRounded";
import StorageRounded from "@mui/icons-material/StorageRounded";
import PlaylistPlayRounded from "@mui/icons-material/PlaylistPlayRounded";
import GroupsRounded from "@mui/icons-material/GroupsRounded";
import TuneRounded from "@mui/icons-material/TuneRounded";
import AccountTreeRounded from "@mui/icons-material/AccountTreeRounded";
import TimelineRounded from "@mui/icons-material/TimelineRounded";
import InsightsRounded from "@mui/icons-material/InsightsRounded";
import HelpOutlineRounded from "@mui/icons-material/HelpOutlineRounded";
import WorkspacesRounded from "@mui/icons-material/WorkspacesRounded";
import LogoutRounded from "@mui/icons-material/LogoutRounded";
import type { ReactNode } from "react";
import { ThemeModeToggle } from "./theme";

type NavItem = { label: string; path: string; icon: ReactNode };
const navItems: NavItem[] = [
  { label: "Overview", path: "/", icon: <DashboardRounded /> },
  { label: "Datasets", path: "/datasets", icon: <StorageRounded /> },
  { label: "Runs", path: "/runs", icon: <PlaylistPlayRounded /> },
  { label: "Analytics", path: "/analytics", icon: <InsightsRounded /> },
  { label: "Teams", path: "/teams", icon: <GroupsRounded /> },
  { label: "Presets", path: "/presets", icon: <TuneRounded /> },
  { label: "Taxonomy", path: "/taxonomy", icon: <AccountTreeRounded /> },
  { label: "Activity", path: "/activity", icon: <TimelineRounded /> },
  { label: "Jobs", path: "/jobs", icon: <WorkspacesRounded /> },
];

function WorkspaceMark() {
  return <Box sx={{ width: 32, height: 32, flexShrink: 0, display: "grid", placeItems: "center", borderRadius: "7px", bgcolor: "primary.main", color: "primary.contrastText" }}><WorkspacesRounded fontSize="small" /></Box>;
}

function SidebarContent({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const helpSelected = pathname === "/help" || pathname.startsWith("/docs");
  return <>
    <Stack direction="row" alignItems="center" gap={1.2} sx={{ px: collapsed ? 2.4 : 2, py: 1.6, minHeight: 64 }}>
      <WorkspaceMark />
      {!collapsed && <Box sx={{ minWidth: 0 }}><Typography sx={{ fontSize: 15, fontWeight: 800, lineHeight: 1.15 }}>CUAutoReview</Typography><Typography color="text.secondary" sx={{ mt: .35, fontSize: 12 }}>Local workspace</Typography></Box>}
    </Stack>
    <Divider />
    <Typography variant="overline" color="text.secondary" aria-hidden={collapsed || undefined} sx={{ px: collapsed ? 1 : 2.2, pt: 1.5, pb: .5 }}>{collapsed ? "\u00a0" : "WORKSPACE"}</Typography>
    <List disablePadding sx={{ px: 1.1 }}>
      {navItems.map(item => {
        const selected = item.path === "/" ? pathname === "/" : pathname === item.path || pathname.startsWith(`${item.path}/`);
        const button = <ListItemButton key={item.path} component={NavLink} to={item.path} end={item.path === "/"} onClick={onNavigate} selected={selected} sx={{ minHeight: 42, mb: .25, px: collapsed ? 1.5 : 1.2, borderRadius: "6px", justifyContent: collapsed ? "center" : "initial", color: selected ? "primary.main" : "text.secondary", "@media (pointer: coarse)": { minHeight: 46 }, "&.Mui-selected": { bgcolor: "action.selected", color: "primary.main", "&:hover": { bgcolor: "action.selected" } } }}>
          <ListItemIcon sx={{ minWidth: collapsed ? 0 : 34, color: "inherit", justifyContent: "center", "& svg": { fontSize: 21 } }}>{item.icon}</ListItemIcon>
          {!collapsed && <ListItemText primary={item.label} primaryTypographyProps={{ fontSize: 13, fontWeight: selected ? 650 : 500 }} />}
        </ListItemButton>;
        return collapsed ? <Tooltip key={item.path} title={item.label} placement="right">{button}</Tooltip> : button;
      })}
    </List>
    <Box sx={{ mt: "auto", px: 1.1, pb: 1 }}>
      {!collapsed && <Box sx={{ mb: 1, p: 1.5, borderRadius: "7px", bgcolor: "action.hover", border: "1px solid", borderColor: "divider" }}>
        <Typography sx={{ fontWeight: 650, fontSize: 12 }}>Saved replay by default</Typography>
        <Typography color="text.secondary" sx={{ mt: .6, fontSize: 12.5, lineHeight: 1.45 }}>Runs keep a fixed task selection and record the workflow and execution settings used.</Typography>
      </Box>}
      {collapsed ? <Tooltip title="Help and guides" placement="right"><ListItemButton component={NavLink} to="/docs/getting-started" onClick={onNavigate} selected={helpSelected} aria-label="Help and guides" sx={{ minHeight: 43, px: 1.5, borderRadius: 2, justifyContent: "center", color: helpSelected ? "primary.main" : "text.secondary", "&.Mui-selected": { bgcolor: "action.selected", color: "primary.main" } }}><ListItemIcon sx={{ minWidth: 0, color: "inherit", justifyContent: "center" }}><HelpOutlineRounded /></ListItemIcon></ListItemButton></Tooltip>
        : <ListItemButton component={NavLink} to="/docs/getting-started" onClick={onNavigate} selected={helpSelected} sx={{ minHeight: 43, borderRadius: 2, color: helpSelected ? "primary.main" : "text.secondary", "&.Mui-selected": { bgcolor: "action.selected", color: "primary.main" } }}><ListItemIcon sx={{ minWidth: 39, color: "inherit", justifyContent: "center" }}><HelpOutlineRounded /></ListItemIcon><ListItemText primary="Help and guides" primaryTypographyProps={{ fontSize: 14, fontWeight: helpSelected ? 750 : 580 }} /></ListItemButton>}
    </Box>
  </>;
}

function TopBar({ onMenu, mobile, collapsed }: { onMenu: () => void; mobile: boolean; collapsed: boolean }) {
  const identity = useGetIdentity();
  const logout = useLogout();
  const name = String(identity.data?.name || identity.data?.email || "Reviewer");
  const initial = name.trim().slice(0, 1).toUpperCase();
  return <AppBar position="static" elevation={0} color="inherit" sx={{ borderBottom: "1px solid", borderColor: "divider", bgcolor: "background.paper" }}>
    <Toolbar sx={{ minHeight: { xs: "56px !important", md: "64px !important" }, px: { xs: 1, md: 2.5 }, gap: { xs: .5, sm: 1 } }}>
      <IconButton aria-label={mobile ? "Open navigation" : collapsed ? "Expand navigation" : "Collapse navigation"} onClick={onMenu} sx={{ color: "text.secondary" }}>{mobile ? <MenuRounded /> : collapsed ? <ChevronRightRounded /> : <ChevronLeftRounded />}</IconButton>
      <Typography sx={{ display: { xs: "block", sm: "none" }, fontSize: 13, fontWeight: 700, mr: "auto" }}>CUAutoReview</Typography>
      <Stack direction="row" alignItems="center" gap={1} sx={{ mr: "auto", minWidth: 0, display: { xs: "none", sm: "flex" } }}>
        <Box sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: "primary.main" }} />
        <Typography sx={{ fontSize: 13, fontWeight: 650, whiteSpace: "nowrap" }}>Local workspace</Typography>
        <Typography color="text.secondary" sx={{ display: { xs: "none", lg: "block" }, fontSize: 13 }}>Workflow and execution provenance stay attached to every run</Typography>
      </Stack>
      <Stack direction="row" alignItems="center" gap={{ xs: .2, sm: .8 }} sx={{ ml: "auto", flexShrink: 0 }}>
        <ThemeModeToggle />
        <Avatar aria-label={name} sx={{ width: 30, height: 30, bgcolor: "action.selected", color: "primary.main", fontSize: 13, fontWeight: 650, display: { xs: "none", sm: "flex" } }}>{initial}</Avatar>
        <Box sx={{ display: { xs: "none", lg: "block" } }}><Typography sx={{ fontWeight: 700, fontSize: 13, lineHeight: 1.2 }}>{name}</Typography><Typography color="text.secondary" sx={{ fontSize: 11, textTransform: "capitalize" }}>{String(identity.data?.role || "member")}</Typography></Box>
        <IconButton aria-label="Sign out" onClick={() => logout()} sx={{ display: { xs: "inline-flex", sm: "none" }, color: "text.secondary" }}><LogoutRounded fontSize="small" /></IconButton>
        <Button color="inherit" size="small" startIcon={<LogoutRounded />} onClick={() => logout()} sx={{ display: { xs: "none", sm: "inline-flex" }, ml: .5, color: "text.secondary" }}>Sign out</Button>
      </Stack>
    </Toolbar>
  </AppBar>;
}

export function WorkspaceLayout({ children }: { children: ReactNode }) {
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("md"));
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("cu-web-nav-collapsed") === "true"; } catch { return false; }
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const toggle = () => {
    if (mobile) setMobileOpen(value => !value);
    else setCollapsed(value => {
      const next = !value;
      try { localStorage.setItem("cu-web-nav-collapsed", String(next)); } catch { /* storage can be unavailable */ }
      return next;
    });
  };
  const closeMobile = () => setMobileOpen(false);
  const navWidth = collapsed ? 72 : 240;
  return <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
    {mobile ? <Drawer variant="temporary" open={mobileOpen} onClose={closeMobile} ModalProps={{ keepMounted: true }} PaperProps={{ component: "nav", "aria-label": "Workspace navigation", sx: { width: "min(280px, 88vw)", display: "flex", flexDirection: "column", bgcolor: "background.paper" } }}><SidebarContent collapsed={false} onNavigate={closeMobile} /></Drawer> : <Box component="nav" aria-label="Workspace navigation" sx={{ position: "fixed", inset: "0 auto 0 0", zIndex: 10, width: navWidth, overflowY: "auto", display: "flex", flexDirection: "column", bgcolor: "background.paper", borderRight: "1px solid", borderColor: "divider", transition: "width 160ms ease" }}><SidebarContent collapsed={collapsed} /></Box>}
    <Box sx={{ ml: { xs: 0, md: `${navWidth}px` }, minWidth: 0, minHeight: "100dvh", transition: "margin-left 160ms ease" }}>
      <TopBar mobile={mobile} collapsed={collapsed} onMenu={toggle} />
      <Box component="main" id="workspace-main" sx={{ width: "100%", maxWidth: 1640, minWidth: 0, mx: "auto", px: { xs: 1.5, sm: 2.5, lg: 3 }, py: { xs: 2, md: 2.5 } }}>{children}</Box>
      <Box component="footer" sx={{ px: { xs: 1.5, sm: 2.5, lg: 3 }, pb: 2, color: "text.secondary", fontSize: 11.5 }}>
        Local workspace · Evidence and evaluator outcomes are preserved as recorded.
      </Box>
    </Box>
  </Box>;
}
