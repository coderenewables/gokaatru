export interface TimelineData {
  kind: "timeline";
  x: Float64Array;
  ys: Float32Array[];
  xmin: number;
  xmax: number;
}
export interface ScatterData {
  kind: "scatter";
  x: Float32Array;
  y: Float32Array;
}
export type Data = TimelineData | ScatterData;

export interface Payload {
  /** Indices as delivered by the library, when it delivers them. */
  indices?: ArrayLike<number>;
  /** Selection bounds in data units, as reported by the library. */
  range?: { x?: [number, number]; y?: [number, number] };
  /** Selection polygon in canvas pixels (lasso). */
  poly?: [number, number][];
  /** Count of indices the library itself delivered, when it also fell back to a range. */
  nativeCount?: number;
}

export interface Rect { left: number; top: number; width: number; height: number }

export interface Adapter {
  mount(el: HTMLElement, data: Data, onSelect: (p: Payload) => void): Promise<void>;
  /** Plot area in viewport (page) coordinates. */
  plot(): Rect;
  /** Data coordinates to viewport pixels (scatter). */
  toPage(x: number, y: number): [number, number];
  /** Paint a selection. fromBrush: the library already painted its own native brush result. */
  setSelection(indices: ArrayLike<number>, fromBrush: boolean): Promise<void>;
  zoom(frac: number): Promise<void>;
  /** Key to hold during the drag (lasso initiators). */
  modifier?: string;
  /** Canvas origin in viewport coordinates, for polygon tests. */
  canvasOrigin?(): [number, number];
  destroy(): void;
}

export const TL_W = 1600;
export const TL_H = 420;
export const SC_S = 800;
export const HI_COLOR = "#e4572e";
