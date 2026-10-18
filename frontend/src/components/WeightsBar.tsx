import { useState } from "react";
import { useStore } from "../lib/store";

export function weightsLabel(presetKey: string, presets: { key: string; label: string }[]): string {
  return presets.find((p) => p.key === presetKey)?.label ?? "Custom weights";
}

export default function WeightsBar() {
  const { meta, weights, setWeights, presetKey, isOfficial } = useStore();
  const [open, setOpen] = useState(false);
  if (!meta || !meta.loaded) return null;
  const presets = meta.presets;
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  const current = presets.find((p) => p.key === presetKey);

  return (
    <div className="card px-4 py-3" data-testid="weights-bar">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Your weights</span>
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Weight preset">
          {presets.map((p) => (
            <button
              key={p.key}
              role="radio"
              aria-checked={presetKey === p.key}
              title={p.why}
              onClick={() => setWeights(p.weights, p.key)}
              className={`rounded-md border px-2.5 py-1 text-[13px] ${presetKey === p.key ? "border-accent bg-accent-soft font-medium text-accent-strong" : "border-line-2 text-ink-2 hover:bg-canvas"}`}
            >
              {p.label}
            </button>
          ))}
          {presetKey === "custom" && (
            <span className="rounded-md border border-accent bg-accent-soft px-2.5 py-1 text-[13px] font-medium text-accent-strong">Custom</span>
          )}
        </div>
        <button className="btn-ghost ml-auto text-[13px]" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "Hide sliders" : "Adjust weights"}
        </button>
      </div>
      <p className="mt-1 text-xs text-ink-3">
        {isOfficial
          ? "Ranking by the official Total_Risk_Index. Pick a preset or adjust weights to see a custom index next to it; the official index is never changed."
          : current
            ? current.why
            : "Your own weights. The custom index is shown next to the official one, always labelled."}
      </p>
      {open && (
        <div className="mt-3 grid grid-cols-3 gap-x-6 gap-y-1 border-t border-line pt-3 xl:grid-cols-6">
          {meta.categories.map((c) => {
            const w = weights[c.column] ?? 0;
            const changed = Math.abs((w / total) * 100 - c.weight_pct) >= 0.5;
            return (
              <label key={c.column} className="block text-xs">
                <span className="flex justify-between gap-1">
                  <span className={`truncate ${changed ? "font-medium text-ink" : "text-ink-2"}`} title={c.original}>{c.label}</span>
                  <span className={`num ${changed ? "text-accent" : "text-ink-3"}`} title={`Official ${c.weight_pct}%`}>
                    {((w / total) * 100).toFixed(1)}%
                  </span>
                </span>
                <input
                  type="range"
                  min={0}
                  max={30}
                  step={1}
                  value={w}
                  aria-label={`Weight for ${c.label}`}
                  className="w-full accent-[var(--color-accent)]"
                  onChange={(e) => setWeights({ ...weights, [c.column]: Number(e.target.value) }, "custom")}
                />
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
