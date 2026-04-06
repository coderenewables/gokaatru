import { Navigate, createBrowserRouter } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { DataPage } from "./pages/DataPage";
import { LtcPage } from "./pages/LtcPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReanalysisPage } from "./pages/ReanalysisPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SitePage } from "./pages/SitePage";

export const appRouter = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "data", element: <DataPage /> },
      { path: "site", element: <SitePage /> },
      { path: "reanalysis", element: <ReanalysisPage /> },
      { path: "ltc", element: <LtcPage /> },
      { path: "results", element: <ResultsPage /> },
    ],
  },
]);
