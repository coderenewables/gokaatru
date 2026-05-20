import { useMemo, useState } from "react";

import { paletteGroups, type NodePaletteGroup } from "../../lib/nodeRegistry";
import { useWorkflowUiStore } from "../../stores/workflowUiStore";
import { useWorkflowStore } from "../../stores/workflowStore";
import { useLocation } from "react-router-dom";

type PaletteSection = {
  id: "core" | "windkit";
  label: string;
  description: string;
};

const paletteSections: PaletteSection[] = [
  {
    id: "core",
    label: "Core Tools",
    description: "GoKaatru-native analysis and workflow operations.",
  },
  {
    id: "windkit",
    label: "WindKit Tools",
    description: "Full WindKit catalog grouped by domain.",
  },
];

const defaultExpandedGroupIds = new Set<string>(["core-dataset-source", "core-data-cleaning"]);

function buildGroupsBySection(groups: NodePaletteGroup[]): Record<PaletteSection["id"], NodePaletteGroup[]> {
  return {
    core: groups.filter((group) => group.accent === "core"),
    windkit: groups.filter((group) => group.accent === "windkit"),
  };
}

const CANVAS_PATHS = new Set(["/overview", "/brighthub", "/data", "/reanalysis", "/site", "/ltc", "/results"]);

type NodePaletteProps = {
  defaultBrightHubUuid?: string | null;
};

export function NodePalette({ defaultBrightHubUuid = null }: NodePaletteProps) {
  const activeBranchId = useWorkflowUiStore((state) => state.activeBranchId);
  const setSelectedNodeId = useWorkflowUiStore((state) => state.setSelectedNodeId);
  const addOperationNode = useWorkflowStore((state) => state.addOperationNode);
  const groupsBySection = useMemo(() => buildGroupsBySection(paletteGroups), []);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(defaultExpandedGroupIds));
  const [search, setSearch] = useState("");
  const location = useLocation();

  // Show palette on all workflow pages but contextualise the header hint
  const isCanvasPage = CANVAS_PATHS.has(location.pathname) || location.pathname === "/";
  const dragHint = "Click or drag into canvas";

  if (!isCanvasPage) return null;

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return paletteGroups;
    return paletteGroups
      .map((group) => ({
        ...group,
        items: group.items.filter(
          (item) =>
            item.label.toLowerCase().includes(q) ||
            item.category.toLowerCase().includes(q) ||
            group.label.toLowerCase().includes(q),
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [search]);

  const filteredGroupsBySection = useMemo(() => buildGroupsBySection(filteredGroups), [filteredGroups]);

  const expandAll = () => {
    setExpandedGroups(new Set(paletteGroups.map((group) => group.id)));
  };

  const collapseAll = () => {
    setExpandedGroups(new Set());
  };

  const toggleGroup = (groupId: string) => {
    setExpandedGroups((previous) => {
      const next = new Set(previous);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

  return (
    <section className="workflow-panel-card">
      <div className="workflow-panel-header">
        <div>
          <span className="eyebrow">Node palette</span>
          <h2>{dragHint}</h2>
        </div>
        <span className="workflow-phase-chip">{paletteGroups.length} groups</span>
      </div>
      <div className="workflow-palette-search">
        <input
          type="search"
          className="workflow-palette-search-input"
          placeholder="Search nodes…"
          aria-label="Search nodes"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            if (e.target.value.trim()) {
              setExpandedGroups(new Set(paletteGroups.map((g) => g.id)));
            }
          }}
        />
      </div>
      <div className="workflow-palette-toolbar">
        <button className="ghost-button" type="button" onClick={expandAll}>
          Expand all
        </button>
        <button className="ghost-button" type="button" onClick={collapseAll}>
          Collapse all
        </button>
      </div>
      <div className="workflow-palette-scroll">
        {search.trim() && filteredGroups.length === 0 && (
          <p className="workflow-palette-no-results">No nodes match "{search}"</p>
        )}
        {paletteSections.map((section) => {
          const sectionGroups = search.trim() ? filteredGroupsBySection[section.id] : groupsBySection[section.id];
          if (sectionGroups.length === 0) {
            return null;
          }

          const sectionNodeCount = sectionGroups.reduce((total, group) => total + group.items.length, 0);

          return (
            <section key={section.id} className="workflow-palette-section">
              <header className="workflow-palette-section-header">
                <div>
                  <h3>{section.label}</h3>
                  <p>{section.description}</p>
                </div>
                <span className="workflow-phase-chip">{sectionNodeCount} nodes</span>
              </header>

              <div className="workflow-palette-groups">
                {sectionGroups.map((group) => {
                  const isExpanded = expandedGroups.has(group.id);

                  return (
                    <article
                      key={group.id}
                      className={`workflow-palette-group ${isExpanded ? "" : "workflow-palette-group-collapsed"}`}
                    >
                      <button
                        type="button"
                        className="workflow-palette-group-toggle"
                        onClick={() => toggleGroup(group.id)}
                        aria-expanded={isExpanded ? "true" : "false"}
                        aria-controls={`palette-group-${group.id}`}
                      >
                        <span className="workflow-palette-group-title">{group.label}</span>
                        <span className="workflow-palette-group-count">
                          {group.items.length} {group.items.length === 1 ? "node" : "nodes"} {isExpanded ? "-" : "+"}
                        </span>
                      </button>

                      {isExpanded ? (
                        <div id={`palette-group-${group.id}`} className="workflow-palette-group-body">
                          <p>{group.description}</p>
                          <div className="workflow-palette-items">
                            {group.items.map((item) => (
                              <button
                                key={item.id}
                                type="button"
                                className="workflow-palette-item"
                                draggable
                                onClick={() => setSelectedNodeId(addOperationNode(activeBranchId, item.id, undefined, defaultBrightHubUuid))}
                                onDragStart={(event) => {
                                  event.dataTransfer.setData("application/gokaatru-node-template", item.id);
                                  event.dataTransfer.effectAllowed = "move";
                                }}
                              >
                                <strong>{item.label}</strong>
                                <span>{item.category}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}