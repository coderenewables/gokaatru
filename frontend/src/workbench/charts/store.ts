import { create } from "zustand";

import type { DropHandler } from "../dnd";

// Which channels each chart draws. A chart starts from its default (the timeline: the wind
// speeds; the scatter: the two highest speeds; the rose: the vane nearest the top) and the
// analyst changes it by dropping a channel from the data tree onto it (plan §3.3 "Any
// chart"), or with the chart's own picker, which is the keyboard route to the same thing.

export interface ChartChannels {
  /** null until the analyst picks: the chart then shows its default. */
  timeline: string[] | null;
  scatter: { x: string; y: string } | null;
  rose: string | null;
}

interface ChartStore extends ChartChannels {
  /** Add a channel to the timeline, after the ones it shows (``shown``: its current list). */
  addToTimeline: (channel: string, shown: string[]) => void;
  removeFromTimeline: (channel: string, shown: string[]) => void;
  setScatterAxis: (axis: "x" | "y", channel: string, shown: { x: string; y: string }) => void;
  setRose: (channel: string) => void;
  reset: () => void;
}

const DEFAULTS: ChartChannels = { timeline: null, scatter: null, rose: null };

/** A channel dropped on a chart (``dnd.tsx``) goes into that chart's channels. */
export const dropOnChart: DropHandler = (channel, target) => {
  const charts = useCharts.getState();
  if (target.kind === "timeline") charts.addToTimeline(channel, target.shown);
  else if (target.kind === "scatter") charts.setScatterAxis(target.axis, channel, target.shown);
  else charts.setRose(channel);
};

export const useCharts = create<ChartStore>((set) => ({
  ...DEFAULTS,
  addToTimeline: (channel, shown) =>
    set(() => ({ timeline: shown.includes(channel) ? shown : [...shown, channel] })),
  removeFromTimeline: (channel, shown) => set(() => ({ timeline: shown.filter((name) => name !== channel) })),
  setScatterAxis: (axis, channel, shown) => set(() => ({ scatter: { ...shown, [axis]: channel } })),
  setRose: (channel) => set(() => ({ rose: channel })),
  reset: () => set(() => ({ ...DEFAULTS })),
}));
