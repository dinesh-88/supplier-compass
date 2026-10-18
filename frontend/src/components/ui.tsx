import { useEffect, type ReactNode } from "react";
import { levelColor, levelText } from "../lib/levels";
import type { Band } from "../lib/api";

export function LevelChip({ level, value, bands, size = "sm" }: { level: string; value?: number | string; bands?: Band[]; size?: "sm" | "xs" }) {
  const pad = size === "xs" ? "px-1.5 py-0 text-[11px]" : "px-2 py-0.5 text-xs";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded font-medium whitespace-nowrap ${pad}`}
      style={{ background: levelColor(level, bands), color: levelText(level) }}
    >
      {value !== undefined && <span className="num font-semibold">{value}</span>}
      {level}
    </span>
  );
}

export function LevelLegend({ bands }: { bands: Band[] }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
      {bands.map((b) => (
        <span key={b.level} className="inline-flex items-center gap-1">
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: levelColor(b.level, bands) }} />
          {b.level} <span className="num text-ink-3">{b.min}–{b.max}</span>
        </span>
      ))}
    </div>
  );
}

export function RangeSlider({
  min,
  max,
  step = 1,
  value,
  onChange,
  format = (v: number) => String(v),
  label,
}: {
  min: number;
  max: number;
  step?: number;
  value: [number, number];
  onChange: (v: [number, number]) => void;
  format?: (v: number) => string;
  label: string;
}) {
  const [lo, hi] = value;
  const pct = (v: number) => ((v - min) / (max - min || 1)) * 100;
  const active = lo > min || hi < max;
  return (
    <div className="py-1">
      <div className="flex items-baseline justify-between gap-2 text-[13px]">
        <span className={active ? "font-medium text-ink" : "text-ink-2"}>{label}</span>
        <span className={`num text-xs ${active ? "text-accent font-medium" : "text-ink-3"}`}>
          {format(lo)} – {format(hi)}
        </span>
      </div>
      <div className="range2">
        <div className="track" />
        <div className="fill" style={{ left: `${pct(lo)}%`, width: `${pct(hi) - pct(lo)}%` }} />
        <input
          type="range"
          aria-label={`${label} minimum`}
          min={min}
          max={max}
          step={step}
          value={lo}
          onChange={(e) => onChange([Math.min(Number(e.target.value), hi), hi])}
        />
        <input
          type="range"
          aria-label={`${label} maximum`}
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => onChange([lo, Math.max(Number(e.target.value), lo)])}
        />
      </div>
    </div>
  );
}

/** Sparkline-style mini bar of category scores, coloured by level. */
export function MiniBars({ scores, bands, labels }: { scores: number[]; bands: Band[]; labels: string[] }) {
  const w = 3;
  const gap = 1;
  const h = 22;
  return (
    <svg width={scores.length * (w + gap)} height={h} aria-label="Category scores" className="block">
      <title>{scores.map((s, i) => `${labels[i]}: ${s}`).join("\n")}</title>
      {scores.map((s, i) => {
        let lvl = bands[0]?.level ?? "";
        for (const b of bands) if (s >= b.min) lvl = b.level;
        const bh = Math.max(1.5, (s / 100) * h);
        return <rect key={i} x={i * (w + gap)} y={h - bh} width={w} height={bh} rx={1} fill={levelColor(lvl, bands)} />;
      })}
    </svg>
  );
}

export function Tile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card px-4 py-3">
      <div className="label">{label}</div>
      <div className="num mt-1 text-2xl font-semibold text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: "neutral" | "accent" | "warn"; title?: string }) {
  const cls =
    tone === "accent"
      ? "bg-accent-soft text-accent-strong"
      : tone === "warn"
        ? "bg-amber-50 text-warn border border-amber-200"
        : "bg-canvas text-ink-2 border border-line";
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>
      {children}
    </span>
  );
}

export function Modal({ title, children, onClose, width = 520 }: { title: string; children: ReactNode; onClose: () => void; width?: number }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label={title}
        className="card max-h-[85vh] overflow-auto p-5 shadow-xl"
        style={{ width }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-3 text-lg font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-ink-3">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line-2 border-t-accent" />
      {label}
    </span>
  );
}

export function RankChange({ change }: { change: number }) {
  if (!change) return <span className="text-xs text-ink-3">no change</span>;
  const up = change > 0;
  return (
    <span
      className={`num text-xs font-medium ${up ? "text-accent" : "text-lv-high"}`}
      title={`${up ? "Up" : "Down"} ${Math.abs(change)} places under your weights`}
    >
      {up ? "↑" : "↓"} {Math.abs(change)} {Math.abs(change) === 1 ? "place" : "places"}
    </span>
  );
}
