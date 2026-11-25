import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "dockview-react/dist/styles/dockview.css";
import "./theme/tokens.css";
import "./workbench.css";
import { applyTheme, storedTheme } from "./theme/theme";
import { Workbench } from "./Workbench";

applyTheme(storedTheme());

// Server state goes through TanStack Query (decisions/0012); a refusal is shown, not retried.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <Workbench />
      </QueryClientProvider>
    </StrictMode>,
  );
}
