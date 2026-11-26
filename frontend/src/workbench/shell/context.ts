import { createContext, useContext } from "react";

export interface CampaignContext {
  sessionId: string;
  projectId: string | null;
}

/** The open campaign, for every panel: dockview renders panels from its own registry, so
 * they read it here rather than through props. */
export const Campaign = createContext<CampaignContext | null>(null);

export function useCampaign(): CampaignContext {
  const campaign = useContext(Campaign);
  if (campaign === null) throw new Error("A workbench panel was rendered outside an open campaign");
  return campaign;
}
