import { useState, type FormEvent } from "react";
import { useLogin } from "react-admin";
import { Alert, Box, Button, CircularProgress, Container, Divider, Paper, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import AutoAwesomeRounded from "@mui/icons-material/AutoAwesomeRounded";
import { apiRequest } from "./api";
import { ThemeModeToggle } from "./theme";

export function AccessPage() {
  const login = useLogin();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "signup") {
        await apiRequest("/auth/signup", { method: "POST", body: JSON.stringify({ name: name.trim(), email: email.trim(), password }) });
      }
      await login({ email: email.trim(), password });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign in failed. Check your details and try again.");
    } finally { setBusy(false); }
  };

  return <Box sx={{ position: "relative", minHeight: "100vh", display: "grid", placeItems: "center", p: 2.5, bgcolor: "background.default", backgroundImage: theme => theme.palette.mode === "dark" ? "radial-gradient(circle at 12% 12%, rgba(64,94,151,.2) 0, transparent 32%), radial-gradient(circle at 85% 86%, rgba(43,106,82,.13) 0, transparent 28%)" : "radial-gradient(circle at 12% 12%, #e4edff 0, transparent 32%), radial-gradient(circle at 85% 86%, #e9f5f0 0, transparent 28%)" }}>
    <Box sx={{ position: "absolute", top: 2, right: 2 }}><ThemeModeToggle /></Box>
    <Container maxWidth="sm">
      <Paper elevation={0} sx={{ p: { xs: 2.5, sm: 4 }, border: "1px solid", borderColor: "divider", borderRadius: 4, boxShadow: theme => theme.palette.mode === "dark" ? "0 24px 70px rgba(0,0,0,.32)" : "0 24px 70px rgba(34,61,100,.1)" }}>
        <Stack alignItems="center" sx={{ mb: 3 }}>
          <Box sx={{ width: 50, height: 50, display: "grid", placeItems: "center", bgcolor: "primary.main", color: "primary.contrastText", borderRadius: 2.6 }}><AutoAwesomeRounded /></Box>
          <Typography variant="h1" sx={{ mt: 1.8, textAlign: "center" }}>CUAutoReview</Typography>
          <Typography color="text.secondary" sx={{ mt: .8, textAlign: "center", maxWidth: 440 }}>A local evidence workspace for computer-use trajectories, review runs, teams, and shared labels.</Typography>
        </Stack>
        <ToggleButtonGroup exclusive fullWidth value={mode} onChange={(_, value) => value && setMode(value)} sx={{ mb: 2.7 }}>
          <ToggleButton value="login" sx={{ textTransform: "none", fontWeight: 700 }}>Sign in</ToggleButton>
          <ToggleButton value="signup" sx={{ textTransform: "none", fontWeight: 700 }}>Create account</ToggleButton>
        </ToggleButtonGroup>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Box component="form" onSubmit={submit}>
          <Stack gap={1.8}>
            {mode === "signup" && <TextField label="Name" value={name} onChange={event => setName(event.target.value)} autoComplete="name" required fullWidth />}
            <TextField label="Email" type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="email" required fullWidth />
            <TextField label="Password" type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete={mode === "signup" ? "new-password" : "current-password"} required fullWidth inputProps={{ minLength: 8 }} helperText={mode === "signup" ? "Use at least 8 characters." : undefined} />
            <Button type="submit" variant="contained" size="large" disabled={busy || (mode === "signup" && password.length < 8)} sx={{ mt: .4, py: 1.2, fontWeight: 750, textTransform: "none" }}>
              {busy ? <CircularProgress size={22} color="inherit" /> : mode === "signup" ? "Create local account" : "Sign in"}
            </Button>
          </Stack>
        </Box>
        <Divider sx={{ my: 2.3 }} />
        <Typography color="text.secondary" sx={{ fontSize: 13, textAlign: "center" }}>The first account in a new workspace becomes its administrator. No model runs start automatically.</Typography>
      </Paper>
    </Container>
  </Box>;
}
