import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { fixtureCsv, pageErrors } from "./fixtures";

// The project start screen and the campaign switcher (P2-10): a project holds several
// campaigns, one is open at a time, and each keeps its own coordinate and timezone.

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.map(
      (violation) => `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(" ")).join("; ")}`,
    ),
  ).toEqual([]);
}

const projectCard = (page: Page, name: string) =>
  page.getByRole("listitem").filter({ has: page.getByRole("heading", { name, exact: true }) });

async function addCampaign(page: Page, projectName: string, name: string, kind: string) {
  const card = projectCard(page, projectName);
  await card.getByRole("button", { name: "Add campaign" }).click();
  await card.getByLabel("Campaign name").fill(name);
  await card.getByLabel("Kind").selectOption(kind);
  await card.getByLabel("Campaign name").press("Enter");
  await expect(card.getByRole("link", { name, exact: true })).toBeVisible();
}

test("a project is made, renamed and given a mast and a lidar, and the switcher moves between them", async ({
  page,
}, testInfo) => {
  const stamp = Date.now();
  const name = `Ridge ${stamp}`;
  await page.goto("/workbench/");
  await expectNoAxeViolations(page);

  // A blank name is the server's refusal, shown where the form is.
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("alert").first()).toContainText(/name/i);

  await page.getByLabel("Project name").fill(name);
  await page.getByLabel("Site name (optional)").fill("North ridge");
  await page.getByLabel("Project name").press("Enter");
  const card = projectCard(page, name);
  await expect(card).toBeVisible();
  await expect(card).toContainText("North ridge");
  await expect(card).toContainText("No campaigns yet.");

  // Rename the project and its site; Escape cancels and focus returns to the button.
  await card.getByRole("button", { name: "Rename project" }).click();
  await card.getByLabel("Project name").fill("discarded");
  await page.keyboard.press("Escape");
  await expect(card.getByRole("button", { name: "Rename project" })).toBeFocused();
  await expect(card.getByRole("heading", { name })).toBeVisible();

  const renamed = `${name} B`;
  await card.getByRole("button", { name: "Rename project" }).click();
  await card.getByLabel("Project name").fill(renamed);
  await card.getByLabel("Site name").fill("South ridge");
  await card.getByLabel("Site name").press("Enter");
  const moved = projectCard(page, renamed);
  await expect(moved).toContainText("South ridge");
  await expect(moved.getByRole("button", { name: "Rename project" })).toBeFocused();

  await addCampaign(page, renamed, "Mast M1", "mast");
  await addCampaign(page, renamed, "Lidar L1", "lidar");

  await moved.getByRole("button", { name: "Rename Lidar L1" }).click();
  await moved.getByLabel("Campaign name").fill("Lidar L2");
  await moved.getByLabel("Campaign name").press("Enter");
  await expect(moved.getByRole("link", { name: "Lidar L2" })).toBeVisible();
  await expect(moved.getByRole("link", { name: "Lidar L1" })).toHaveCount(0);
  await expect(moved).toContainText("No site declared yet");
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("start-screen.png") });

  await moved.getByRole("link", { name: "Mast M1" }).click();
  const crumbs = page.getByRole("navigation", { name: "Where you are" });
  const switcher = crumbs.getByRole("combobox", { name: "Campaign" });
  await expect(switcher).toHaveValue(/.+/);
  await expect(crumbs).toContainText(renamed);
  await expect(switcher.locator("option:checked")).toHaveText("Mast M1");
  const mastUrl = page.url();

  await switcher.selectOption({ label: "Lidar L2" });
  await expect(page).not.toHaveURL(mastUrl);
  await expect(page).toHaveURL(/project=.+&campaign=.+/);
  await expect(crumbs.getByRole("combobox", { name: "Campaign" }).locator("option:checked")).toHaveText("Lidar L2");
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("shell-switcher.png") });
});

function spec(offset: number) {
  return {
    location: { name: "Site", latitude_ddeg: 55.25, longitude_ddeg: 7.75, offset_from_utc_hrs: offset },
    points: [{ name: "Spd_100m", measurement_type_id: "wind_speed", height_m: 100 }],
  };
}

test("campaigns that declare different timezones are shown with the notice", async ({ page }, testInfo) => {
  const name = `Zones ${Date.now()}`;
  const project = await page.request.post("/api/projects", { data: { name, site_name: "Two zones" } });
  expect(project.ok(), await project.text()).toBeTruthy();
  const projectId = (await project.json()).id as string;
  for (const [campaignName, kind, offset] of [
    ["Mast Z0", "mast", 0],
    ["Lidar Z1", "lidar", 1],
  ] as const) {
    const created = await page.request.post(`/api/projects/${projectId}/campaigns`, { data: { name: campaignName, kind } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const sessionId = (await created.json()).session_id as string;
    const headers = { "X-GoKaatru-Session": sessionId };
    const upload = await page.request.post(`/api/sessions/${sessionId}/uploads/timeseries`, {
      headers,
      multipart: { file: { name: "mast.csv", mimeType: "text/csv", buffer: Buffer.from(fixtureCsv()) } },
    });
    expect(upload.ok(), await upload.text()).toBeTruthy();
    const built = await page.request.post(`/api/sessions/${sessionId}/operations/build_data_model`, {
      headers,
      data: { spec: spec(offset) },
    });
    expect(built.ok(), await built.text()).toBeTruthy();
    // The start screen reads each campaign's site from its saved run configuration.
    const saved = await page.request.post(`/api/sessions/${sessionId}/operations/save_run_config`, { headers, data: {} });
    expect(saved.ok(), await saved.text()).toBeTruthy();
  }

  await page.goto("/workbench/");
  const card = projectCard(page, name);
  await expect(card.getByRole("status")).toContainText("The campaigns declare different timezones:");
  await expect(card.getByRole("status")).toContainText("Mast Z0");
  await expect(card.getByRole("status")).toContainText("Lidar Z1");
  await expect(card).toContainText("55.2500°, 7.7500°");
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("timezones.png") });
});
