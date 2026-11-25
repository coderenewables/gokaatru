import { speedChannels, useSensors } from "../sensors";
import { useCampaign } from "../shell/context";
import { SelectionSection } from "./SelectionSection";

/** The inspector: what is selected and, as the flag flow lands (P2-18), what can be done. */
export function InspectorPanel() {
  const { sessionId } = useCampaign();
  const sensors = useSensors(sessionId);
  return (
    <div className="gk-panel gk-inspector">
      <SelectionSection sessionId={sessionId} channels={speedChannels(sensors.data ?? [])} />
    </div>
  );
}
