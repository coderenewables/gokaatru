export const CAMPAIGN_KINDS = [
  { value: "mast", label: "Mast" },
  { value: "lidar", label: "Lidar" },
  { value: "floating_lidar", label: "Floating lidar" },
] as const;

export function kindLabel(kind: string): string {
  return CAMPAIGN_KINDS.find((item) => item.value === kind)?.label ?? kind.replace("_", " ");
}

/** Minutes in UTC, so the figure reads the same on every machine. */
export function formatChange(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return `${parsed.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

interface Located {
  latitude?: number | null;
  longitude?: number | null;
  elevation_m?: number | null;
  timezone?: string | null;
}

/** The campaign's own coordinate and timezone, or what is still missing. */
export function describeSite(campaign: Located): string {
  const parts: string[] = [];
  const { latitude, longitude, elevation_m: elevation, timezone } = campaign;
  if (typeof latitude === "number" && typeof longitude === "number") {
    parts.push(`${latitude.toFixed(4)}°, ${longitude.toFixed(4)}°`);
  }
  if (typeof elevation === "number") parts.push(`${elevation.toFixed(0)} m`);
  if (timezone) parts.push(timezone);
  return parts.length > 0 ? parts.join(" · ") : "No site declared yet";
}

/** Names each campaign's timezone; the campaigns are never reconciled, only shown. */
export function timezoneNotice(campaigns: { name: string; timezone?: string | null }[]): string {
  const listed = campaigns
    .filter((campaign) => campaign.timezone)
    .map((campaign) => `${campaign.name} ${campaign.timezone}`);
  return `The campaigns declare different timezones: ${listed.join("; ")}.`;
}
