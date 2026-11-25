import { expect, type Page } from "@playwright/test";

// A campaign with records, for the workbench's browser tests: 30 days of 10-minute data on a
// mast at 60, 80 and 100 m with a vane and a thermometer at 100 m, uploaded through the real
// route and given a data model through the generated operation. Deterministic, so a test can
// name the records it expects. Spd_100m reads under 0.6 m/s for FROZEN_RECORDS records from
// FROZEN_START while the lower cups keep turning: a frozen cup, for the flag tests.

export const FIXTURE_START = Date.UTC(2023, 2, 1);
export const STEP_MS = 10 * 60 * 1000;
export const RECORDS = 30 * 144;
export const FROZEN_START = 2000;
export const FROZEN_RECORDS = 48;
export const CHANNELS = ["Spd_100m", "Spd_80m", "Spd_60m", "Dir_100m", "Tmp_100m"] as const;
/** Statistic columns: the 100 m cup's standard deviation, part of its instrument. */
export const STATISTICS = ["Spd_100m_sd"] as const;

function random(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function stamp(index: number): string {
  return new Date(FIXTURE_START + index * STEP_MS).toISOString().slice(0, 16).replace("T", " ");
}

export function fixtureCsv(): string {
  const next = random(20261125);
  const gauss = () => (next() + next() + next() + next() + next() + next() - 3) / Math.sqrt(0.5);
  const rows = ["Timestamp," + [...CHANNELS, ...STATISTICS].join(",")];
  let gust = 0;
  let direction = 235;
  for (let i = 0; i < RECORDS; i += 1) {
    const day = i / 144;
    gust = 0.93 * gust + 0.55 * gauss();
    const speed = Math.max(0.6, 8.2 + 2.6 * Math.sin((day * 2 * Math.PI) / 6.5) + gust);
    const night = i % 144 < 42 || i % 144 > 114 ? 1 : 0;
    const alpha = 0.13 + 0.07 * night;
    const at80 = Math.max(0.3, speed * (80 / 100) ** alpha + 0.12 * gauss());
    const at60 = Math.max(0.3, speed * (60 / 100) ** alpha + 0.12 * gauss());
    direction += 0.06 * (235 + 50 * Math.sin((day * 2 * Math.PI) / 6.5) - direction) + 5 * gauss();
    const frozen = i >= FROZEN_START && i < FROZEN_START + FROZEN_RECORDS;
    const at100 = frozen ? 0.35 + 0.08 * Math.abs(gauss()) : speed;
    const temperature = 6 + 4 * Math.sin(((i % 144) / 144) * 2 * Math.PI) + 0.5 * gauss();
    rows.push(
      [stamp(i), at100, at80, at60, ((direction % 360) + 360) % 360, temperature, 0.1 * at100 + 0.05 * Math.abs(gauss())]
        .map((value) => (typeof value === "number" ? value.toFixed(3) : value))
        .join(","),
    );
  }
  return rows.join("\n") + "\n";
}

const SPEC = {
  location: { name: "Test ridge mast", latitude_ddeg: 55.25, longitude_ddeg: 7.75, offset_from_utc_hrs: 0 },
  points: [
    {
      name: "Spd_100m",
      measurement_type_id: "wind_speed",
      height_m: 100,
      statistics: [{ column_name: "Spd_100m_sd", statistic_type_id: "sd" }],
    },
    { name: "Spd_80m", measurement_type_id: "wind_speed", height_m: 80 },
    { name: "Spd_60m", measurement_type_id: "wind_speed", height_m: 60 },
    { name: "Dir_100m", measurement_type_id: "wind_direction", height_m: 100 },
    { name: "Tmp_100m", measurement_type_id: "temperature", height_m: 100 },
  ],
};

export interface Opened {
  projectId: string;
  sessionId: string;
}

/** A project with one empty mast campaign. */
export async function newCampaign(page: Page, name: string): Promise<Opened> {
  const project = await page.request.post("/api/projects", { data: { name, site_name: "Test ridge" } });
  expect(project.ok(), await project.text()).toBeTruthy();
  const projectId = (await project.json()).id as string;
  const campaign = await page.request.post(`/api/projects/${projectId}/campaigns`, {
    data: { name: "Mast M1", kind: "mast" },
  });
  expect(campaign.ok(), await campaign.text()).toBeTruthy();
  return { projectId, sessionId: (await campaign.json()).session_id as string };
}

/** A project with one mast campaign holding the fixture's records and a built data model. */
export async function campaignWithData(page: Page, name: string): Promise<Opened> {
  const opened = await newCampaign(page, name);
  const headers = { "X-GoKaatru-Session": opened.sessionId };
  const upload = await page.request.post(`/api/sessions/${opened.sessionId}/uploads/timeseries`, {
    headers,
    multipart: { file: { name: "mast.csv", mimeType: "text/csv", buffer: Buffer.from(fixtureCsv()) } },
  });
  expect(upload.ok(), await upload.text()).toBeTruthy();
  const built = await page.request.post(`/api/sessions/${opened.sessionId}/operations/build_data_model`, {
    headers,
    data: { spec: SPEC },
  });
  expect(built.ok(), await built.text()).toBeTruthy();
  return opened;
}

/** Every uncaught error the page throws; a test asserts the list empty at its end. A chart
 * that throws inside its library draws nothing and passes every other check. */
export function pageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`${error.message} ${error.stack?.split("\n")[1]?.trim() ?? ""}`));
  return errors;
}

export function workbenchUrl({ projectId, sessionId }: Opened): string {
  return `/workbench/?project=${projectId}&campaign=${sessionId}`;
}
