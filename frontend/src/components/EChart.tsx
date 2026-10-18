import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, RadarChart, ScatterChart, TreeChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  HeatmapChart,
  RadarChart,
  ScatterChart,
  TreeChart,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

export const CHART_TEXT = { color: "#4b5259", fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif", fontSize: 12 };
export const AXIS = {
  axisLine: { lineStyle: { color: "#d0d4d9" } },
  axisTick: { show: false },
  splitLine: { lineStyle: { color: "#eef0f2", type: "solid" as const } },
  axisLabel: { color: "#737a82" },
  nameTextStyle: { color: "#4b5259" },
};

type Props = {
  option: echarts.EChartsCoreOption;
  height: number | string;
  onClick?: (params: echarts.ECElementEvent) => void;
  className?: string;
  ariaLabel?: string;
};

export default function EChart({ option, height, onClick, className, ariaLabel }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const clickRef = useRef(onClick);
  clickRef.current = onClick;

  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.current = c;
    c.on("click", (p) => clickRef.current?.(p as echarts.ECElementEvent));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption({ textStyle: CHART_TEXT, animation: false, ...option }, true);
  }, [option]);

  return <div ref={ref} style={{ height, width: "100%" }} className={className} role="img" aria-label={ariaLabel} />;
}
