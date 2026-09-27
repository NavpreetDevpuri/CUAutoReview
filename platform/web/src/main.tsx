import React from "react";
import ReactDOM from "react-dom/client";
import { Admin, CustomRoutes, Resource } from "react-admin";
import { Route } from "react-router-dom";
import { authProvider, dataProvider } from "./api";
import { WorkspaceLayout } from "./layout";
import { AccessPage } from "./auth";
import { HelpPage } from "./pages/Help";
import { ThemeModeProvider, useThemeMode } from "./theme";
import { OverviewPage } from "./pages/Overview";
import { DatasetsPage, DatasetDetailPage } from "./pages/Datasets";
import { BatchesPage, BatchDetailPage } from "./pages/Batches";
import { DatasetTaskPage } from "./pages/DatasetTask";
import { TrajectoryPage } from "./pages/Trajectory";
import { TeamsPage } from "./pages/Teams";
import { PresetsPage } from "./pages/Presets";
import { TaxonomyPage, CandidatePage } from "./pages/Taxonomy";
import { ActivityPage, JobDetailPage, JobsPage } from "./pages/Activity";
import { AnalyticsPage } from "./pages/Analytics";
import { ComparePage } from "./pages/Compare";
import "./styles.css";

function App() {
  const { theme } = useThemeMode();
  return <Admin theme={theme} dataProvider={dataProvider} authProvider={authProvider} layout={WorkspaceLayout} loginPage={AccessPage} dashboard={OverviewPage} title="CUAutoReview">
    <Resource name="datasets" list={DatasetsPage} />
    <Resource name="runs" list={BatchesPage} />
    <Resource name="batches" list={BatchesPage} />
    <Resource name="teams" list={TeamsPage} />
    <Resource name="presets" list={PresetsPage} />
    <Resource name="taxonomy" list={TaxonomyPage} />
    <Resource name="activity" list={ActivityPage} />
    <Resource name="jobs" list={JobsPage} />
    <CustomRoutes>
      <Route path="/datasets/:id" element={<DatasetDetailPage />} />
      <Route path="/datasets/:id/tasks/:taskId" element={<DatasetTaskPage />} />
      <Route path="/runs/:id" element={<BatchDetailPage />} />
      <Route path="/runs/:id/tasks/:taskId" element={<TrajectoryPage />} />
      <Route path="/jobs/:id" element={<JobDetailPage />} />
      <Route path="/analytics" element={<AnalyticsPage />} />
      <Route path="/compare" element={<ComparePage />} />
      <Route path="/batches/:id" element={<BatchDetailPage />} />
      <Route path="/batches/:id/tasks/:taskId" element={<TrajectoryPage />} />
      <Route path="/taxonomy/candidates/:id" element={<CandidatePage />} />
      <Route path="/help" element={<HelpPage />} />
      <Route path="/docs/:slug" element={<HelpPage />} />
    </CustomRoutes>
  </Admin>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><ThemeModeProvider><App /></ThemeModeProvider></React.StrictMode>);
