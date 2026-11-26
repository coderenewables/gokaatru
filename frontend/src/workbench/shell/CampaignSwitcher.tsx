export interface CampaignSwitcherProps {
  projectId: string;
  sessionId: string;
  campaigns: { session_id: string; name: string }[];
}

/** The open project's campaigns; choosing one opens it (one campaign is open at a time). */
export function CampaignSwitcher({ projectId, sessionId, campaigns }: CampaignSwitcherProps) {
  return (
    <select
      className="gk-switcher"
      aria-label="Campaign"
      value={sessionId}
      onChange={(event) => {
        window.location.assign(`/?project=${projectId}&campaign=${event.target.value}`);
      }}
    >
      {campaigns.map((campaign) => (
        <option key={campaign.session_id} value={campaign.session_id}>
          {campaign.name}
        </option>
      ))}
    </select>
  );
}
