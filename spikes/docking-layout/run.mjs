// Drives the docking-layout spike pages in headed Chromium.
// Usage: node run.mjs --phase dev|prod [--libs dockview,flexlayout] [--items 2,3] [--runs 5]
//   dev  = Vite dev server (StrictMode double-invokes effects): items 1, 2, 3, 5, 6, 7
//   prod = production build via vite preview: items 1 (console), 4 (timing), 6 (axe)
import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createServer, preview } from "vite";
import { writeFileSync } from "node:fs";

const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf("--" + k); return i >= 0 ? argv[i + 1] : d; };
const phase = arg("phase", "dev");
const LIBS = arg("libs", "dockview,flexlayout").split(",");
const ITEMS = arg("items", phase === "dev" ? "1,2,3,5,6,7" : "1,4,6").split(",").map(Number);
const RUNS = Number(arg("runs", "5"));
const PORT = 5198;
const BASE = `http://127.0.0.1:${PORT}/`;
const median = (a) => { const s = [...a].sort((x, y) => x - y); const n = s.length; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };

const SEL = {
  dockview: {
    tab: (id) => `.dv-tab[data-tab-panel-id="${id}"]`,
    group: (id) => `.dv-groupview:has(.dv-tab[data-tab-panel-id="${id}"])`,
    content: ".dv-content-container",
    activeTab: ".dv-tab.dv-active-tab",
    tablist: "[role=tablist]",
    sash: ".dv-sash",
  },
  flexlayout: {
    tab: (id) => `#flexlayout-tabbutton-${id}`,
    group: (id) => `.flexlayout__tabset:has(#flexlayout-tabbutton-${id})`,
    content: ".flexlayout__tabset_content",
    activeTab: ".flexlayout__tab_button--selected",
    tablist: "[role=tablist]",
    sash: ".flexlayout__splitter",
  },
};

async function open(browser, lib, extra = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const msgs = [];
  page.on("console", (m) => { if (m.type() !== "debug") msgs.push({ type: m.type(), text: m.text().slice(0, 400) }); });
  page.on("pageerror", (e) => msgs.push({ type: "pageerror", text: String(e).slice(0, 400) }));
  page.on("requestfailed", (r) => msgs.push({ type: "requestfailed", text: r.url() }));
  page.on("response", (r) => { if (r.status() >= 400) msgs.push({ type: "http" + r.status(), text: r.url() }); });
  await page.goto(`${BASE}?lib=${lib}`);
  await page.waitForFunction(() => window.__spike?.groups && window.__spike.live >= 1 && document.querySelector(".u-over"));
  await page.waitForTimeout(500);
  return { ctx, page, msgs };
}

// State of the chart: mount counters, instance id, data identity, whether drawn.
const snap = (page) => page.evaluate(() => {
  const s = window.__spike;
  const host = document.querySelector('[data-testid="chart-host"]');
  const u = s.chart;
  let ink = 0, cw = 0, ch = 0;
  const cv = host?.querySelector("canvas");
  if (cv) {
    cw = cv.width; ch = cv.height;
    const d = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) ink++;
  }
  let sum = 0, n = 0;
  if (u) { const y = u.data[1]; for (let i = 0; i < y.length; i += 1000) if (y[i] === y[i]) { sum += y[i]; n++; } }
  const r = host?.getBoundingClientRect();
  return {
    mounts: s.mounts, unmounts: s.unmounts, live: s.live, instance: host?.dataset.instance ?? null,
    points: u ? u.data[1].length : 0, checksum: Math.round(sum * 1000) / 1000, canvasInkPixels: ink, canvasPx: [cw, ch],
    hostRect: r ? [Math.round(r.width), Math.round(r.height)] : null, uplotSize: u ? [u.width, u.height] : null,
    hostConnected: !!host?.isConnected, groups: s.groups(),
  };
});

// Native drag by mouse events. target = {x, y} in page coordinates.
async function dragTo(page, fromLoc, to) {
  const b = await fromLoc.boundingBox();
  const sx = b.x + b.width / 2, sy = b.y + b.height / 2;
  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await page.mouse.move(sx + 8, sy + 8, { steps: 4 });
  await page.mouse.move(to.x, to.y, { steps: 20 });
  await page.waitForTimeout(250);
  await page.mouse.move(to.x + 1, to.y + 1, { steps: 2 });
  await page.waitForTimeout(150);
  await page.mouse.up();
  await page.waitForTimeout(600);
}
async function contentPoint(page, lib, panelId, fx, fy) {
  const s = SEL[lib];
  const b = await page.locator(s.group(panelId)).locator(s.content).first().boundingBox();
  return { x: b.x + b.width * fx, y: b.y + b.height * fy };
}
const norm = (g) => g.map((x) => [...x].sort()).sort((a, b) => a.join().localeCompare(b.join()));
const diffs = (a, b, path = "") => {
  if (typeof a !== "object" || a === null || typeof b !== "object" || b === null) return a === b ? [] : [`${path}: ${JSON.stringify(a)} -> ${JSON.stringify(b)}`];
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].flatMap((k) => diffs(a[k], b[k], path + "/" + k));
};
const sameGroupAs = (groups, a, b) => groups.some((g) => g.includes(a) && g.includes(b));
const summarise = (msgs) => {
  const c = {};
  for (const m of msgs) c[m.type] = (c[m.type] ?? 0) + 1;
  return { counts: c, errorsAndWarnings: msgs.filter((m) => ["error", "warning", "pageerror", "requestfailed"].some((t) => m.type === t) || m.type.startsWith("http")) };
};

const items = {
  // 1. React 19 compatibility: console under StrictMode, mount counts after load.
  async 1(browser, lib) {
    const { ctx, page, msgs } = await open(browser, lib);
    const st = await snap(page);
    const out = { phase, mountsAfterLoad: st.mounts, unmountsAfterLoad: st.unmounts, liveCharts: st.live, chartCanvasesInDom: await page.locator(".u-over").count(), console: summarise(msgs) };
    await ctx.close();
    return out;
  },

  // 2. Move a tab to another group; drag to split.
  async 2(browser, lib) {
    const s = SEL[lib];
    const { ctx, page } = await open(browser, lib);
    const before = await snap(page);
    const out = { before };
    // A: drag chart tab onto the centre of the inspector group's content: expect it joins that group
    await dragTo(page, page.locator(s.tab("chart")), await contentPoint(page, lib, "inspector", 0.5, 0.5));
    const a = await snap(page);
    out.moveToGroup = { worked: sameGroupAs(a.groups, "chart", "inspector"), groups: a.groups, mountDelta: a.mounts - before.mounts, unmountDelta: a.unmounts - before.unmounts, sameInstance: a.instance === before.instance, sameData: a.points === before.points && a.checksum === before.checksum, drawn: a.canvasInkPixels > 1000, after: a };
    // B: drag chart tab onto the left edge of the rose group: expect a new group holding only the chart
    await dragTo(page, page.locator(s.tab("chart")), await contentPoint(page, lib, "rose", 0.06, 0.5));
    const b = await snap(page);
    const alone = b.groups.some((g) => g.length === 1 && g[0] === "chart");
    out.dragToSplit = { worked: alone && b.groups.length === a.groups.length + 0 || alone, groups: b.groups, groupCountBefore: a.groups.length, groupCountAfter: b.groups.length, mountDelta: b.mounts - a.mounts, unmountDelta: b.unmounts - a.unmounts, sameInstance: b.instance === a.instance, sameData: b.points === a.points && b.checksum === a.checksum, drawn: b.canvasInkPixels > 1000, after: b };
    out.totalMountDeltaAcrossBothMoves = b.mounts - before.mounts;
    out.totalUnmountDeltaAcrossBothMoves = b.unmounts - before.unmounts;
    // placeholder panels keep working after the moves
    const inp = page.getByLabel("inspector input");
    await inp.fill("abc");
    out.placeholderInputWorksAfterMoves = (await inp.inputValue()) === "abc";
    // save state for item 3 within the same context
    out._json = await page.evaluate(() => window.__spike.serialize());
    out._groups = b.groups;
    await ctx.close();
    return out;
  },

  // 3. Persistence: serialise after a change, reload, restore from JSON, compare.
  async 3(browser, lib) {
    const s = SEL[lib];
    const { ctx, page } = await open(browser, lib);
    await dragTo(page, page.locator(s.tab("chart")), await contentPoint(page, lib, "rose", 0.06, 0.5));
    await dragTo(page, page.locator(s.tab("tree")), await contentPoint(page, lib, "inspector", 0.5, 0.5));
    const json = await page.evaluate(() => window.__spike.serialize());
    const groups = await page.evaluate(() => window.__spike.groups());
    const rects = async () => page.evaluate(() => Object.fromEntries(["chart-host"].map((id) => { const r = document.querySelector(`[data-testid="${id}"]`).getBoundingClientRect(); return [id, [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]]; })));
    const rectBefore = await rects();
    await page.reload();
    await page.waitForFunction(() => window.__spike?.groups && window.__spike.live >= 1 && document.querySelector(".u-over"));
    await page.waitForTimeout(500);
    const after = await snap(page);
    const json2 = await page.evaluate(() => window.__spike.serialize());
    const out = {
      jsonBytes: json.length, jsonBytesUtf8: Buffer.byteLength(json),
      groupsBefore: groups, groupsAfterReload: after.groups,
      sameGroups: JSON.stringify(norm(groups)) === JSON.stringify(norm(after.groups)),
      sameGroupsExactOrder: JSON.stringify(groups) === JSON.stringify(after.groups),
      jsonIdenticalAfterRestore: json === json2,
      jsonDiffAfterRestore: json === json2 ? null : diffs(JSON.parse(json), JSON.parse(json2)).slice(0, 12),
      chartDrawnAfterReload: after.canvasInkPixels > 1000, liveChartsAfterReload: after.live,
      chartHostRectBefore: rectBefore, chartHostRectAfter: await rects(),
      jsonPreview: json.slice(0, 400),
    };
    await ctx.close();
    return out;
  },

  // 4. Splitter resize cost (prod build, headed): 300 px in 30 steps, frame times.
  async 4(browser, lib) {
    const s = SEL[lib];
    const reps = [];
    for (let r = 0; r < RUNS; r++) {
      const { ctx, page } = await open(browser, lib);
      // pick the vertical bar (tallest sash) between the left group and the right column
      const sashIdx = await page.evaluate((sel) => {
        const els = [...document.querySelectorAll(sel)];
        let best = -1, h = 0;
        els.forEach((e, i) => { const b = e.getBoundingClientRect(); if (b.width > 0 && b.height > h && b.height > b.width) { h = b.height; best = i; } });
        return best;
      }, s.sash);
      const sash = page.locator(s.sash).nth(sashIdx);
      const sb = await sash.boundingBox();
      const widthBefore = await page.evaluate(() => document.querySelector('[data-testid="chart-host"]').clientWidth);
      await page.evaluate(() => {
        const t = []; window.__frames = t; window.__rafStop = false;
        const loop = (ts) => { t.push(ts); if (!window.__rafStop) requestAnimationFrame(loop); };
        requestAnimationFrame(loop);
        window.__spike.resizeEvents = 0;
      });
      await page.waitForTimeout(150);
      const sx = sb.x + sb.width / 2, sy = sb.y + sb.height * 0.25; // away from the T-junction with the horizontal splitter
      await page.mouse.move(sx, sy);
      await page.waitForTimeout(100);
      await page.mouse.down();
      const t0 = await page.evaluate(() => performance.now());
      for (let i = 1; i <= 30; i++) { await page.mouse.move(sx + 10 * i, sy); await page.waitForTimeout(16); }
      await page.mouse.up();
      await page.waitForTimeout(300);
      const res = await page.evaluate((t0) => {
        window.__rafStop = true;
        const f = window.__frames.filter((x) => x >= t0);
        const d = []; for (let i = 1; i < f.length; i++) d.push(f[i] - f[i - 1]);
        const host = document.querySelector('[data-testid="chart-host"]');
        const u = window.__spike.chart;
        return { deltas: d, hostW: host.clientWidth, hostH: host.clientHeight, uW: u.width, uH: u.height, resizeEvents: window.__spike.resizeEvents };
      }, t0);
      reps.push({
        widthBefore, widthAfter: res.hostW, grew: res.hostW - widthBefore, chartFollows: res.uW === res.hostW && res.uH === res.hostH,
        frames: res.deltas.length, medianFrameMs: +median(res.deltas).toFixed(2), worstFrameMs: +Math.max(...res.deltas).toFixed(2),
        framesOver33ms: res.deltas.filter((x) => x > 33).length, resizeEvents: res.resizeEvents,
      });
      await ctx.close();
    }
    return {
      reps, medianOfMedianFrameMs: +median(reps.map((x) => x.medianFrameMs)).toFixed(2), worstFrameMsAcrossReps: Math.max(...reps.map((x) => x.worstFrameMs)),
      medianOfWorstFrameMs: +median(reps.map((x) => x.worstFrameMs)).toFixed(2), allChartsEndAtPanelSize: reps.every((x) => x.chartFollows),
    };
  },

  // 5. Floating panel and pop-out window.
  async 5(browser, lib) {
    const out = {};
    {
      const { ctx, page, msgs } = await open(browser, lib);
      const before = await snap(page);
      let err = null;
      try { await page.evaluate(() => window.__spike.floatChart()); } catch (e) { err = String(e).slice(0, 200); }
      await page.waitForTimeout(1000);
      const a = await snap(page);
      const floatEl = await page.evaluate(() => document.querySelector(".dv-resize-container, .flexlayout__float_window")?.className ?? null);
      out.floating = { error: err, floatElement: floatEl, groups: a.groups, mountDelta: a.mounts - before.mounts, unmountDelta: a.unmounts - before.unmounts, chartDrawn: a.canvasInkPixels > 1000, hostRect: a.hostRect, uplotSize: a.uplotSize, consoleErrors: summarise(msgs).errorsAndWarnings };
      await ctx.close();
    }
    {
      const { ctx, page, msgs } = await open(browser, lib);
      const before = await snap(page);
      let err = null, popup = null;
      try { await page.evaluate(() => window.__spike.popoutChart()); } catch (e) { err = String(e).slice(0, 200); }
      await page.waitForTimeout(2500);
      popup = ctx.pages().filter((p) => p !== page && !p.isClosed()).pop() ?? null;

      const info = { error: err, popupOpened: !!popup, popupUrl: popup ? popup.url() : null, windowsOpenedIncludingClosed: ctx.pages().length - 1 };
      if (popup) {
        const inPopup = await popup.evaluate(() => {
          const host = document.querySelector('[data-testid="chart-host"]');
          const cv = host?.querySelector("canvas");
          let ink = 0;
          if (cv) { const d = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) ink++; }
          return { chartHostInPopup: !!host, canvasInkPixels: ink, hostSize: host ? [host.clientWidth, host.clientHeight] : null, popupInner: [innerWidth, innerHeight] };
        }).catch((e) => ({ error: String(e).slice(0, 200) }));
        info.popup = inPopup;
        // resize the popup window: does the chart follow?
        await popup.setViewportSize({ width: 500, height: 400 }).catch((e) => { info.resizeError = String(e).slice(0, 120); });
        await page.waitForTimeout(800);
        info.afterPopupResize = { uplot: await page.evaluate(() => { const u = window.__spike.chart; return u ? [u.width, u.height] : null; }), hostAndInner: await popup.evaluate(() => { const h = document.querySelector('[data-testid="chart-host"]'); return h ? [h.clientWidth, h.clientHeight, innerWidth, innerHeight] : null; }).catch(() => null) };
      }
      const a = await snap(page).catch((e) => ({ error: String(e) }));
      info.mainWindow = { mountDelta: a.mounts - before.mounts, unmountDelta: a.unmounts - before.unmounts, live: a.live, groups: a.groups };
      info.consoleErrors = summarise(msgs).errorsAndWarnings;
      out.popout = info;
      if (popup) await popup.close().catch(() => {});
      await ctx.close();
    }
    return out;
  },

  // 6. Keyboard + roles + axe.
  async 6(browser, lib) {
    const s = SEL[lib];
    const { ctx, page } = await open(browser, lib);
    const out = {};
    out.roles = await page.evaluate(() => {
      const c = (sel) => document.querySelectorAll(sel).length;
      return { tablist: c('[role="tablist"]'), tab: c('[role="tab"]'), tabSelectedTrue: c('[role="tab"][aria-selected="true"]'), tabSelectedFalse: c('[role="tab"][aria-selected="false"]'), tabpanel: c('[role="tabpanel"]'), ariaControls: c('[role="tab"][aria-controls]'), buttonsInTabs: c('[role="tab"] [role="button"]'), separators: c('[role="separator"]') };
    });
    // Keyboard only: press Tab until a tab button is focused.
    const describe = () => page.evaluate(() => { const a = document.activeElement; return { role: a?.getAttribute("role"), aria: a?.getAttribute("aria-label"), tag: a?.tagName, text: (a?.textContent ?? "").trim().slice(0, 20) }; });
    let presses = 0, reached = null;
    const trail = [];
    for (; presses < 25; presses++) {
      await page.keyboard.press("Tab");
      const d = await describe(); trail.push(d);
      if (d.role === "tab") { reached = d; presses++; break; }
    }
    out.keyboard = { tabKeyPressesToReachFirstTab: reached ? presses : null, firstTabFocused: reached, trail: trail.slice(0, 6) };
    const selectedLabel = () => page.evaluate(() => [...document.querySelectorAll('[role="tab"][aria-selected="true"]')].map((e) => e.getAttribute("aria-label")));
    const base = await selectedLabel();
    out.keyboard.selectedAtStart = base;
    // Which keys change the selected tab / move focus within the strip?
    const trial = async (key) => {
      const f0 = await describe(); const s0 = await selectedLabel();
      await page.keyboard.press(key); await page.waitForTimeout(250);
      const f1 = await describe(); const s1 = await selectedLabel();
      return { key, focusBefore: f0.aria, focusAfter: f1.aria, focusMoved: f0.aria !== f1.aria, selectedBefore: s0, selectedAfter: s1, selectionChanged: JSON.stringify(s0) !== JSON.stringify(s1) };
    };
    out.keyboard.keys = [];
    for (const k of ["ArrowRight", "Enter", "ArrowLeft", " ", "Tab", "Enter", "ArrowRight", "Home", "End"]) out.keyboard.keys.push(await trial(k));
    // Can keyboard-only reach the other tab and then switch to it (Tab to it, Enter / Space)?
    const treeTab = page.locator(s.tab("tree"));
    await treeTab.focus();
    for (const k of ["Enter", " "]) {
      await page.locator(s.tab("chart")).click(); // reset
      await treeTab.focus(); await page.keyboard.press(k); await page.waitForTimeout(250);
      out.keyboard["switchByFocusAnd" + (k === " " ? "Space" : k)] = (await selectedLabel()).includes("Data tree");
    }
    // Panel's own controls reachable by keyboard
    await page.locator(s.tab("inspector")).focus();
    let found = false;
    for (let i = 0; i < 12 && !found; i++) { await page.keyboard.press("Tab"); const d = await describe(); if (d.tag === "BUTTON" && /inspector clicks/.test(d.text) || (d.tag === "INPUT")) found = true; }
    out.keyboard.panelControlsReachableByTab = found;
    const axe = await new AxeBuilder({ page }).analyze();
    out.axe = { phase, violationsByRule: axe.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })), violationRuleCount: axe.violations.length, violationNodeCount: axe.violations.reduce((n, v) => n + v.nodes.length, 0), passes: axe.passes.length, incomplete: axe.incomplete.map((v) => ({ id: v.id, nodes: v.nodes.length })) };
    await ctx.close();
    return out;
  },

  // 10 (extra). Does the chart survive its tab being hidden and shown again (inactive tab)?
  async 10(browser, lib) {
    const s = SEL[lib];
    const { ctx, page } = await open(browser, lib);
    const before = await snap(page);
    await page.locator(s.tab("tree")).click(); await page.waitForTimeout(500);
    const hidden = await snap(page);
    const inDomWhileHidden = await page.locator(".u-over").count();
    await page.locator(s.tab("chart")).click(); await page.waitForTimeout(500);
    const back = await snap(page);
    await ctx.close();
    return { phase, mountsBefore: before.mounts, afterHide: { mountDelta: hidden.mounts - before.mounts, unmountDelta: hidden.unmounts - before.unmounts, chartCanvasesInDom: inDomWhileHidden }, afterShow: { mountDelta: back.mounts - before.mounts, unmountDelta: back.unmounts - before.unmounts, sameInstance: back.instance === before.instance, drawn: back.canvasInkPixels > 1000, sameData: back.checksum === before.checksum, uplotMatchesHost: JSON.stringify(back.uplotSize) === JSON.stringify(back.hostRect) } };
  },

  // 7. Theming via CSS custom properties.
  async 7(browser, lib) {
    const { ctx, page } = await open(browser, lib);
    const cfg = lib === "dockview"
      ? { rootSel: ".dockview-theme-abyss", probe: ".dv-tab.dv-active-tab", probe2: ".dv-groupview", vars: { "--dv-activegroup-visiblepanel-tab-background-color": ["rgb(255, 0, 0)", "rgb(0, 128, 0)"], "--dv-group-view-background-color": ["rgb(0, 0, 255)", "rgb(255, 255, 0)"], "--dv-tabs-and-actions-container-height": ["50px", "30px"] } }
      : { rootSel: ":root", probe: ".flexlayout__tab_button--selected", probe2: ".flexlayout__tabset", vars: { "--flexlayout-color-tab-selected-background": ["rgb(255, 0, 0)", "rgb(0, 128, 0)"], "--flexlayout-color-background": ["rgb(0, 0, 255)", "rgb(255, 255, 0)"] } };
    const read = (c) => page.evaluate((c) => {
      const bg = (sel) => { const e = document.querySelector(sel); return e ? getComputedStyle(e).backgroundColor : null; };
      const tabsH = document.querySelector(c.lib === "dockview" ? ".dv-tabs-and-actions-container" : ".flexlayout__tabset_tabbar_outer")?.getBoundingClientRect().height;
      return { probe: bg(c.probe), probe2: bg(c.probe2), tabsHeight: tabsH };
    }, { ...c, lib });
    const baseline = await read(cfg);
    const results = { baseline };
    for (const idx of [0, 1]) {
      await page.evaluate(({ rootSel, vars, idx }) => { for (const el of document.querySelectorAll(rootSel)) for (const [k, v] of Object.entries(vars)) el.style.setProperty(k, v[idx]); }, { rootSel: cfg.rootSel, vars: cfg.vars, idx });
      await page.waitForTimeout(150);
      results[idx === 0 ? "tokenSetA" : "tokenSetB"] = await read(cfg);
    }
    results.varsSet = Object.fromEntries(Object.entries(cfg.vars).map(([k, v]) => [k, v]));
    results.scope = lib === "dockview" ? "variables are defined on the theme class element (.dockview-theme-*); the class appears on two nested elements (shell and inner), and the inner one re-declares the variables, so the override must be set on every element carrying the class (setting it only on the outer one had no effect, measured)" : "global --flexlayout-* overrides set on :root";
    await ctx.close();
    return results;
  },
};

const out = { phase, date: new Date().toISOString(), results: {} };
let srv;
if (phase === "dev") { srv = await createServer({ server: { port: PORT, strictPort: true, host: "127.0.0.1" }, logLevel: "error" }); await srv.listen(); }
else srv = await preview({ preview: { port: PORT, strictPort: true, host: "127.0.0.1" }, logLevel: "error" });
const browser = await chromium.launch({ headless: false });
try {
  const ctx0 = await browser.newContext(); const p0 = await ctx0.newPage(); await p0.goto(`${BASE}?lib=none`);
  out.env = { version: browser.version(), gpu: await p0.evaluate(() => { const c = document.createElement("canvas"); const gl = c.getContext("webgl"); const e = gl?.getExtension("WEBGL_debug_renderer_info"); return gl && e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : null; }) };
  await ctx0.close();
  for (const lib of LIBS) {
    out.results[lib] = {};
    for (const it of ITEMS) {
      try { out.results[lib][it] = await items[it](browser, lib); }
      catch (e) { out.results[lib][it] = { error: String(e).slice(0, 600) }; }
      console.log(`[${phase}] ${lib} item ${it} done`);
    }
  }
} finally {
  await browser.close();
  if (srv?.close) await srv.close();
  else if (srv?.httpServer) await new Promise((r) => srv.httpServer.close(r));
}
writeFileSync(new URL(`./results-${phase}${arg("tag", "") ? "-" + arg("tag", "") : ""}.json`, import.meta.url), JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
