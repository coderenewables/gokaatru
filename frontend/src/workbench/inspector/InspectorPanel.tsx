import { speedChannels, useSensors } from "../sensors";
import { useCampaign } from "../shell/context";
import { FlagSection } from "./FlagSection";
import { FocusedFlagSection } from "./FocusedFlagSection";
import { RuleDraftSection } from "./RuleDraftSection";
import { SelectionSection } from "./SelectionSection";
import "./inspector.css";

/** The inspector: the flag in focus, a proposed rule, what is selected and flagging it. */
export function InspectorPanel() {
  const { sessionId } = useCampaign();
  const sensors = useSensors(sessionId);
  return (
    <div className="gk-panel gk-inspector">
      <FocusedFlagSection sessionId={sessionId} />
      <RuleDraftSection sessionId={sessionId} />
      <SelectionSection sessionId={sessionId} channels={speedChannels(sensors.data ?? [])} />
      <FlagSection sessionId={sessionId} />
    </div>
  );
}
