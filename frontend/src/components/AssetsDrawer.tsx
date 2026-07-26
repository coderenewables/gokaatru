// Collapsible Assets drawer (spec §3.1).
//
// Renders normalized assets grouped by kind, each expandable to show its raw
// payload. Mounted on the right side of the workspace body.
import { useState } from "react";
import clsx from "clsx";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import type { NormalizedAsset } from "../lib/normalization";

interface AssetsDrawerProps {
  open: boolean;
  onToggle: () => void;
}

const KIND_LABEL: Record<NormalizedAsset["kind"], string> = {
  config: "Configuration",
  summary: "Summary",
  sensor_inventory: "Sensors",
  dataset_preview: "Dataset preview",
  operation_result: "Operation results",
  plot: "Plots",
};

export function AssetsDrawer({ open, onToggle }: AssetsDrawerProps) {
  const assets = useWorkspaceStore((state) => state.assets);

  // Group by kind, preserving the canonical order.
  const grouped = assets.reduce<Record<string, NormalizedAsset[]>>((acc, asset) => {
    (acc[asset.kind] ??= []).push(asset);
    return acc;
  }, {});
  const kinds = Object.keys(grouped);

  return (
    <aside className={clsx("assets-drawer", { open })}>
      <button type="button" className="assets-drawer-toggle" onClick={onToggle}>
        {open ? "Hide assets ▸" : "◂ Show assets"}
      </button>
      {open ? (
        <div className="assets-drawer-body">
          {kinds.length === 0 ? (
            <p className="muted">No assets yet.</p>
          ) : (
            kinds.map((kind) => (
              <AssetGroup key={kind} kind={kind as NormalizedAsset["kind"]} items={grouped[kind]} />
            ))
          )}
        </div>
      ) : null}
    </aside>
  );
}

function AssetGroup({ kind, items }: { kind: NormalizedAsset["kind"]; items: NormalizedAsset[] }) {
  return (
    <section className="asset-group">
      <h4>{KIND_LABEL[kind]}</h4>
      <ul className="asset-list">
        {items.map((asset) => (
          <AssetItem key={asset.id} asset={asset} />
        ))}
      </ul>
    </section>
  );
}

function AssetItem({ asset }: { asset: NormalizedAsset }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="asset-item">
      <button
        type="button"
        className="asset-item-head"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className="asset-item-label">{asset.label}</span>
        <span className="asset-item-summary muted">{asset.summary}</span>
        <span className="asset-item-caret">{expanded ? "▾" : "▸"}</span>
      </button>
      {expanded ? (
        <pre className="asset-item-payload">{JSON.stringify(asset.payload, null, 2)}</pre>
      ) : null}
    </li>
  );
}
