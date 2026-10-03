import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { CssBaseline, IconButton, ThemeProvider, Tooltip, createTheme } from "@mui/material";
import type { PaletteMode, Theme } from "@mui/material/styles";
import DarkModeRounded from "@mui/icons-material/DarkModeRounded";
import LightModeRounded from "@mui/icons-material/LightModeRounded";

interface ThemeModeContextValue {
  mode: PaletteMode;
  theme: Theme;
  toggleMode: () => void;
}

const ThemeModeContext = createContext<ThemeModeContextValue | null>(null);
const STORAGE_KEY = "cu-web-color-mode";

function preferredMode(): PaletteMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function createWorkspaceTheme(mode: PaletteMode) {
  const dark = mode === "dark";
  return createTheme({
    palette: {
      mode,
      primary: dark
        ? { main: "#90b4ff", dark: "#b8ceff", light: "#31466d", contrastText: "#101725" }
        : { main: "#2f64c5", dark: "#204d9e", light: "#eaf1ff", contrastText: "#ffffff" },
      secondary: { main: dark ? "#a8c0d3" : "#55728d" },
      background: { default: dark ? "#10151f" : "#f4f7fb", paper: dark ? "#171e2a" : "#ffffff" },
      text: { primary: dark ? "#ecf1f7" : "#172334", secondary: dark ? "#b0bccb" : "#586779" },
      divider: dark ? "rgba(218,228,240,.14)" : "#e1e8f0",
      success: dark
        ? { main: "#75d5a4", dark: "#a8edc8", light: "#254c3b", contrastText: "#101a14" }
        : { main: "#27825d", dark: "#15563c", light: "#d8f0e4", contrastText: "#ffffff" },
      warning: dark
        ? { main: "#f2bd68", dark: "#ffdb9f", light: "#594426", contrastText: "#1b160c" }
        : { main: "#a96e14", dark: "#75500f", light: "#fff0d0", contrastText: "#ffffff" },
      error: dark
        ? { main: "#ff8e98", dark: "#ffb3ba", light: "#582b34", contrastText: "#201014" }
        : { main: "#bd4750", dark: "#8e2e38", light: "#fbe5e7", contrastText: "#ffffff" },
    },
    shape: { borderRadius: 6 },
    typography: {
      fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: 14,
      h1: { fontSize: "clamp(22px, 2.2vw, 28px)", fontWeight: 700, letterSpacing: "-.025em", lineHeight: 1.25 },
      h2: { fontSize: 24, fontWeight: 700, letterSpacing: "-.025em", lineHeight: 1.25 },
      h3: { fontSize: 17, fontWeight: 650, letterSpacing: "-.015em", lineHeight: 1.35 },
      body1: { fontSize: 14, lineHeight: 1.55 },
      body2: { fontSize: 13, lineHeight: 1.5 },
      subtitle1: { fontSize: 14, fontWeight: 600, lineHeight: 1.5 },
      subtitle2: { fontSize: 13, fontWeight: 600, lineHeight: 1.5 },
      caption: { fontSize: 12, lineHeight: 1.45 },
      overline: { fontSize: 10, fontWeight: 700, letterSpacing: ".09em", lineHeight: 1.8 },
      button: { fontSize: 13, textTransform: "none", fontWeight: 600 },
    },
    components: {
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 6,
            minHeight: 36,
            whiteSpace: "nowrap",
            lineHeight: 1.35,
            flexShrink: 0,
            boxShadow: "none",
            "&:hover": { boxShadow: "none" },
            "@media (pointer: coarse)": { minHeight: 44 },
          },
          startIcon: { marginLeft: 0, marginRight: 6 },
          endIcon: { marginLeft: 6, marginRight: 0 },
        },
      },
      MuiIconButton: { styleOverrides: { root: { "@media (pointer: coarse)": { minWidth: 44, minHeight: 44 } } } },
      MuiTextField: { defaultProps: { size: "small" } },
      MuiFormControl: { defaultProps: { size: "small" }, styleOverrides: { root: { minWidth: 0 } } },
      MuiOutlinedInput: {
        styleOverrides: {
          root: ({ theme }) => ({
            backgroundColor: theme.palette.background.paper,
            fontSize: 14,
            [theme.breakpoints.down("sm")]: { fontSize: 16 },
          }),
        },
      },
      MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
      MuiChip: {
        styleOverrides: {
          root: { maxWidth: "100%", minHeight: 24, height: "auto", borderRadius: 6, fontSize: 12, fontWeight: 600 },
          label: { padding: "3px 8px", whiteSpace: "normal", overflowWrap: "anywhere", lineHeight: 1.4 },
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: { fontSize: 13, padding: "12px 14px", verticalAlign: "top" },
          head: { color: dark ? "#c5d0df" : "#526174", fontWeight: 650 },
          sizeSmall: { padding: "10px 12px" },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            borderRadius: 10,
            "@media (max-width: 599px)": { margin: 12, maxWidth: "calc(100% - 24px)", maxHeight: "calc(100% - 24px)" },
            "&.MuiDialog-paperFullScreen": { margin: 0, maxWidth: "100%", maxHeight: "100%", borderRadius: 0 },
          },
        },
      },
      MuiDialogTitle: { styleOverrides: { root: { fontSize: 18, fontWeight: 650, padding: "18px 20px 12px" } } },
      MuiDialogContent: { styleOverrides: { root: { paddingLeft: 20, paddingRight: 20 } } },
      MuiDialogActions: {
        styleOverrides: {
          root: {
            padding: "12px 20px 16px",
            gap: 8,
            flexWrap: "wrap",
            "& > :not(style) ~ :not(style)": { marginLeft: 0 },
          },
        },
      },
      MuiAlert: {
        styleOverrides: { root: { minWidth: 0, fontSize: 13 }, message: { minWidth: 0, overflowWrap: "anywhere" } },
      },
    },
  });
}

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<PaletteMode>(preferredMode);
  const theme = useMemo(() => createWorkspaceTheme(mode), [mode]);
  const toggleMode = useCallback(() => {
    setMode(current => {
      const next: PaletteMode = current === "light" ? "dark" : "light";
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* preferences remain usable without storage */
      }
      return next;
    });
  }, []);
  const value = useMemo(() => ({ mode, theme, toggleMode }), [mode, theme, toggleMode]);
  return (
    <ThemeModeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeModeContext.Provider>
  );
}

export function useThemeMode() {
  const value = useContext(ThemeModeContext);
  if (!value) throw new Error("useThemeMode must be used inside ThemeModeProvider");
  return value;
}

export function ThemeModeToggle({ size = "small" }: { size?: "small" | "medium" }) {
  const { mode, toggleMode } = useThemeMode();
  const target = mode === "light" ? "dark" : "light";
  return (
    <Tooltip title={`Switch to ${target} mode`}>
      <IconButton size={size} color="inherit" aria-label={`Switch to ${target} mode`} onClick={toggleMode}>
        {mode === "light" ? <DarkModeRounded fontSize={size} /> : <LightModeRounded fontSize={size} />}
      </IconButton>
    </Tooltip>
  );
}
