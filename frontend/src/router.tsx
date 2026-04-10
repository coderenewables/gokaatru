import { Suspense, lazy } from "react";

import { Navigate, createBrowserRouter } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { LoadingState } from "./components/common/LoadingState";

const OverviewPage = lazy(async () => ({ default: (await import("./pages/OverviewPage")).OverviewPage }));
const BrightHubPage = lazy(async () => ({ default: (await import("./pages/BrightHubPage")).BrightHubPage }));
const DataPage = lazy(async () => ({ default: (await import("./pages/DataPage")).DataPage }));
const SitePage = lazy(async () => ({ default: (await import("./pages/SitePage")).SitePage }));
const ReanalysisPage = lazy(async () => ({ default: (await import("./pages/ReanalysisPage")).ReanalysisPage }));
const LtcPage = lazy(async () => ({ default: (await import("./pages/LtcPage")).LtcPage }));
const ResultsPage = lazy(async () => ({ default: (await import("./pages/ResultsPage")).ResultsPage }));
const ChatPage = lazy(async () => ({ default: (await import("./pages/ChatPage")).ChatPage }));

function LazyPage({ component: Component }: { component: React.ComponentType }) {
  return (
    <Suspense fallback={<LoadingState label="Loading page" />}>
      <Component />
    </Suspense>
  );
}

export const appRouter = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: "overview", element: <LazyPage component={OverviewPage} /> },
      { path: "brighthub", element: <LazyPage component={BrightHubPage} /> },
      { path: "data", element: <LazyPage component={DataPage} /> },
      { path: "site", element: <LazyPage component={SitePage} /> },
      { path: "reanalysis", element: <LazyPage component={ReanalysisPage} /> },
      { path: "ltc", element: <LazyPage component={LtcPage} /> },
      { path: "results", element: <LazyPage component={ResultsPage} /> },
      { path: "chat", element: <LazyPage component={ChatPage} /> },
    ],
  },
]);
