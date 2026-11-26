import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import { campaignWithData, pageErrors, workbenchUrl } from "./fixtures";

// The reanalysis acquisition panel (P2-20): find the nodes around the site, take them one at
// a time, interpolate each source to the site. The providers are stubbed in the browser, so
// no test reaches BrightHub or EarthDataHub; the campaign and its site coordinate are real.

const NODES = [
  { latitude: 55.5, longitude: 8.0, distance_km: 33.7, bearing: "NE" },
  { latitude: 55.25, longitude: 7.75, distance_km: 0.4, bearing: "N" },
  { latitude: 55.0, longitude: 7.75, distance_km: 27.8, bearing: "S" },
  { latitude: 55.25, longitude: 8.0, distance_km: 16.0, bearing: "E" },
];
// Nearest first: the order the panel must take them in.
const NEAREST_FIRST = [...NODES].sort((a, b) => a.distance_km - b.distance_km);
const CACHE = ["hit", "downloaded", "downloaded", "hit"];

interface Recorded {
  login: unknown[];
  nodes: unknown[];
  downloads: Array<{ dataset: string; nodes: Array<{ latitude_ddeg: number; longitude_ddeg: number }>; source: string }>;
  extracts: Array<{ latitude: number; longitude: number; start_date: string; end_date: string }>;
  interpolates: unknown[];
  maxInFlight: number;
}

interface Options {
  /** The 1-based download or extraction that answers 502. */
  failAt?: number;
  delayMs?: number;
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function stubProviders(page: Page, options: Options = {}): Promise<Recorded> {
  const recorded: Recorded = { login: [], nodes: [], downloads: [], extracts: [], interpolates: [], maxInFlight: 0 };
  const delay = options.delayMs ?? 250;
  let signedIn = false;
  let token = false;
  let inFlight = 0;
  let interpolated = false;

  const guarded = async (route: Route, step: () => unknown) => {
    inFlight += 1;
    recorded.maxInFlight = Math.max(recorded.maxInFlight, inFlight);
    await new Promise((resolve) => setTimeout(resolve, delay));
    try {
      return step();
    } finally {
      inFlight -= 1;
    }
  };

  await page.route("**/api/sessions/*/brighthub/**", async (route) => {
    const url = new URL(route.request().url());
    const action = url.pathname.split("/brighthub/")[1];
    const body = route.request().postData() ? JSON.parse(route.request().postData() as string) : null;
    if (action === "status") return json(route, { authenticated: signedIn, has_token: signedIn });
    if (action === "login") {
      recorded.login.push(body);
      signedIn = true;
      return json(route, { status: "ok", authenticated: true });
    }
    if (action === "logout") {
      signedIn = false;
      return json(route, { status: "ok" });
    }
    if (action === "reanalysis/nodes") {
      recorded.nodes.push(body);
      const nodes = NODES.map((n) => ({ latitude_ddeg: n.latitude, longitude_ddeg: n.longitude, distance_km: n.distance_km, bearing: n.bearing }));
      return json(route, { era5_nodes: nodes, merra2_nodes: nodes });
    }
    if (action === "reanalysis/download") {
      recorded.downloads.push(body);
      const count = recorded.downloads.length;
      const result = await guarded(route, () =>
        options.failAt === count
          ? { status: 502, body: { detail: "BrightHub API error: the node could not be read" } }
          : {
              status: 200,
              body: {
                dataset: body.dataset,
                source: "brighthub",
                items: [
                  {
                    latitude: body.nodes[0].latitude_ddeg,
                    longitude: body.nodes[0].longitude_ddeg,
                    rows: 1000,
                    cache: CACHE[(count - 1) % 4],
                    cached_through: "2025-12-31T23:00:00",
                  },
                ],
              },
            },
      );
      return json(route, (result as { body: unknown }).body, (result as { status: number }).status);
    }
    return json(route, { detail: `unstubbed ${action}` }, 404);
  });

  await page.route("**/api/sessions/*/era5/**", async (route) => {
    const url = new URL(route.request().url());
    const action = url.pathname.split("/era5/")[1];
    const method = route.request().method();
    const body = route.request().postData() ? JSON.parse(route.request().postData() as string) : null;
    if (action === "credential/status") return json(route, { configured: token });
    if (action === "credential") {
      token = method === "POST";
      return json(route, { status: "ok", configured: token });
    }
    if (action === "nodes") {
      recorded.nodes.push(body);
      return json(route, { nodes: NODES, grid_resolution_deg: 0.25 });
    }
    if (action === "extract") {
      recorded.extracts.push(body);
      const count = recorded.extracts.length;
      const result = await guarded(route, () =>
        options.failAt === count
          ? { status: 502, body: { detail: "EarthDataHub refused the read" } }
          : { status: 200, body: { status: "ok", rows: 100 } },
      );
      return json(route, (result as { body: unknown }).body, (result as { status: number }).status);
    }
    if (action === "interpolate") {
      recorded.interpolates.push(body);
      interpolated = true;
      return json(route, { status: "ok", nodes_used: 4 });
    }
    return json(route, { detail: `unstubbed ${action}` }, 404);
  });

  // The real summary, with the reanalysis flags the stubbed acquisition would have set.
  await page.route(/\/api\/sessions\/[^/]+$/, async (route) => {
    const response = await route.fetch();
    const summary = await response.json();
    if (interpolated) summary.era5_interpolated_loaded = true;
    return json(route, summary);
  });
  return recorded;
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.map(
      (violation) => `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(" ")).join("; ")}`,
    ),
  ).toEqual([]);
}

async function open(page: Page, name: string, options: Options = {}) {
  const recorded = await stubProviders(page, options);
  const opened = await campaignWithData(page, `${name} ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await page.locator(".dv-tab", { hasText: "Reanalysis" }).click();
  await expect(page.getByRole("heading", { name: "Site" })).toBeVisible();
  return recorded;
}

const progress = (page: Page) => page.locator(".gk-re-progress");

async function storageHolds(page: Page, secret: string): Promise<boolean> {
  return page.evaluate((value) => {
    const dump = (store: Storage) => Object.keys(store).map((key) => `${key}=${store.getItem(key)}`).join("\n");
    return dump(localStorage).includes(value) || dump(sessionStorage).includes(value);
  }, secret);
}

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

test("the panel is a tab beside Data, shows the site, and passes axe", async ({ page }) => {
  await open(page, "Reanalysis tab");
  const group = page.locator(".dv-groupview", { has: page.locator(".dv-tab", { hasText: "Data" }) });
  await expect(group.locator(".dv-tab", { hasText: "Reanalysis" })).toBeVisible();
  await expect(page.getByText("55.25°N 7.75°E")).toBeVisible();
  await expect(page.getByRole("button", { name: "Acquire reanalysis" })).toBeDisabled();
  await expect(page.getByText("Sign in to BrightHub first.")).toBeVisible();
  await expectNoAxeViolations(page);
});

test("BrightHub: sign in, take the nodes one at a time, interpolate both sources", async ({ page }, testInfo) => {
  const recorded = await open(page, "BrightHub run");
  await page.getByLabel("Client ID").fill("client-123");
  await page.getByLabel("Client secret").fill("s3cret-value-xyz");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Signed in for this session.")).toBeVisible();
  expect(recorded.login).toEqual([{ client_id: "client-123", client_secret: "s3cret-value-xyz" }]);
  expect(await storageHolds(page, "s3cret-value-xyz")).toBe(false);

  await page.getByRole("button", { name: "Acquire reanalysis" }).click();
  await expect(page.getByRole("button", { name: "Acquiring…" })).toBeDisabled();
  await expect(page.getByLabel("Client ID")).toHaveCount(0);
  await expect(progress(page)).toContainText("ERA5 node 2 of 4");
  await expect(progress(page)).toContainText("km from the site");
  await expect(progress(page)).toContainText("MERRA-2 node 1 of 4", { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Loaded", exact: true })).toBeVisible({ timeout: 15_000 });

  expect(recorded.downloads.map((d) => d.dataset)).toEqual([...Array(4).fill("ERA5"), ...Array(4).fill("MERRA-2")]);
  for (const request of recorded.downloads) {
    expect(request.nodes).toHaveLength(1);
    expect(request.source).toBe("brighthub");
  }
  expect(recorded.downloads.slice(0, 4).map((d) => [d.nodes[0].latitude_ddeg, d.nodes[0].longitude_ddeg])).toEqual(
    NEAREST_FIRST.map((n) => [n.latitude, n.longitude]),
  );
  expect(recorded.nodes).toEqual([{ latitude: 55.25, longitude: 7.75 }]);
  expect(recorded.interpolates).toEqual([{ source: "era5" }, { source: "merra2" }]);

  const taken = page.getByRole("list", { name: "Nodes taken" });
  await expect(taken.getByRole("listitem")).toHaveCount(8);
  await expect(taken.getByRole("listitem").nth(0)).toContainText("ERA5 55.25°N 7.75°E, 0.4 km from the site: from the project's cache");
  await expect(taken.getByRole("listitem").nth(1)).toContainText(": downloaded");
  await expect(page.getByText("ERA5: 4 nodes, 2 from the cache, interpolated to the site")).toBeVisible();
  await expect(page.getByText("MERRA-2: 4 nodes, 2 from the cache, interpolated to the site")).toBeVisible();

  await page.locator(".dv-tab", { hasText: "Data" }).click();
  await expect(page.getByText("Interpolated to the site.")).toBeVisible();
  await page.locator(".dv-tab", { hasText: "Reanalysis" }).click();
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("reanalysis-light.png") });
  await page.getByRole("button", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("reanalysis-dark.png") });

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Client ID")).toBeVisible();
});

test("BrightHub: a failing third node stops the run and names the step", async ({ page }) => {
  const recorded = await open(page, "BrightHub failure", { failAt: 3 });
  await page.getByLabel("Client ID").fill("client-123");
  await page.getByLabel("Client secret").fill("s3cret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Acquire reanalysis" }).click();

  const alert = page.locator(".gk-re-failure[role=alert]");
  await expect(alert).toContainText("Downloading ERA5 node 3 of 4 failed.");
  await expect(alert).toContainText("BrightHub API error: the node could not be read");
  await expect(page.getByText("ERA5: 2 nodes, 1 from the cache, not interpolated")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Loaded before the failure" })).toBeVisible();
  expect(recorded.downloads).toHaveLength(3);
  expect(recorded.interpolates).toEqual([]);
  await expect(page.getByRole("button", { name: "Acquire reanalysis" })).toBeEnabled();
});

test("EarthDataHub: the four extractions run one after another, never two in flight", async ({ page }) => {
  const recorded = await open(page, "EarthDataHub run", { delayMs: 300 });
  await page.getByRole("radio", { name: /EarthDataHub/ }).check();
  await page.getByLabel("Personal access token").fill("edh-token-abc-987");
  await page.getByRole("button", { name: "Set token" }).click();
  await expect(page.getByText("A token is set for this session.")).toBeVisible();
  expect(await storageHolds(page, "edh-token-abc-987")).toBe(false);

  await page.getByLabel("From", { exact: true }).fill("2020-01-01");
  await page.getByLabel("To", { exact: true }).fill("2020-12-31");
  await page.getByRole("button", { name: "Acquire reanalysis" }).click();
  await expect(progress(page)).toContainText("ERA5 node 3 of 4");
  await expect(page.getByText("ERA5: 4 nodes, interpolated to the site")).toBeVisible({ timeout: 15_000 });

  expect(recorded.maxInFlight).toBe(1);
  expect(recorded.extracts.map((e) => [e.latitude, e.longitude])).toEqual(NEAREST_FIRST.map((n) => [n.latitude, n.longitude]));
  expect(recorded.extracts.every((e) => e.start_date === "2020-01-01" && e.end_date === "2020-12-31")).toBe(true);
  expect(recorded.interpolates).toEqual([{ source: "era5" }]);
  expect(await storageHolds(page, "edh-token-abc-987")).toBe(false);

  await page.getByRole("button", { name: "Clear token" }).click();
  await expect(page.getByLabel("Personal access token")).toBeVisible();
});

test("EarthDataHub: a failing extraction names the step", async ({ page }) => {
  const recorded = await open(page, "EarthDataHub failure", { failAt: 2, delayMs: 50 });
  await page.getByRole("radio", { name: /EarthDataHub/ }).check();
  await page.getByLabel("Personal access token").fill("edh-token");
  await page.getByRole("button", { name: "Set token" }).click();
  await page.getByRole("button", { name: "Acquire reanalysis" }).click();
  await expect(page.locator(".gk-re-failure[role=alert]")).toContainText("Extracting ERA5 node 2 of 4 failed. EarthDataHub refused the read");
  expect(recorded.extracts).toHaveLength(2);
});
