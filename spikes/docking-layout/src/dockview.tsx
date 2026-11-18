import { DockviewReact, type DockviewReadyEvent, type IDockviewPanelProps, type DockviewApi } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { ChartPanel, Placeholder, spike } from "./panels";

const KEY = "spike-layout-dockview";
const components = {
  chart: () => <ChartPanel />,
  ph: (p: IDockviewPanelProps<{ name: string }>) => <Placeholder name={p.params.name} />,
};

function groupsOf(api: DockviewApi): string[][] {
  return api.groups.map((g) => g.panels.map((p) => p.id));
}

function onReady(e: DockviewReadyEvent) {
  const api = e.api;
  let saved: string | null = null;
  try {
    saved = localStorage.getItem(KEY);
  } catch {
    /* none */
  }
  if (saved) api.fromJSON(JSON.parse(saved));
  else {
    api.addPanel({ id: "chart", component: "chart", title: "Timeline" });
    api.addPanel({ id: "tree", component: "ph", title: "Data tree", params: { name: "tree" }, position: { referencePanel: "chart", direction: "within" } });
    api.addPanel({ id: "inspector", component: "ph", title: "Inspector", params: { name: "inspector" }, position: { referencePanel: "chart", direction: "right" } });
    api.addPanel({ id: "rose", component: "ph", title: "Wind rose", params: { name: "rose" }, position: { referencePanel: "inspector", direction: "below" } });
    api.getPanel("chart")!.api.setActive();
  }
  api.onDidLayoutChange(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(api.toJSON()));
    } catch {
      /* none */
    }
  });
  Object.assign(spike, {
    api,
    groups: () => groupsOf(api),
    serialize: () => JSON.stringify(api.toJSON()),
    floatChart: () => {
      api.addFloatingGroup(api.getPanel("chart")!, { position: { left: 100, top: 100 }, width: 500, height: 300 });
    },
    popoutChart: () => api.addPopoutGroup(api.getPanel("chart")!.group, { popoutUrl: "/popout.html" }),
  });
}

export default function DockviewApp() {
  return (
    <div style={{ height: "100vh", width: "100vw" }}>
      <DockviewReact className="dockview-theme-abyss" components={components} onReady={onReady} />
    </div>
  );
}
