import { Layout, Model, Actions, type TabNode, type IJsonModel } from "flexlayout-react";
import "flexlayout-react/style/light.css";
import { useRef } from "react";
import { ChartPanel, Placeholder, spike } from "./panels";

const KEY = "spike-layout-flexlayout";
const defaultJson: IJsonModel = {
  global: { tabEnablePopout: true, tabEnableFloat: true },
  layout: {
    type: "row",
    weight: 100,
    children: [
      {
        type: "tabset",
        weight: 60,
        selected: 0,
        children: [
          { type: "tab", id: "chart", name: "Timeline", component: "chart" },
          { type: "tab", id: "tree", name: "Data tree", component: "ph" },
        ],
      },
      {
        type: "row",
        weight: 40,
        children: [
          { type: "tabset", weight: 50, children: [{ type: "tab", id: "inspector", name: "Inspector", component: "ph" }] },
          { type: "tabset", weight: 50, children: [{ type: "tab", id: "rose", name: "Wind rose", component: "ph" }] },
        ],
      },
    ],
  },
};

function load(): Model {
  try {
    const s = localStorage.getItem(KEY);
    if (s) return Model.fromJson(JSON.parse(s));
  } catch {
    /* fall through */
  }
  return Model.fromJson(defaultJson);
}

function groupsOf(model: Model): string[][] {
  const out: string[][] = [];
  model.visitNodes((n) => {
    if (n.getType() === "tabset") out.push(n.getChildren().map((c) => c.getId()));
  });
  return out;
}

export default function FlexApp() {
  const model = useRef<Model>(null as unknown as Model);
  if (!model.current) {
    model.current = load();
    const m = model.current;
    Object.assign(spike, {
      model: m,
      groups: () => groupsOf(m),
      serialize: () => JSON.stringify(m.toJson()),
      floatChart: () => {
        m.doAction(Actions.popoutTab("chart", "float"));
      },
      popoutChart: () => m.doAction(Actions.popoutTab("chart", "window")),
    });
  }
  const factory = (node: TabNode) => {
    const c = node.getComponent();
    if (c === "chart") return <ChartPanel />;
    return <Placeholder name={node.getId()} />;
  };
  return (
    <div style={{ position: "relative", height: "100vh", width: "100vw" }}>
      <Layout
        model={model.current}
        factory={factory}
        onModelChange={(m) => {
          try {
            localStorage.setItem(KEY, JSON.stringify(m.toJson()));
          } catch {
            /* none */
          }
        }}
      />
    </div>
  );
}
