// Drives every (library, case) page in Chromium and writes results-<mode>.json and results-<mode>.md.
// Usage: node run.mjs [--mode headless|headed] [--runs 5] [--libs plotly4,echarts] [--cases timeline-1] [--tag name] [--args "--flag1 --flag2"]
import { chromium } from "@playwright/test";
import { preview } from "vite";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import os from "node:os";
import { execSync } from "node:child_process";

const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf("--" + k); return i >= 0 ? argv[i + 1] : d; };
const mode = arg("mode", "headless");
const RUNS = Number(arg("runs", "5"));
const tag = arg("tag", mode);
const extraArgs = (arg("args", "") || "").split(" ").filter(Boolean);
const LIBS = (arg("libs", "plotly4,plotly2,echarts,uplot")).split(",");
const CASES = (arg("cases", "timeline-1,timeline-6,timeline-60-decimated,scatter-1")).split(",");
const PORT = 5199;
const BASE = `http://127.0.0.1:${PORT}/`;

const median = (a) => { const s = [...a].sort((x, y) => x - y); const n = s.length; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };
const stat = (a) => ({ median: median(a), min: Math.min(...a), max: Math.max(...a), values: a });

function bundleSizes() {
  const dir = new URL("./dist/assets/", import.meta.url);
  const out = {};
  for (const f of readdirSync(dir)) {
    const p = new URL(f, dir);
    const buf = readFileSync(p);
    out[f] = { bytes: statSync(p).size, gzipBytes: gzipSync(buf).length };
  }
  return out;
}

async function environment(browser, ctxOpts) {
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  await page.goto(BASE + "?lib=none&case=blank");
  await page.waitForFunction(() => window.__bench);
  const gpu = await page.evaluate(() => window.__bench.gpu());
  const floor = await page.evaluate(() => window.__bench.floor());
  let gpuPage = null;
  try {
    await page.goto("chrome://gpu", { timeout: 15000 });
    await page.waitForTimeout(1500);
    gpuPage = await page.evaluate(() => document.body.innerText.slice(0, 4000));
  } catch { gpuPage = null; }
  const ua = await page.evaluate(() => navigator.userAgent).catch(() => "");
  await ctx.close();
  return { gpu, barrierFloorMs: floor, chromeGpuPage: gpuPage, userAgent: ua };
}

async function oneRun(browser, ctxOpts, lib, cs) {
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  page.setDefaultTimeout(240000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  try {
    await page.goto(`${BASE}?lib=${lib}&case=${cs}`);
    await page.waitForFunction(() => window.__bench);
    const info = await page.evaluate(() => window.__bench.ready());
    const render = await page.evaluate(() => window.__bench.render());
    const plan = await page.evaluate(() => window.__bench.brushPlan());
    await page.evaluate(() => window.__bench.armBrush());
    const [a, b] = plan.points;
    await page.mouse.move(a[0], a[1]);
    if (plan.modifier) await page.keyboard.down(plan.modifier);
    await page.mouse.down();
    await page.mouse.move(b[0], b[1], { steps: 20 });
    await page.mouse.up();
    if (plan.modifier) await page.keyboard.up(plan.modifier);
    const brush = await page.evaluate(() => window.__bench.brushResult());
    const hl = await page.evaluate(() => window.__bench.highlight());
    const zm = await page.evaluate(() => window.__bench.zoom());
    const heap = await page.evaluate(() => window.__bench.heap());
    return { ok: true, info, render, brush, highlight: hl, zoom: zm, heap, pageErrors: errors };
  } catch (e) {
    return { ok: false, error: String(e).slice(0, 600), pageErrors: errors };
  } finally {
    await ctx.close();
  }
}

function summarise(runs) {
  const good = runs.slice(1).filter((r) => r.ok && r.brush && !r.brush.timeout); // runs[0] is the warm-up
  const okAll = runs.slice(1).filter((r) => r.ok);
  const pick = (rs, f) => rs.map(f).filter((v) => typeof v === "number" && isFinite(v));
  const s = {};
  if (okAll.length) {
    s.firstRenderMs = stat(pick(okAll, (r) => r.render.firstRenderMs));
    s.libReturnMs = stat(pick(okAll, (r) => r.render.libReturnMs));
    s.highlightMs = stat(pick(okAll, (r) => r.highlight.highlightMs));
    s.zoomMs = stat(pick(okAll, (r) => r.zoom.zoomMs));
    s.heapAfterMB = stat(pick(okAll, (r) => r.heap.heapAfter / 1048576));
    s.heapDeltaMB = stat(pick(okAll, (r) => r.heap.heapDelta / 1048576));
    s.info = okAll[0].info;
    s.genMs = stat(pick(okAll, (r) => r.info.genMs));
    if (okAll[0].info.decimateMs) s.decimateMs = stat(pick(okAll, (r) => r.info.decimateMs));
  }
  if (good.length) {
    s.brushLatencyMs = stat(pick(good, (r) => r.brush.latencyMs));
    s.brushCallbackMs = stat(pick(good, (r) => r.brush.callbackMs));
    s.brushIndicesMs = stat(pick(good, (r) => r.brush.indicesMs));
    s.brushPaintMs = stat(pick(good, (r) => r.brush.paintMs));
    s.selection = {
      source: good[0].brush.source,
      nSelected: good.map((r) => r.brush.nSelected),
      nDelivered: good.map((r) => r.brush.nDelivered),
      nReference: good.map((r) => r.brush.nReference),
      nMissing: good.map((r) => r.brush.nMissing),
      nExtra: good.map((r) => r.brush.nExtra),
      nativeCount: good.map((r) => r.brush.nativeCount),
      allAgree: good.every((r) => r.brush.agree),
    };
  }
  s.brushRunsDelivered = `${good.length}/${runs.length - 1}`;
  s.failures = runs.filter((r) => !r.ok).map((r) => r.error);
  s.brushTimeouts = runs.slice(1).filter((r) => r.ok && r.brush && r.brush.timeout).length;
  return s;
}

const f = (st, d = 1) => (st ? `${st.median.toFixed(d)} [${st.min.toFixed(d)}-${st.max.toFixed(d)}]` : "n/a");

function markdown(res) {
  const L = [];
  L.push(`# Results: ${res.tag} (${res.mode})`, "", `Median [min-max] of ${RUNS} runs after 1 warm-up. Times in ms unless stated. Barrier floor (empty page): ${res.env.barrierFloorMs.toFixed(1)} ms.`, "");
  L.push("| lib | case | first render | brush latency | highlight redraw | zoom step | heap after (MB) | heap delta (MB) | selected (library vs reference) | agree |");
  L.push("|---|---|---|---|---|---|---|---|---|---|");
  for (const r of res.results) {
    const s = r.summary;
    const sel = s.selection ? `${s.selection.nSelected[0]} vs ${s.selection.nReference[0]} (${s.selection.source})` : (s.brushTimeouts ? "no selection event" : "n/a");
    L.push(`| ${r.lib} | ${r.case} | ${f(s.firstRenderMs)} | ${f(s.brushLatencyMs)} | ${f(s.highlightMs)} | ${f(s.zoomMs)} | ${f(s.heapAfterMB, 0)} | ${f(s.heapDeltaMB, 0)} | ${sel} | ${s.selection ? s.selection.allAgree : "n/a"} |`);
  }
  L.push("", "## Brush latency breakdown (median, ms)", "", "| lib | case | pointer-up to callback | callback to indices | indices to painted | total |", "|---|---|---|---|---|---|");
  for (const r of res.results) {
    const s = r.summary;
    L.push(`| ${r.lib} | ${r.case} | ${f(s.brushCallbackMs)} | ${f(s.brushIndicesMs)} | ${f(s.brushPaintMs)} | ${f(s.brushLatencyMs)} |`);
  }
  L.push("", "## Data preparation (not part of render time), median ms", "", "| lib | case | generation | decimation (60 channels) | points per channel | channels |", "|---|---|---|---|---|---|");
  for (const r of res.results) {
    const s = r.summary;
    L.push(`| ${r.lib} | ${r.case} | ${f(s.genMs, 0)} | ${s.decimateMs ? f(s.decimateMs, 1) : "n/a"} | ${s.info?.pointsPerChannel ?? "n/a"} | ${s.info?.channels ?? "n/a"} |`);
  }
  L.push("", "## Failures", "");
  for (const r of res.results) for (const e of r.summary.failures ?? []) L.push(`- ${r.lib} ${r.case}: ${e}`);
  return L.join("\n") + "\n";
}

const server = await preview({ preview: { port: PORT, strictPort: true, host: "127.0.0.1" }, logLevel: "error" });
let browser;
try {
  const headless = mode !== "headed";
  browser = await chromium.launch({ headless, args: ["--enable-precise-memory-info", "--js-flags=--expose-gc", ...extraArgs] });
  const ctxOpts = { viewport: { width: 1700, height: 900 }, deviceScaleFactor: 1 };
  const env = await environment(browser, ctxOpts);
  env.browserVersion = browser.version();
  env.cpu = os.cpus()[0].model;
  env.logicalCpus = os.cpus().length;
  env.ramGB = +(os.totalmem() / 2 ** 30).toFixed(2);
  env.os = `${os.type()} ${os.release()}`;
  env.node = process.version;
  try { env.gpuAdapter = execSync('powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join \'; \'"').toString().trim(); } catch { /* optional */ }
  console.log("env", JSON.stringify(env.gpu), "floor", env.barrierFloorMs);
  const results = [];
  for (const lib of LIBS) {
    for (const cs of CASES) {
      const runs = [];
      let consecutiveFail = 0;
      for (let i = 0; i <= RUNS; i++) {
        const t = Date.now();
        const r = await oneRun(browser, ctxOpts, lib, cs);
        runs.push(r);
        console.log(`${lib} ${cs} run ${i}${i === 0 ? " (warm-up)" : ""}: ${r.ok ? `render ${r.render.firstRenderMs.toFixed(0)} brush ${r.brush && !r.brush.timeout ? r.brush.latencyMs.toFixed(0) : "none"} hl ${r.highlight.highlightMs.toFixed(0)} zoom ${r.zoom.zoomMs.toFixed(0)}` : "FAIL " + r.error.slice(0, 160)} (${((Date.now() - t) / 1000).toFixed(0)}s)`);
        consecutiveFail = r.ok ? 0 : consecutiveFail + 1;
        if (consecutiveFail >= 2) break;
      }
      results.push({ lib, case: cs, runs, summary: summarise(runs) });
    }
  }
  const res = { tag, mode, runsPerCase: RUNS, env, bundles: bundleSizes(), results };
  writeFileSync(new URL(`./results-${tag}.json`, import.meta.url), JSON.stringify(res, null, 1));
  writeFileSync(new URL(`./results-${tag}.md`, import.meta.url), markdown(res));
  console.log("written results-" + tag);
} finally {
  if (browser) await browser.close();
  await server.close();
}
