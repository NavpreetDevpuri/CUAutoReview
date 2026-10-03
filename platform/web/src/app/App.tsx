import { lazy } from "react";
import { Admin, CustomRoutes, Resource } from "react-admin";
import { Route } from "react-router-dom";
import { authProvider, dataProvider } from "../api/client";
import { AccessPage } from "./AccessPage";
import { useThemeMode } from "./theme";
import { WorkspaceLayout } from "./WorkspaceLayout";

// Pages load on first visit; WorkspaceLayout supplies the Suspense fallback. Sign-in stays in the main bundle.
const HelpPage = lazy(() => import("../pages/Help").then(module => ({ default: module.HelpPage })));
const OverviewPage = lazy(() => import("../pages/Overview").then(module => ({ default: module.OverviewPage })));
const DatasetsPage = lazy(() => import("../pages/Datasets").then(module => ({ default: module.DatasetsPage })));
const DatasetDetailPage = lazy(() => import("../pages/Datasets").then(module => ({ default: module.DatasetDetailPage })));
const BatchesPage = lazy(() => import("../pages/Batches").then(module => ({ default: module.BatchesPage })));
const BatchDetailPage = lazy(() => import("../pages/Batches").then(module => ({ default: module.BatchDetailPage })));
const DatasetTaskPage = lazy(() => import("../pages/DatasetTask").then(module => ({ default: module.DatasetTaskPage })));
const TrajectoryPage = lazy(() => import("../pages/trajectory/TrajectoryPage").then(module => ({ default: module.TrajectoryPage })));
const TeamsPage = lazy(() => import("../pages/Teams").then(module => ({ default: module.TeamsPage })));
const PresetsPage = lazy(() => import("../pages/Presets").then(module => ({ default: module.PresetsPage })));
const TaxonomyPage = lazy(() => import("../pages/Taxonomy").then(module => ({ default: module.TaxonomyPage })));
const CandidatePage = lazy(() => import("../pages/Taxonomy").then(module => ({ default: module.CandidatePage })));
const ActivityPage = lazy(() => import("../pages/Activity").then(module => ({ default: module.ActivityPage })));
const JobDetailPage = lazy(() => import("../pages/Activity").then(module => ({ default: module.JobDetailPage })));
const JobsPage = lazy(() => import("../pages/Activity").then(module => ({ default: module.JobsPage })));
const AnalyticsPage = lazy(() => import("../pages/Analytics").then(module => ({ default: module.AnalyticsPage })));
const ComparePage = lazy(() => import("../pages/Compare").then(module => ({ default: module.ComparePage })));

export function App() {
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
