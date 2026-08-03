/// <reference types="vite/client" />

declare module 'react-plotly.js' {
  import type { ComponentType, CSSProperties } from 'react';

  interface PlotProps {
    data: unknown[];
    layout?: Record<string, unknown>;
    config?: Record<string, unknown>;
    style?: CSSProperties;
  }

  const Plot: ComponentType<PlotProps>;
  export default Plot;
}
