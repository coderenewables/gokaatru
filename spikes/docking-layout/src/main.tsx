import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { spike } from "./panels";
import DockviewApp from "./dockview";
import FlexApp from "./flexlayout";

const lib = new URLSearchParams(location.search).get("lib");
spike.lib = lib ?? "";
createRoot(document.getElementById("root")!).render(
  <StrictMode>{lib === "flexlayout" ? <FlexApp /> : lib === "dockview" ? <DockviewApp /> : <div>?lib=dockview|flexlayout</div>}</StrictMode>,
);
