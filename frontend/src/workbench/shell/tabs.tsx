import type { IDockviewHeaderActionsProps, IDockviewPanelHeaderProps } from "dockview-react";
import { useEffect, useState } from "react";

/** The tab: its title only. Dockview's own tab element carries role="tab", so a close
 * button inside it is an interactive control nested in another (axe's nested-interactive,
 * decisions/0006); the close control is in the group's header actions instead. */
export function TabTitle({ api }: IDockviewPanelHeaderProps) {
  const [title, setTitle] = useState(api.title ?? api.id);
  useEffect(() => {
    const subscription = api.onDidTitleChange((event) => setTitle(event.title));
    return () => subscription.dispose();
  }, [api]);
  return <span className="gk-tab-title">{title}</span>;
}

/** The group's own controls, outside every tab: close the panel the group shows. */
export function GroupActions({ activePanel, api }: IDockviewHeaderActionsProps) {
  const [panel, setPanel] = useState(activePanel);
  useEffect(() => {
    setPanel(activePanel);
    const subscription = api.onDidActivePanelChange((event) => setPanel(event.panel));
    return () => subscription.dispose();
  }, [activePanel, api]);
  if (!panel) return null;
  return (
    <div className="gk-group-actions">
      <button
        type="button"
        className="gk-icon-button"
        aria-label={`Close ${panel.title ?? panel.id}`}
        title={`Close ${panel.title ?? panel.id}`}
        onClick={() => panel.api.close()}
      >
        ×
      </button>
    </div>
  );
}
