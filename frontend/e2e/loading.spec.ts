import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { fixtureCsv, newCampaign, pageErrors, workbenchUrl } from "./fixtures";

// Loading a campaign's files and the mast diagram (P2-11): a table loads as the records and
// is drafted into a mast; a height the header does not carry is highlighted, never guessed;
// an edit of a built mast rebuilds and undoes; a campaign's own data model is shown only.

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

const csv = (buffer: string) => ({ name: "mast.csv", mimeType: "text/csv", buffer: Buffer.from(buffer) });
const level = (page: Page, height: number) => page.getByRole("group", { name: `Mast level ${height} m` });
const handle = (page: Page, name: string) => page.getByRole("button", { name: `Drag ${name} to a level` });
const treeAt = (page: Page, height: number) => page.getByRole("region", { name: `${height} m`, exact: true });

/** The fixture's table with one more column whose header carries no height. */
function withUnknownColumn(): string {
  return fixtureCsv()
    .split("\n")
    .map((row, index) => (index === 0 ? `${row},WS_Avg` : row === "" ? row : `${row},7.5`))
    .join("\n");
}

// The dragging tests use a tall window: a narrow panel stacks the mast taller than the
// default one, and a pointer cannot drop on a level it cannot see.
async function dragTo(page: Page, from: ReturnType<typeof handle>, to: ReturnType<typeof level>) {
  await page.setViewportSize({ width: 1280, height: 1500 });
  const a = await from.boundingBox();
  const b = await to.boundingBox();
  if (!a || !b) throw new Error("nothing to drag");
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(a.x + a.width / 2 + 8, a.y + a.height / 2 + 8, { steps: 4 });
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await page.mouse.up();
}

async function fillSite(page: Page) {
  await page.getByLabel("Latitude (°)").fill("55.25");
  await page.getByLabel("Longitude (°)").fill("7.75");
  await page.getByLabel("UTC offset (hours)").fill("0");
}

async function accessible(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
}

test("a chosen table is drafted into a mast, and Build waits for the timezone", async ({ page }, testInfo) => {
  const opened = await newCampaign(page, `Load ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(page.getByText("Drop the campaign's files here")).toBeVisible();
  await page.getByLabel("Choose files").setInputFiles(csv(fixtureCsv()));

  await expect(page.getByRole("heading", { name: "Build the data model" })).toBeVisible();
  for (const height of [100, 80, 60]) await expect(level(page, height)).toBeVisible();
  await expect(level(page, 100)).toContainText("Spd_100m");
  await expect(level(page, 100)).toContainText("Spd_100m_sd");
  await expect(level(page, 60)).toContainText("Spd_60m");

  const build = page.getByRole("button", { name: "Build data model" });
  await expect(build).toBeDisabled();
  await expect(page.getByText("Give the timezone", { exact: false })).toBeVisible();
  await accessible(page);
  await page.screenshot({ path: testInfo.outputPath("builder-light.png") });
  await page.getByRole("button", { name: "Dark theme" }).click();
  await accessible(page);
  await page.screenshot({ path: testInfo.outputPath("builder-dark.png") });
  await page.getByRole("button", { name: "Light theme" }).click();

  await fillSite(page);
  await expect(build).toBeEnabled();
  await build.click();
  await expect(page.getByText("Data model loaded")).toBeVisible();
  await expect(treeAt(page, 100)).toContainText("Spd_100m");
  await expect(treeAt(page, 80)).toContainText("Spd_80m");
  await expect(treeAt(page, 60)).toContainText("Spd_60m");
});

test("a column with no height is highlighted and blocks Build until it is placed by drag", async ({ page }) => {
  const opened = await newCampaign(page, `No height ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await page.getByLabel("Choose files").setInputFiles(csv(withUnknownColumn()));

  const tray = page.getByRole("group", { name: "No height yet" });
  await expect(tray).toBeVisible();
  await expect(tray).toContainText("WS_Avg");
  await expect(tray).toContainText("declare the height");
  await fillSite(page);
  const build = page.getByRole("button", { name: "Build data model" });
  await expect(build).toBeDisabled();
  await expect(page.getByText("Give a height to WS_Avg.")).toBeVisible();

  await dragTo(page, handle(page, "WS_Avg"), level(page, 80));
  await expect(tray).toHaveCount(0);
  await expect(level(page, 80)).toContainText("WS_Avg");
  await expect(build).toBeEnabled();
  await build.click();
  await expect(page.getByText("Data model loaded")).toBeVisible();
  await expect(treeAt(page, 80)).toContainText("WS_Avg");
});

test("a new level places a column by keyboard", async ({ page }) => {
  const opened = await newCampaign(page, `New level ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await page.getByLabel("Choose files").setInputFiles(csv(withUnknownColumn()));
  const field = page.getByLabel("New level for WS_Avg in metres");
  await field.fill("40");
  await field.press("Enter");
  await expect(level(page, 40)).toContainText("WS_Avg");
  await expect(page.getByRole("group", { name: "No height yet" })).toHaveCount(0);
});

test("after a build a dragged chip rebuilds the data model, and Ctrl+Z restores it", async ({ page }) => {
  const opened = await newCampaign(page, `Rebuild ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await page.getByLabel("Choose files").setInputFiles(csv(fixtureCsv()));
  await fillSite(page);
  await page.getByRole("button", { name: "Build data model" }).click();
  await expect(page.getByText("Data model loaded")).toBeVisible();

  await page.getByRole("button", { name: "Mast diagram (editable)" }).click();
  await expect(level(page, 60)).toContainText("Spd_60m");
  await dragTo(page, handle(page, "Spd_60m"), level(page, 80));
  await expect(treeAt(page, 80)).toContainText("Spd_60m");
  await expect(treeAt(page, 60)).toHaveCount(0);

  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+z");
  await expect(treeAt(page, 60)).toContainText("Spd_60m");
  await expect(treeAt(page, 80)).not.toContainText("Spd_60m");
});

test("a boom change rebuilds too", async ({ page }) => {
  const opened = await newCampaign(page, `Fields ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await page.getByLabel("Choose files").setInputFiles(csv(fixtureCsv()));
  await fillSite(page);
  await page.getByRole("button", { name: "Build data model" }).click();
  await expect(page.getByText("Data model loaded")).toBeVisible();
  await page.getByRole("button", { name: "Mast diagram (editable)" }).click();
  const boom = page.getByLabel("Boom orientation of Spd_80m in degrees");
  await boom.fill("90");
  await boom.press("Enter");
  await expect(treeAt(page, 80)).toContainText("boom 90°");
});

const OWN_MODEL = {
  author: "Vendor Logger Export",
  date: "2023-03-01T00:00:00Z",
  version: "1.3.0",
  measurement_location: [
    {
      name: "Vendor mast",
      latitude_ddeg: 55.25,
      longitude_ddeg: 7.75,
      logger_main_config: [{ offset_from_utc_hrs: 0 }],
      measurement_point: ["Spd_100m", "Spd_80m", "Spd_60m"].map((name) => {
        const height = Number(name.slice(4, -1));
        return {
          name,
          measurement_type_id: "wind_speed",
          height_m: height,
          height_reference_id: "ground_level",
          logger_measurement_config: [{ height_m: height, column_name: [{ column_name: name, statistic_type_id: "avg" }] }],
        };
      }),
    },
  ],
};

test("a campaign's own data model is shown read only", async ({ page }, testInfo) => {
  const opened = await newCampaign(page, `Own ${Date.now()}`);
  const headers = { "X-GoKaatru-Session": opened.sessionId };
  const timeseries = await page.request.post(`/api/sessions/${opened.sessionId}/uploads/timeseries`, {
    headers,
    multipart: { file: csv(fixtureCsv()) },
  });
  expect(timeseries.ok(), await timeseries.text()).toBeTruthy();
  const model = await page.request.post(`/api/sessions/${opened.sessionId}/uploads/datamodel`, {
    headers,
    multipart: {
      file: { name: "vendor.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(OWN_MODEL)) },
    },
  });
  expect(model.ok(), await model.text()).toBeTruthy();

  await page.goto(workbenchUrl(opened));
  await page.getByRole("button", { name: "Mast diagram (read only)" }).click();
  await expect(page.getByText("The campaign's own data model, vendor.json. Shown, never changed.")).toBeVisible();
  await expect(level(page, 100)).toContainText("Spd_100m");
  await expect(level(page, 60)).toContainText("Spd_60m");
  await expect(page.getByRole("button", { name: /^Drag .* to a level$/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Build data model" })).toHaveCount(0);
  await expect(page.locator(".gk-mast select, .gk-mast input")).toHaveCount(0);
  await accessible(page);
  await page.screenshot({ path: testInfo.outputPath("readonly-light.png") });
  await page.getByRole("button", { name: "Dark theme" }).click();
  await accessible(page);
  await page.screenshot({ path: testInfo.outputPath("readonly-dark.png") });
});

test("a file dropped on the window loads, and a refusal is shown in the server's words", async ({ page }) => {
  const opened = await newCampaign(page, `Drop ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  const drop = (name: string, text: string, type: string) =>
    page.evaluate(
      ({ name, text, type }) => {
        const transfer = new DataTransfer();
        transfer.items.add(new File([text], name, { type }));
        document.body.dispatchEvent(new DragEvent("dragenter", { dataTransfer: transfer, bubbles: true, cancelable: true }));
        document.body.dispatchEvent(new DragEvent("drop", { dataTransfer: transfer, bubbles: true, cancelable: true }));
      },
      { name, text, type },
    );

  await drop("mast.csv", fixtureCsv(), "text/csv");
  await expect(page.getByText("Records loaded")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Build the data model" })).toBeVisible();
  await expect(page.getByRole("status").getByText("Loaded as the timeseries.")).toBeVisible();

  await drop("notes.json", "{ not a data model", "application/json");
  await expect(page.getByRole("status").getByText(/was refused/)).toBeVisible();
  await drop("picture.png", "x", "image/png");
  await expect(page.getByRole("status").getByText("Not a table", { exact: false })).toBeVisible();
});
