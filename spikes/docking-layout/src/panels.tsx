import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { genChannel, timeAxis } from "./data";

export interface Spike {
  lib: string;
  mounts: number;
  unmounts: number;
  live: number;
  instanceSeq: number;
  chart: uPlot | null;
  resizeEvents: number;
  [k: string]: unknown;
}
declare global {
  interface Window {
    __spike: Spike;
  }
}

export const spike: Spike = ((window as unknown as { __spike?: Spike }).__spike = {
  lib: "",
  mounts: 0,
  unmounts: 0,
  live: 0,
  instanceSeq: 0,
  chart: null,
  resizeEvents: 0,
});

let data: [Float64Array, Float32Array] | null = null;
function getData(): [Float64Array, Float32Array] {
  if (!data) data = [timeAxis(), genChannel(0)];
  return data;
}

export function ChartPanel() {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = host.current!;
    spike.mounts++;
    spike.live++;
    const id = ++spike.instanceSeq;
    el.dataset.instance = String(id);
    const w = Math.max(50, el.clientWidth);
    const h = Math.max(50, el.clientHeight);
    const u = new uPlot(
      { width: w, height: h, scales: { x: { time: false } }, series: [{}, { stroke: "#1f77b4", width: 1 }], legend: { show: false } },
      getData() as unknown as uPlot.AlignedData,
      el,
    );
    spike.chart = u;
    const ro = new ResizeObserver(() => {
      spike.resizeEvents++;
      const cw = el.clientWidth;
      const ch = el.clientHeight;
      if (cw > 0 && ch > 0 && (cw !== u.width || ch !== u.height)) u.setSize({ width: cw, height: ch });
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      u.destroy();
      spike.unmounts++;
      spike.live--;
      if (spike.chart === u) spike.chart = null;
    };
  }, []);
  return <div ref={host} data-testid="chart-host" style={{ width: "100%", height: "100%", overflow: "hidden" }} />;
}

export function Placeholder({ name }: { name: string }) {
  const [n, setN] = useState(0);
  return (
    <div style={{ padding: 8 }} data-testid={`panel-${name}`}>
      <div>{name} placeholder</div>
      <button onClick={() => setN(n + 1)}>{name} clicks: {n}</button> <input aria-label={`${name} input`} defaultValue="" />
    </div>
  );
}
