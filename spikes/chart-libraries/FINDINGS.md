# Chart library spike: findings (P0-11)

**Question.** Which chart library can carry the workbench's linked, brushable views at the
owner's target scale of 5 years × 10-minute data × 60 channels (262,800 points per
channel, about 15.8 million values)?

**Answer.** uPlot for time series and regl-scatterplot for scatters. They are the only
libraries tested that meet both budgets (first render under 1 s, brush under 100 ms) at one
channel and at the scatter. Sixty channels are served decimated, with a level-of-detail
refetch on zoom. Plotly stays only for the existing server-built static figures until they
are replaced. ECharts is not used.

Measured 2026-11-18/19 by `run.mjs` in this folder (Playwright driving Chromium). Results:
`results-headed.json` / `.md` (the table below) and `results-headless-gpu.json` / `.md`.

## Environment

| Item | Value |
| --- | --- |
| CPU | Intel Core i5-10210U, 4 cores / 8 threads |
| RAM | 15.8 GB |
| GPU | Intel UHD Graphics (integrated), driver 30.0.101.1122 |
| OS, Node | Windows 11, Node 22.17 |
| Browser | Chromium 159.0.8154.6 (Playwright 1.65.1) |
| WebGL renderer, headed | ANGLE (Intel UHD Graphics Direct3D11): hardware |
| WebGL renderer, default headless | SwiftShader: software |
| WebGL renderer, headless with `--use-angle=d3d11 --ignore-gpu-blocklist --enable-gpu` | Intel hardware |

An integrated laptop GPU is a reasonable floor for an analyst's machine, not a typical
workstation. A faster machine moves every number down; it does not change the ranking.

## Versions (exact pins)

plotly.js-dist-min 4.3.0; plotly.js-dist-min 2.35.3 (the version `frontend/` ships, as the
alias `plotly-v2`); echarts 6.1.0 (tree-shaken, canvas renderer); uplot 1.6.32;
regl-scatterplot 1.16.0 with regl 2.1.1 and pub-sub-es 3.0.0; vite 6.4.3; typescript 5.9.3;
@playwright/test 1.65.1. Vite and TypeScript are the frontend's installed versions, not the
newest.

## Method

- **Data.** Generated in the page from a fixed seed: an autocorrelated wind-speed-like
  series with daily and seasonal cycles, 0-25 m/s, with NaN gap runs. The scatter is a
  second, correlated series, compacted to the 252,665 pairs where both are valid.
- **Cases.** `timeline-1`: one channel, 262,800 points. `timeline-6`: six overlaid channels,
  1.58 million points. `timeline-60-decimated`: 60 channels, each reduced in the page to
  min/max per bucket for a 1,600 px plot (3,200 points per channel), as a server would send.
  `scatter-1`: 252,665 points.
- **Runs.** One warm-up, then 5 runs, each in a fresh browser context. Median [min-max].
- **Paint barrier.** `requestAnimationFrame`, then a forced `readPixels` on every WebGL
  canvas, then one macrotask; ECharts also waits for its `finished` event. An empty page
  measures 17.5 ms, which is inside every figure. It is a lower bound on true paint time.
- **First render.** From data ready to the barrier after mounting.
- **Brush latency.** From the `pointerup` timestamp of a Playwright drag over 20% of the x
  range (timelines) or a box over a dense region (scatter) to: selection delivered, indices
  known, highlight painted, barrier passed.
- **Highlight redraw.** A selection of 50,000 indices set programmatically, as a linked
  view would, to painted. On the decimated case it maps to about 640 bucket points.
- **Zoom step.** One programmatic zoom into 10% of the range, to painted.
- **Heap.** `usedJSHeapSize` after garbage collection. It excludes typed-array backing
  stores, so it understates the uPlot and regl figures most.
- **Selected-count check.** The library's selection against an independent linear scan of
  the data with the library's reported bounds, or its lasso polygon.

## Results, headed Chromium, hardware GPU (ms)

| Library | Case | First render | Brush latency | Highlight redraw | Zoom step | Heap after (MB) |
| --- | --- | --- | --- | --- | --- | --- |
| Plotly 4.3.0 | timeline-1 | 455 [438-515] | 478 [466-554] | 286 [258-361] | 169 [142-184] | 88 |
| Plotly 4.3.0 | timeline-6 | 1,218 [1,147-1,423] | 1,584 [1,528-2,077] | 1,185 [1,165-1,620] | 570 [554-749] | 416 |
| Plotly 4.3.0 | timeline-60-decimated | 589 [573-610] | 1,396 [1,375-1,444] | 794 [696-852] | 384 [317-388] | 50 |
| Plotly 4.3.0 | scatter-1 | 407 [400-463] | 182 [177-188] | 326 [319-345] | 149 [145-151] | 89 |
| Plotly 2.35.3 | timeline-1 | 489 [452-528] | 486 [460-546] | 267 [263-277] | 127 [114-140] | 98 |
| Plotly 2.35.3 | timeline-6 | 1,226 [1,212-1,245] | 1,582 [1,543-1,677] | 1,175 [1,137-1,250] | 555 [493-601] | 426 |
| Plotly 2.35.3 | timeline-60-decimated | 615 [590-634] | 1,425 [1,356-1,441] | 746 [663-853] | 335 [309-405] | 61 |
| Plotly 2.35.3 | scatter-1 | 424 [411-429] | 176 [65-182] | 298 [287-326] | 123 [120-124] | 100 |
| ECharts 6.1.0 | timeline-1 | 123 [120-130] | 245 [225-276] | 168 [140-215] | 86 [69-92] | 37 |
| ECharts 6.1.0 | timeline-6 | 263 [256-272] | 1,014 [973-1,041] | 781 [742-805] | 324 [290-343] | 143 |
| ECharts 6.1.0 | timeline-60-decimated | 229 [221-284] | 923 [859-1,036] | 844 [740-902] | 447 [422-487] | 85 |
| ECharts 6.1.0 | scatter-1 | 663 [606-703] | 922 [801-1,028] | 766 [713-886] | 75 [72-85] | 33 |
| uPlot 1.6.32 | timeline-1 | **62** [60-77] | **19.7** [16.3-32.5] | 9.8 [8.4-12.6] | 37 [34-43] | 11 |
| uPlot 1.6.32 | timeline-6 | 230 [216-273] | **61** [56-76] | 512 [499-551] | 554 [503-641] | 37 |
| uPlot 1.6.32 | timeline-60-decimated | **67** [65-70] | **15.3** [14.6-15.6] | 14.6 [14.1-15.0] | 68 [65-74] | 10 |
| regl-scatterplot 1.16.0 | scatter-1 | **256** [244-258] | **50.0** [49.5-51.4] | 11.3 [9.0-12.0] | 30 [23-33] | 41 |

In the results files the regl-scatterplot row is labelled `uplot | scatter-1`: it is the
uPlot page's scatter case, which uses regl-scatterplot.

Decimating 60 channels to 1,600 buckets took 79.6 ms median in the page. Generating the 60
channels took about 1.4 s and is not in any render figure.

**Bundle size** (minified, before gzip / gzip): Plotly 4.3.0 4.80 MB / 1.48 MB; Plotly 2.35.3
4.68 MB / 1.42 MB; ECharts, tree-shaken, 544 kB / 185 kB; uPlot 52 kB / 23 kB;
regl-scatterplot with regl 224 kB / 77 kB.

### Against the budget (first render ≤ 1,000 ms, brush ≤ 100 ms)

| Library | timeline-1 | scatter-1 |
| --- | --- | --- |
| Plotly 4.3.0 | render meets (455), brush misses (478) | render meets (407), brush misses (182) |
| Plotly 2.35.3 | render meets (489), brush misses (486) | render meets (424), brush misses (176) |
| ECharts 6.1.0 | render meets (123), brush misses (245) | render meets (663), brush misses (922) |
| uPlot / regl-scatterplot | **both meet** (62, 19.7) | **both meet** (256, 50.0) |

## Where the brush time goes (headed medians, ms)

| Library | Case | Pointer-up to callback | Callback to indices | Indices to painted |
| --- | --- | --- | --- | --- |
| Plotly 4.3.0 | timeline-1 | 110.6 | 1.8 | 370.8 |
| Plotly 4.3.0 | scatter-1 | 155.5 | 0.0 | 26.8 |
| ECharts 6.1.0 | timeline-1 | 4.9 | 2.7 | 239.2 |
| ECharts 6.1.0 | scatter-1 | 3.3 | 4.1 | 917.0 |
| uPlot 1.6.32 | timeline-1 | 1.2 | 3.3 | 15.2 |
| regl-scatterplot | scatter-1 | 33.0 | 0.0 | 16.9 |

Plotly spends over 100 ms before its own selection callback fires, before any highlight is
drawn, so a faster overlay cannot bring it under budget. ECharts' callback is fast, and its
cost is the redraw; a cheaper highlight might recover part of it, but not the 917 ms scatter.

## Selected-count correctness

| Library | Case | Library | Reference | Agree |
| --- | --- | --- | --- | --- |
| All | timeline-1, timeline-6 | 51,822 | 51,822 | yes (range reported; indices computed in the page) |
| All | timeline-60-decimated | 640 | 640 | yes (range reported) |
| ECharts | scatter-1 | 53,839 | 53,839 | yes (range reported) |
| Plotly 4.3.0 and 2.35.3 | scatter-1 | 53,828 | 53,817 | **no, 11 extra (0.02%)**, cause not investigated |
| regl-scatterplot | scatter-1 | 50,301 | 50,302 | **no, 1 missing**: the reference uses the lasso polygon from `lassoEnd`, rounded to about 4 decimals in normalised coordinates and about 3 px from the dragged path |

Whichever library is used, the selection the server acts on must be the bounds the analyst
drew, resolved to record indices on the server, never the index list a chart reports. That
makes the two disagreements above harmless, and keeps the workbench's selection exact.

## Native versus hand-written

| Library | Native | Hand-written in this spike |
| --- | --- | --- |
| Plotly | Box select, zoom; `selectedpoints` highlight on the scatter | Highlight overlay trace on timelines, because `scattergl` with `mode: "lines"` delivers **no** selected points (both versions) |
| ECharts | `brush` (lineX, rect), `dataZoom` | Overlay series for every highlight; range fallback, because `brushselected` delivers no indices for `sampling: "lttb"` or `large` series |
| uPlot | Drag-to-select, `setScale` zoom | Highlight as a canvas draw hook; NaN-to-null conversion for gaps |
| regl-scatterplot | Rectangle lasso (Shift-drag), selection highlight, zoom | Normalising data to normalised device coordinates |

Adapter files: `src/libs/plotly.ts` 89 lines, `echarts.ts` 127, `uplot.ts` 87, `regl.ts` 67. A
line count of the hand-written parts alone was not made.

## Weaknesses of this measurement

- **One machine, one browser.** No Firefox, no Safari, no discrete GPU.
- **The paint barrier is a lower bound.** Real time-to-pixels is somewhat higher for every
  library alike.
- **Highlights are this spike's own code for most libraries.** A better overlay could
  improve ECharts' and Plotly's redraw figures, but not the time before Plotly's callback.
- **uPlot's timeline-6 highlight (512 ms) and zoom (554 ms)** come from this spike drawing
  the 300,000-marker highlight overlay on every redraw. Drawing a selection as shaded x
  ranges instead of markers, which is what the workbench does, avoids it. This is not yet
  measured.
- **Raw 60 channels at full resolution were not measured, by design.** Only the decimated
  case was.
- **Software rendering.** Default headless Chromium uses SwiftShader, and Plotly there was
  about 10× slower at first render (4-5 s) and about 37× at brush (about 17.8 s) on
  single runs at timeline-1; one Plotly 2.35.3 scatter run crashed the page. The reduced
  software pass (2 runs) was stopped unfinished on 2026-11-19 because the decision does not
  depend on it. Browser tests in CI run headless and will be slower than an analyst sees;
  timing assertions belong in local headed runs, not in CI.
- **Unexplained outlier.** With GPU flags in headless mode, Plotly 4.3.0's
  timeline-60-decimated brush took 3,038 ms against 1,396 ms headed. Every other headless-GPU
  figure matched headed within noise. Not investigated.
- **Not tested.** A Plotly `lines+markers` variant, and the newest Vite (8.3.8) and
  TypeScript (7.0.2).

## Recommendation, and the numbers that decide it

1. **Time series: uPlot.** It is the only library under 100 ms brush at one channel
   (19.7 ms) and at six (61 ms), and it renders one channel in 62 ms. Plotly's brush is 478 ms
   and ECharts' 245 ms at one channel.
2. **Scatter: regl-scatterplot.** 256 ms first render and 50 ms brush with a native lasso,
   against Plotly's 182 ms and ECharts' 922 ms brush.
3. **Sixty channels: decimate on the server and refetch on zoom.** Decimated to 3,200
   points per channel, uPlot renders in 67 ms and brushes in 15 ms; the decimation itself is
   about 80 ms for 60 channels. The full 15.8 million values never go to the browser.
4. **Selections are bounds, resolved on the server.** See the correctness section.
5. **Plotly remains for the existing server-built figures** (wind rose, profiles, and the
   other `plotly_json` views) until each is replaced. They are small and static, so its
   speed does not matter there, but its 1.42 MB gzip bundle should be loaded only by the
   views that use it.

These choices are recorded as an architecture decision in P0-13.
