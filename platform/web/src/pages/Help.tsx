import { isValidElement, useEffect, useMemo, type ReactNode } from "react";
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Box, Button, Grid, Link as MuiLink, Stack, Typography } from "@mui/material";
import { EmptyState, PageHeader, Panel, SectionTitle } from "../components";
import gettingStarted from "../docs/getting-started.md?raw";
import rolesTeams from "../docs/roles-teams.md?raw";
import datasets from "../docs/datasets.md?raw";
import batches from "../docs/batches.md?raw";
import reviewing from "../docs/reviewing.md?raw";

const guides = [
  { slug: "getting-started", title: "Getting started", markdown: gettingStarted },
  { slug: "roles-teams", title: "Roles and teams", markdown: rolesTeams },
  { slug: "datasets", title: "Datasets and ZIP imports", markdown: datasets },
  { slug: "batches", title: "Runs and progress", markdown: batches },
  { slug: "reviewing", title: "Trajectories and taxonomy", markdown: reviewing },
] as const;

function slugify(value: string): string {
  return value.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9\s-]/g, "").trim().replace(/[\s-]+/g, "-");
}

function plainText(children: ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(plainText).join("");
  if (isValidElement<{ children?: ReactNode }>(children)) return plainText(children.props.children);
  return "";
}

function headingsFrom(markdown: string) {
  return markdown.split("\n").flatMap(line => {
    const match = /^(#{2,3})\s+(.+?)\s*#*\s*$/.exec(line);
    return match ? [{ level: match[1].length, title: match[2], id: slugify(match[2]) }] : [];
  });
}

export function HelpPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const guide = guides.find(item => item.slug === slug) || guides[0];
  const section = searchParams.get("section") || "";
  const headings = useMemo(() => headingsFrom(guide.markdown), [guide.markdown]);

  const goToHeading = (id: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("section", id);
    setSearchParams(next, { preventScrollReset: true });
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  useEffect(() => {
    if (slug && !guides.some(item => item.slug === slug)) navigate("/docs/getting-started", { replace: true });
  }, [navigate, slug]);

  useEffect(() => {
    if (!section) return;
    requestAnimationFrame(() => document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [guide.slug, section]);

  const markdownComponents: Components = {
    h1: ({ children }) => <Typography component="h1" variant="h2" id={slugify(plainText(children))} sx={{ mb: 2 }}>{children}</Typography>,
    h2: ({ children }) => <Typography component="h2" variant="h3" id={slugify(plainText(children))} sx={{ mt: 3.5, mb: 1.2, scrollMarginTop: 96 }}>{children}</Typography>,
    h3: ({ children }) => <Typography component="h3" id={slugify(plainText(children))} sx={{ mt: 2.7, mb: 1, fontSize: 16, fontWeight: 750, scrollMarginTop: 96 }}>{children}</Typography>,
    p: ({ children }) => <Typography component="p" sx={{ mt: 0, mb: 1.5, lineHeight: 1.7 }}>{children}</Typography>,
    ul: ({ children }) => <Box component="ul" sx={{ pl: 3, mt: -.3, mb: 1.8, "& li": { mb: .7, lineHeight: 1.65 } }}>{children}</Box>,
    ol: ({ children }) => <Box component="ol" sx={{ pl: 3, mt: -.3, mb: 1.8, "& li": { mb: .7, lineHeight: 1.65 } }}>{children}</Box>,
    blockquote: ({ children }) => <Box component="blockquote" sx={{ ml: 0, my: 2, pl: 2, borderLeft: "3px solid", borderColor: "primary.main", color: "text.secondary" }}>{children}</Box>,
    code: ({ children }) => <Box component="code" sx={{ px: .5, py: .1, borderRadius: .7, bgcolor: "action.hover", color: "text.primary", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: ".9em" }}>{children}</Box>,
    pre: ({ children }) => <Box component="pre" sx={{ p: 1.8, my: 2, overflow: "auto", borderRadius: 2, border: "1px solid", borderColor: "divider", bgcolor: "action.hover", color: "text.primary", fontSize: 13, lineHeight: 1.55, "& code": { p: 0, bgcolor: "transparent", fontSize: "inherit" } }}>{children}</Box>,
    a: ({ href, children }) => {
      const internalHeading = href?.startsWith("#");
      return <MuiLink href={href || "#"} target={internalHeading ? undefined : "_blank"} rel={internalHeading ? undefined : "noopener noreferrer"} onClick={event => {
        if (internalHeading) {
          event.preventDefault();
          goToHeading(decodeURIComponent(href?.slice(1) || ""));
        }
      }}>{children}</MuiLink>;
    },
    table: ({ children }) => <Box sx={{ overflowX: "auto", mb: 2 }}><Box component="table" sx={{ width: "100%", borderCollapse: "collapse", "& th, & td": { border: "1px solid", borderColor: "divider", p: 1, textAlign: "left" }, "& th": { bgcolor: "action.hover", fontWeight: 750 } }}>{children}</Box></Box>,
  };

  if (!guide) return <EmptyState title="Guide not found" description="Choose a topic from the Help and guides menu." action={<Button component={RouterLink} to="/docs/getting-started">Open getting started</Button>} />;

  return <>
    <PageHeader eyebrow="HELP CENTER" title="User guide" description="Practical guidance for importing saved evidence, managing review work, and understanding access." />
    <Grid container spacing={2} alignItems="flex-start">
      <Grid size={{ xs: 12, md: 3 }} sx={{ alignSelf: { md: "stretch" }, minWidth: 0 }}>
        <Stack gap={1.5} sx={{ position: { md: "sticky" }, top: { md: 16 }, alignSelf: "flex-start", maxHeight: { md: "calc(100vh - 32px)" }, overflowY: { md: "auto" } }}>
          <Panel sx={{ p: 1.5 }}>
            <SectionTitle title="Topics" />
            <Stack component="nav" aria-label="Help topics" gap={.4}>
              {guides.map(item => <Button key={item.slug} component={RouterLink} to={`/docs/${item.slug}`} fullWidth variant={guide.slug === item.slug ? "contained" : "text"} color={guide.slug === item.slug ? "primary" : "inherit"} sx={{ justifyContent: "flex-start", textAlign: "left", px: 1.2 }}>{item.title}</Button>)}
            </Stack>
          </Panel>
          {!!headings.length && <Panel sx={{ p: 1.5 }}>
            <SectionTitle title="On this page" />
            <Stack component="nav" aria-label="Headings in this guide" gap={.2}>
              {headings.map(item => <MuiLink key={item.id} href={`#${item.id}`} underline="hover" color={section === item.id ? "primary.main" : "text.secondary"} aria-current={section === item.id ? "location" : undefined} onClick={event => { event.preventDefault(); goToHeading(item.id); }} sx={{ display: "block", py: .4, pl: item.level === 3 ? 1.5 : 0, fontSize: 13, lineHeight: 1.4 }}>{item.title}</MuiLink>)}
            </Stack>
          </Panel>}
        </Stack>
      </Grid>
      <Grid size={{ xs: 12, md: 9 }}>
        <Panel>
          <Box className="help-article">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{guide.markdown}</ReactMarkdown>
          </Box>
        </Panel>
      </Grid>
    </Grid>
  </>;
}
