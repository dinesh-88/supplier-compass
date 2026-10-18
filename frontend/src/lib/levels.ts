import type { Band } from "./api";

// One hue, light → dark, so levels differ in lightness as well as being labelled.
export const LEVEL_COLORS: Record<string, string> = {
  Low: "#e8a177",
  Medium: "#d26a3c",
  High: "#a6401c",
  Critical: "#661c0b",
};
export const LEVEL_TEXT: Record<string, string> = {
  Low: "#3b1d0c",
  Medium: "#ffffff",
  High: "#ffffff",
  Critical: "#ffffff",
};
const FALLBACK = ["#e8a177", "#d26a3c", "#a6401c", "#661c0b", "#3d1006"];

export function levelColor(level: string, bands?: Band[]): string {
  if (LEVEL_COLORS[level]) return LEVEL_COLORS[level];
  const i = bands ? bands.findIndex((b) => b.level === level) : -1;
  return FALLBACK[Math.max(0, Math.min(FALLBACK.length - 1, i))];
}

export function levelText(level: string): string {
  return LEVEL_TEXT[level] ?? "#ffffff";
}

export function levelOf(value: number, bands: Band[]): string {
  let label = bands[0]?.level ?? "";
  for (const b of bands) if (value >= b.min) label = b.level;
  return label;
}

export const ACCENT = "#00727f";
export const COOL = "#00727f"; // below average (less risk)
export const WARM = "#a6401c"; // above average (more risk)
export const MUTED = "#c3c8ce";

export const fmtEur = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (v >= 1e6) return `€${(v / 1e6).toFixed(v >= 1e7 ? 1 : 2)}M`;
  if (v >= 1e3) return `€${(v / 1e3).toFixed(0)}k`;
  return `€${v.toFixed(0)}`;
};
export const fmtPct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${v.toFixed(d)}%`;
export const fmtSigned = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(d)}`;
