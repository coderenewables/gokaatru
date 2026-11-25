import { Shell } from "./shell/Shell";
import { StartScreen } from "./StartScreen";

/** Which screen the address names: a campaign opens the shell, nothing opens the projects. */
export function Workbench() {
  const params = new URLSearchParams(window.location.search);
  const campaign = params.get("campaign");
  if (!campaign) return <StartScreen />;
  return <Shell sessionId={campaign} projectId={params.get("project")} />;
}
