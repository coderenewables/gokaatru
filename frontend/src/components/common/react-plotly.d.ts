// Minimal type shim for react-plotly.js (no @types/react-plotly.js shipped).
declare module "react-plotly.js" {
  import type { ComponentType } from "react";
  interface PlotProps {
    data?: unknown[];
    layout?: unknown;
    config?: unknown;
    style?: React.CSSProperties;
    className?: string;
    onInitialized?: (figure: unknown, graphDiv: unknown) => void;
    onUpdate?: (figure: unknown, graphDiv: unknown) => void;
    [key: string]: unknown;
  }
  const Plot: ComponentType<PlotProps>;
  export default Plot;
}
