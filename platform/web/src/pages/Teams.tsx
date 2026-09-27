import { useState } from "react";
import { useGetIdentity } from "react-admin";
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, Grid, IconButton, MenuItem, Select, Stack, Switch, TextField, Typography } from "@mui/material";
import AddRounded from "@mui/icons-material/AddRounded";
import PersonAddAlt1Rounded from "@mui/icons-material/PersonAddAlt1Rounded";
import DeleteOutlineRounded from "@mui/icons-material/DeleteOutlineRounded";
import { apiRequest } from "../api";
import { useResourceList } from "../hooks";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel, SectionTitle, StatusTag } from "../components";

interface Member { id?: string; user_id?: string; name?: string; email?: string; role?: string; active?: boolean; [key: string]: unknown }
interface Team { id: string; name: string; description?: string; members?: Member[]; [key: string]: unknown }
interface UserRow { id: string; name?: string; email?: string; role?: string; active?: boolean; [key: string]: unknown }

export function TeamsPage() {
  const teams = useResourceList<Team>("teams");
  const users = useResourceList<UserRow>("users");
  const identity = useGetIdentity();
  const isAdmin = identity.data?.role === "admin" || identity.data?.role === "workspace_admin";
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [targetByTeam, setTargetByTeam] = useState<Record<string, string>>({});

  const create = async () => {
    setBusy("create"); setError("");
    try { await apiRequest("/teams", { method: "POST", body: JSON.stringify({ name: name.trim(), description: description.trim() }) }); setCreateOpen(false); setName(""); setDescription(""); teams.reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Team could not be created."); }
    finally { setBusy(""); }
  };
  const addMember = async (teamId: string) => {
    const userId = targetByTeam[teamId];
    if (!userId) return;
    setBusy(`add:${teamId}`); setError("");
    try { await apiRequest(`/teams/${encodeURIComponent(teamId)}/members`, { method: "POST", body: JSON.stringify({ user_id: userId }) }); setTargetByTeam(current => ({ ...current, [teamId]: "" })); teams.reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Member could not be added."); }
    finally { setBusy(""); }
  };
  const removeMember = async (teamId: string, userId: string) => {
    setBusy(`remove:${teamId}:${userId}`); setError("");
    try { await apiRequest(`/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}`, { method: "DELETE" }); teams.reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Member could not be removed."); }
    finally { setBusy(""); }
  };
  const updateUser = async (user: UserRow, patch: Partial<UserRow>) => {
    setBusy(`user:${user.id}`); setError("");
    try { await apiRequest(`/users/${encodeURIComponent(user.id)}`, { method: "PATCH", body: JSON.stringify(patch) }); users.reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "User access could not be updated."); }
    finally { setBusy(""); }
  };

  return <>
    <PageHeader eyebrow="WORKSPACE ACCESS" title="Teams" description="Organize workspace members and manage run-scoped access. Team membership alone does not share datasets or run results." action={<Button variant="contained" startIcon={<AddRounded />} onClick={() => { setError(""); setCreateOpen(true); }}>New team</Button>} />
    {error && <Alert severity="error" onClose={() => setError("")} sx={{ mb: 2 }}>{error}</Alert>}
    {teams.loading && <LoadingState label="Loading teams…" />}
    {teams.error && <ErrorState message={teams.error} onRetry={teams.reload} />}
    {!teams.loading && !teams.error && !teams.data.length && <EmptyState title="No teams created" description="Create a team, then add existing workspace users. Run access remains separately scoped." action={<Button variant="contained" onClick={() => setCreateOpen(true)}>Create a team</Button>} />}
    {!!teams.data.length && <Grid container spacing={1.8} alignItems="flex-start">{teams.data.map(team => {
      const members = team.members || [];
      const available = users.data.filter(user => !members.some(member => String(member.user_id || member.id) === String(user.id)));
      return <Grid key={team.id} size={{ xs: 12, md: 6, xl: 4 }}><Panel>
        <Stack direction="row" justifyContent="space-between" gap={1}><Box sx={{ minWidth: 0 }}><Typography sx={{ fontSize: 15, fontWeight: 700, overflowWrap: "anywhere" }}>{team.name}</Typography><Typography color="text.secondary" sx={{ mt: .5, fontSize: 14 }}>{team.description || "No description recorded."}</Typography></Box><StatusTag value={`${members.length} members`} /></Stack>
        <SectionTitle title="Members" subtitle="Workspace membership" />
        <Stack gap={.75} sx={{ mb: 1.8 }}>{members.map((member, index) => { const userId = String(member.user_id || member.id || ""); return <Stack key={userId || index} direction="row" justifyContent="space-between" alignItems="center" gap={1} sx={{ p: 1, border: "1px solid", borderColor: "divider", borderRadius: 2 }}><Box sx={{ minWidth: 0 }}><Typography sx={{ fontWeight: 700, fontSize: 13, overflowWrap: "anywhere" }}>{member.name || member.email || userId}</Typography><Typography color="text.secondary" sx={{ fontSize: 12, overflowWrap: "anywhere" }}>{member.email || userId} · {member.role || "workspace member"}</Typography></Box><IconButton aria-label={`Remove ${member.name || member.email || userId} from ${team.name}`} size="small" color="error" disabled={!isAdmin || busy === `remove:${team.id}:${userId}`} onClick={() => void removeMember(team.id, userId)}><DeleteOutlineRounded fontSize="small" /></IconButton></Stack>; })}{!members.length && <Typography color="text.secondary" sx={{ fontSize: 14 }}>No members yet.</Typography>}</Stack>
        <Stack direction={{ xs: "column", sm: "row" }} gap={1}>
          <FormControl size="small" fullWidth><Select displayEmpty value={targetByTeam[team.id] || ""} onChange={event => setTargetByTeam(current => ({ ...current, [team.id]: event.target.value }))}><MenuItem value=""><em>Select a workspace user</em></MenuItem>{available.map(user => <MenuItem key={user.id} value={user.id}>{user.name || user.email} · {user.role || "viewer"}</MenuItem>)}</Select></FormControl>
          <Button variant="outlined" startIcon={<PersonAddAlt1Rounded />} disabled={!isAdmin || !targetByTeam[team.id] || busy === `add:${team.id}`} onClick={() => void addMember(team.id)}>Add</Button>
        </Stack>
        {!isAdmin && <Typography color="text.secondary" sx={{ mt: 1, fontSize: 12 }}>Your role does not allow membership changes.</Typography>}
      </Panel></Grid>;
    })}</Grid>}
    {isAdmin && <Panel sx={{ mt: 2.5 }}><SectionTitle title="Workspace users" subtitle="Administrators can change workspace role or deactivate access. Team and run grants remain independent." />
      {users.loading && <LoadingState label="Loading users…" />}{users.error && <ErrorState message={users.error} onRetry={users.reload} />}
      {!!users.data.length && <Stack divider={<Box sx={{ borderBottom: "1px solid", borderColor: "divider" }} />}>
        {users.data.map(user => <Stack key={user.id} direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} gap={1} sx={{ py: 1.1 }}><Box sx={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}><Typography sx={{ fontWeight: 700 }}>{user.name || user.email}</Typography><Typography color="text.secondary" sx={{ fontSize: 13 }}>{user.email}</Typography></Box><FormControl size="small" sx={{ minWidth: 160 }}><Select aria-label={`Role for ${user.email}`} value={user.role || "viewer"} disabled={busy === `user:${user.id}`} onChange={event => void updateUser(user, { role: event.target.value })}><MenuItem value="admin">Administrator</MenuItem><MenuItem value="manager">Manager</MenuItem><MenuItem value="reviewer">Reviewer</MenuItem><MenuItem value="viewer">Viewer</MenuItem></Select></FormControl><Stack direction="row" alignItems="center"><Typography sx={{ fontSize: 13 }}>Active</Typography><Switch checked={user.active !== false} disabled={busy === `user:${user.id}`} onChange={event => void updateUser(user, { active: event.target.checked })} inputProps={{ "aria-label": `Active status for ${user.email}` }} /></Stack></Stack>)}
      </Stack>}
    </Panel>}
    <Dialog open={createOpen} onClose={() => busy !== "create" && setCreateOpen(false)} fullWidth maxWidth="sm"><DialogTitle>Create a team</DialogTitle><DialogContent><Stack gap={2} sx={{ pt: 1 }}>{error && <Alert severity="error">{error}</Alert>}<TextField autoFocus label="Team name" required value={name} onChange={event => setName(event.target.value)} /><TextField label="Description" multiline minRows={2} value={description} onChange={event => setDescription(event.target.value)} /></Stack></DialogContent><DialogActions sx={{ px: 3, pb: 2.5 }}><Button onClick={() => setCreateOpen(false)}>Cancel</Button><Button variant="contained" disabled={!name.trim() || busy === "create"} onClick={create}>Create team</Button></DialogActions></Dialog>
  </>;
}
