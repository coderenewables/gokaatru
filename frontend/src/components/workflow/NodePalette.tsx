import { useMemo, useState } from "react";

import { paletteGroups, type NodePaletteGroup } from "../../lib/nodeRegistry";
import { useWorkflowStore } from "../../stores/workflowStore";

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

export function NodePalette() {
  const addOperationNode = useWorkflowStore((state) => state.addOperationNode);
  const groupsBySection = useMemo(() => buildGroupsBySection(paletteGroups), []);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(defaultExpandedGroupIds));

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
          <h2>Drag into canvas</h2>
        </div>
        <span className="workflow-phase-chip">{paletteGroups.length} groups</span>
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
        {paletteSections.map((section) => {
          const sectionGroups = groupsBySection[section.id];
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
                        aria-expanded={isExpanded}
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
                                onClick={() => addOperationNode(item.id)}
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