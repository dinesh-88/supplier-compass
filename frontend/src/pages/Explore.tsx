import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { SuppliersData } from "../lib/api";
import { activeFilterCount, applyFilters, bounds, defaultFilters, median, type Bounds } from "../lib/filter";
import { ACCENT, fmtEur, levelOf } from "../lib/levels";
import { MAX_COMPARE, useStore, type Filters, type Range } from "../lib/store";
import EChart, { AXIS } from "../components/EChart";
import WeightsBar, { weightsLabel } from "../components/WeightsBar";
import { Badge, LevelChip, MiniBars, RangeSlider, RankChange, Tile } from "../components/ui";

type SortKey = "official" | "custom" | "change" | "spend" | "exposure";

export default function Explore() {
  const { data, filters, setFilters } = useStore();
  const b = useMemo(() => (data ? bounds(data) : null), [data]);
  const def = useMemo(() => (data && b ? defaultFilters(data, b) : null), [data, b]);

  useEffect(() => {
    if (def && !filters) setFilters(def);
  }, [def, filters, setFilters]);

  if (!data || !b || !def || !filters) return null;
  return <ExploreInner data={data} b={b} def={def} filters={filters} setFilters={setFilters} />;
}

function ExploreInner({ data, b, def, filters, setFilters }: { data: SuppliersData; b: Bounds; def: Filters; filters: Filters; setFilters: (f: Filters) => void }) {
  const { custom, isOfficial, compare, toggleCompare, openDrawer, presetKey, meta } = useStore();
  const nav = useNavigate();
  const deferred = useDeferredValue(filters);
  const result = useMemo(() => applyFilters(data, deferred, def), [data, deferred, def]);
  const [sort, setSort] = useState<SortKey>("official");
  const [desc, setDesc] = useState(false);
  const presetName = meta && meta.loaded ? weightsLabel(presetKey, meta.presets) : "";

  useEffect(() => {
    if (isOfficial && (sort === "custom" || sort === "change")) setSort("official");
  }, [isOfficial, sort]);

  const sorted = useMemo(() => {
    const idx = [...result.indices];
    const spend = data.metrics.purchase_order_volume_eur;
    const key: (i: number) => number =
      sort === "custom" && custom
        ? (i) => custom.custom_index[i]
        : sort === "change" && custom
          ? (i) => -custom.rank_change[i]
          : sort === "spend" && spend
            ? (i) => spend[i] ?? 0
            : sort === "exposure" && data.exposure_eur
              ? (i) => data.exposure_eur![i]
              : (i) => data.index[i];
    idx.sort((x, y) => (key(x) - key(y)) * (desc ? -1 : 1) || data.ids[x].localeCompare(data.ids[y]));
    return idx;
  }, [result, sort, desc, custom, data]);

  const med = useMemo(() => median(result.indices.map((i) => data.index[i])), [result, data]);
  const exposureCount = useMemo(() => result.indices.reduce((n, i) => n + data.exposure_list[i], 0), [result, data]);
  const nActive = activeFilterCount(filters, def);

  const addTop = (n: number) => {
    let added = 0;
    for (const i of sorted.slice(0, n)) {
      if (!compare.includes(data.ids[i]) && compare.length + added < MAX_COMPARE) {
        toggleCompare(data.ids[i]);
        added++;
      }
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <FilterPanel data={data} b={b} def={def} filters={filters} setFilters={setFilters} counts={result.facetCounts} matching={result.indices.length} nActive={nActive} />
      <div className="flex min-w-0 flex-1 flex-col gap-3 overflow-hidden p-4">
        <div className="grid shrink-0 grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,2.4fr)] gap-3">
          <div className="col-span-3 flex flex-col gap-3">
            <div className="grid grid-cols-3 gap-3">
              <Tile label="Suppliers matching" value={<span data-testid="match-count">{result.indices.length.toLocaleString()}</span>} sub={`of ${data.ids.length.toLocaleString()}`} />
              <Tile
                label="Median index"
                value={med === null ? "–" : med.toFixed(med % 1 ? 1 : 0)}
                sub={med === null ? "" : <LevelChip size="xs" level={levelOf(med, data.bands)} bands={data.bands} />}
              />
              <Tile
                label="Exposure list"
                value={data.features.exposure ? exposureCount : "–"}
                sub={data.features.exposure ? "top 10% spend and Critical" : "needs a spend column"}
              />
            </div>
            <WeightsBar />
          </div>
          <div className="card p-2">
            <Scatter data={data} matches={result.matches} compare={compare} onPick={(i) => openDrawer(data.ids[i])} />
          </div>
        </div>

        <div className="card flex min-h-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center gap-3 border-b border-line px-3 py-2 text-sm">
            <span className="font-medium">Ranked suppliers</span>
            <label className="flex items-center gap-1.5 text-ink-2">
              Sort by
              <select className="input py-1" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort by">
                <option value="official">Official index</option>
                {!isOfficial && <option value="custom">Custom index ({presetName})</option>}
                {!isOfficial && <option value="change">Biggest rank gain</option>}
                {data.features.spend && <option value="spend">Spend</option>}
                {data.features.exposure && <option value="exposure">Exposure (index × spend)</option>}
              </select>
            </label>
            <button className="btn-ghost" onClick={() => setDesc((d) => !d)} aria-label="Toggle sort direction">
              {desc ? "High → low" : "Low → high"}
            </button>
            <span className="ml-auto text-xs text-ink-3">
              Compare set <span className="num font-medium text-ink">{compare.length}</span>/{MAX_COMPARE}
            </span>
            <button className="btn" disabled={!sorted.length || compare.length >= MAX_COMPARE} onClick={() => addTop(5)}>
              Add top 5
            </button>
            <button className="btn-primary" disabled={!compare.length} onClick={() => nav("/compare")} data-testid="open-compare">
              Open compare →
            </button>
          </div>
          <SupplierList data={data} rows={sorted} />
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ filter panel

function FilterPanel({
  data,
  b,
  def,
  filters,
  setFilters,
  counts,
  matching,
  nActive,
}: {
  data: SuppliersData;
  b: Bounds;
  def: Filters;
  filters: Filters;
  setFilters: (f: Filters) => void;
  counts: ReturnType<typeof applyFilters>["facetCounts"];
  matching: number;
  nActive: number;
}) {
  const [showScores, setShowScores] = useState(true);
  const set = (patch: Partial<Filters>) => setFilters({ ...filters, ...patch });
  const toggle = (key: "sourcing" | "complexity", v: string) =>
    set({ [key]: filters[key].includes(v) ? filters[key].filter((x) => x !== v) : [...filters[key], v] } as Partial<Filters>);
  const f = data.features;

  return (
    <aside className="flex w-[290px] shrink-0 flex-col border-r border-line bg-surface" aria-label="Filters">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <div className="text-sm font-semibold">Filters</div>
          <div className="text-xs text-ink-3">
            <span className="num font-medium text-ink">{matching.toLocaleString()}</span> match · {nActive} active
          </div>
        </div>
        <button className="btn-ghost text-xs" disabled={!nActive} onClick={() => setFilters(def)}>
          Reset
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        <input className="input w-full" placeholder="Search ID or name" value={filters.text} onChange={(e) => set({ text: e.target.value })} aria-label="Search suppliers" />

        <section className="space-y-2">
          <Toggle
            label="Exposure list"
            hint="Top 10% spend and Critical index"
            checked={filters.exposureOnly}
            disabled={!f.exposure}
            count={counts.exposure}
            onChange={(v) => set({ exposureOnly: v })}
            testId="toggle-exposure"
          />
          <Toggle
            label="Delivery mismatch"
            hint="Delivery record doesn't match risk scores"
            checked={filters.mismatchOnly}
            disabled={!f.mismatch}
            count={counts.mismatch}
            onChange={(v) => set({ mismatchOnly: v })}
            testId="toggle-mismatch"
          />
        </section>

        <section>
          <RangeSlider label="Total Risk Index" min={0} max={100} value={filters.index} onChange={(v) => set({ index: v })} />
          {f.spend && b.spend && filters.spend && (
            <RangeSlider label="Spend (log scale)" min={b.spend[0]} max={b.spend[1]} step={0.05} value={filters.spend} onChange={(v) => set({ spend: v })} format={(v) => fmtEur(Math.pow(10, v))} />
          )}
          {f.delivery && b.delivery && filters.delivery && (
            <RangeSlider label="Delivery rating" min={b.delivery[0]} max={b.delivery[1]} value={filters.delivery} onChange={(v) => set({ delivery: v })} format={(v) => `${v}%`} />
          )}
          {f.confirmation && b.confirmation && filters.confirmation && (
            <RangeSlider label="Confirmation rate" min={b.confirmation[0]} max={b.confirmation[1]} value={filters.confirmation} onChange={(v) => set({ confirmation: v })} format={(v) => `${v}%`} />
          )}
          {f.change_rate && b.changeRate && filters.changeRate && (
            <RangeSlider label="Order change rate" min={b.changeRate[0]} max={b.changeRate[1]} value={filters.changeRate} onChange={(v) => set({ changeRate: v })} format={(v) => `${v}%`} />
          )}
        </section>

        {f.sourcing && b.sourcing.length > 0 && (
          <CheckGroup title="Sourcing Risk Level" options={b.sourcing} selected={filters.sourcing} counts={counts.sourcing} onToggle={(v) => toggle("sourcing", v)} />
        )}
        {f.complexity && b.complexity.length > 0 && (
          <CheckGroup title="Supply Chain Complexity" options={b.complexity} selected={filters.complexity} counts={counts.complexity} onToggle={(v) => toggle("complexity", v)} />
        )}

        <section>
          <button className="label mb-1 flex w-full items-center justify-between" onClick={() => setShowScores((s) => !s)} aria-expanded={showScores}>
            Category scores <span>{showScores ? "−" : "+"}</span>
          </button>
          {showScores &&
            data.categories.map((c) => (
              <RangeSlider
                key={c.column}
                label={c.label}
                min={0}
                max={100}
                value={filters.scores[c.column] as Range}
                onChange={(v) => set({ scores: { ...filters.scores, [c.column]: v } })}
              />
            ))}
        </section>
        {!f.spend && <p className="text-xs text-ink-3">Spend, exposure and some filters are off: this dataset has no matching columns.</p>}
      </div>
    </aside>
  );
}

function Toggle({ label, hint, checked, disabled, count, onChange, testId }: { label: string; hint: string; checked: boolean; disabled?: boolean; count: number; onChange: (v: boolean) => void; testId?: string }) {
  return (
    <label className={`flex items-start gap-2.5 rounded-md border px-2.5 py-2 ${checked ? "border-accent bg-accent-soft" : "border-line"} ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input type="checkbox" className="mt-0.5 accent-[var(--color-accent)]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} data-testid={testId} />
      <span className="flex-1">
        <span className="flex justify-between text-[13px] font-medium">
          {label} <span className="num text-ink-3">{disabled ? "n/a" : count}</span>
        </span>
        <span className="block text-xs text-ink-3">{hint}</span>
      </span>
    </label>
  );
}

function CheckGroup({ title, options, selected, counts, onToggle }: { title: string; options: string[]; selected: string[]; counts: Record<string, number>; onToggle: (v: string) => void }) {
  return (
    <section>
      <div className="label mb-1">{title}</div>
      {options.map((o) => (
        <label key={o} className="flex cursor-pointer items-center gap-2 py-0.5 text-[13px]">
          <input type="checkbox" className="accent-[var(--color-accent)]" checked={selected.includes(o)} onChange={() => onToggle(o)} />
          <span className="flex-1">{o}</span>
          <span className="num text-xs text-ink-3">{(counts[o] ?? 0).toLocaleString()}</span>
        </label>
      ))}
    </section>
  );
}

// ------------------------------------------------------------------ scatter

function Scatter({ data, matches, compare, onPick }: { data: SuppliersData; matches: Uint8Array; compare: string[]; onPick: (i: number) => void }) {
  const spend = data.metrics.purchase_order_volume_eur;
  const option = useMemo(() => {
    if (!spend) return null;
    const inSet = new Set(compare);
    const other: number[][] = [];
    const hit: number[][] = [];
    const picked: number[][] = [];
    for (let i = 0; i < data.ids.length; i++) {
      const v = spend[i];
      if (v === null || v <= 0) continue;
      const p = [v, data.index[i], i];
      if (inSet.has(data.ids[i])) picked.push(p);
      if (matches[i]) hit.push(p);
      else other.push(p);
    }
    const allMatch = other.length === 0;
    return {
      grid: { left: 44, right: 14, top: 30, bottom: 34 },
      legend: { top: 2, right: 6, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: "#4b5259" } },
      tooltip: {
        trigger: "item",
        formatter: (p: { value: number[] }) => {
          const i = p.value[2];
          return `<b>${esc(data.ids[i])}</b> ${esc(data.names[i])}<br/>Index ${data.index[i]} · Spend ${fmtEur(spend[i])}`;
        },
      },
      xAxis: { type: "log", name: "Spend (EUR, log)", nameLocation: "middle", nameGap: 22, ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => fmtEur(v) } },
      yAxis: { type: "value", name: "Total Risk Index", min: 0, max: 100, nameGap: 8, ...AXIS },
      series: [
        { name: "Not matching", type: "scatter", data: other, symbolSize: 3, itemStyle: { color: "#cfd4d9" }, large: true, largeThreshold: 3000, silent: false },
        { name: allMatch ? "All suppliers" : "Matching filters", type: "scatter", data: hit, symbolSize: hit.length > 2000 ? 3 : 5, itemStyle: { color: ACCENT, opacity: hit.length > 2000 ? 0.55 : 0.85 }, large: hit.length > 3000 },
        { name: "In compare set", type: "scatter", data: picked, symbolSize: 10, itemStyle: { color: "transparent", borderColor: "#16191d", borderWidth: 2 }, z: 5 },
      ],
    };
  }, [data, matches, compare, spend]);
  if (!option) return <div className="flex h-[230px] items-center justify-center text-sm text-ink-3">No spend column: scatter unavailable.</div>;
  return <EChart option={option} height={230} onClick={(p) => onPick((p.value as number[])[2])} ariaLabel="Scatter of Total Risk Index against spend" />;
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

// ------------------------------------------------------------------ list

function SupplierList({ data, rows }: { data: SuppliersData; rows: number[] }) {
  const { custom, compare, toggleCompare, openDrawer } = useStore();
  const parent = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => 46, overscan: 12 });
  const spend = data.metrics.purchase_order_volume_eur;
  const labels = data.categories.map((c) => c.label);
  const cols = "grid grid-cols-[34px_54px_minmax(170px,1.4fr)_120px_150px_90px_96px_minmax(90px,1fr)] items-center gap-2";

  return (
    <>
      <div className={`${cols} shrink-0 border-b border-line bg-canvas px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-ink-3`}>
        <span title="Add to compare">Cmp</span>
        <span title={custom ? "Rank under your weights (1 = lowest risk)" : "Official rank (1 = lowest risk)"}>{custom ? "Rank*" : "Rank"}</span>
        <span>Supplier</span>
        <span>Official index</span>
        <span>Custom index</span>
        <span>Spend</span>
        <span>Scores</span>
        <span>Flags</span>
      </div>
      <div ref={parent} className="min-h-0 flex-1 overflow-auto" data-testid="supplier-list">
        {rows.length === 0 && <p className="p-6 text-center text-sm text-ink-3">No supplier matches these filters.</p>}
        <div style={{ height: virt.getTotalSize(), position: "relative" }}>
          {virt.getVirtualItems().map((v) => {
            const i = rows[v.index];
            const id = data.ids[i];
            const lvl = data.bands[data.level[i]]?.level ?? "";
            const inSet = compare.includes(id);
            return (
              <div
                key={id}
                className={`${cols} absolute left-0 right-0 cursor-pointer border-b border-line px-3 text-sm hover:bg-canvas ${inSet ? "bg-accent-soft/50" : ""}`}
                style={{ top: 0, height: v.size, transform: `translateY(${v.start}px)` }}
                onClick={() => openDrawer(id)}
                data-testid="supplier-row"
              >
                <span onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-[var(--color-accent)]"
                    checked={inSet}
                    onChange={() => toggleCompare(id)}
                    aria-label={`Add ${id} to compare`}
                    data-testid="compare-checkbox"
                  />
                </span>
                <span className="num text-xs text-ink-3">#{(custom ? custom.custom_rank[i] : data.official_rank[i]).toLocaleString()}</span>
                <span className="min-w-0">
                  <span className="num block font-medium">{id}</span>
                  <span className="block truncate text-xs text-ink-3">{data.names[i]}</span>
                </span>
                <span>
                  <LevelChip level={lvl} value={data.index[i]} bands={data.bands} />
                </span>
                <span className="flex flex-col">
                  {custom ? (
                    <>
                      <span className="flex items-center gap-1.5">
                        <LevelChip size="xs" level={levelOf(custom.custom_index[i], data.bands)} value={custom.custom_index[i].toFixed(1)} bands={data.bands} />
                      </span>
                      <RankChange change={custom.rank_change[i]} />
                    </>
                  ) : (
                    <span className="text-xs text-ink-3">= official</span>
                  )}
                </span>
                <span className="num text-[13px]">{spend ? fmtEur(spend[i]) : "–"}</span>
                <MiniBars scores={data.scores[i]} bands={data.bands} labels={labels} />
                <span className="flex flex-wrap gap-1">
                  {!!data.exposure_list[i] && <Badge tone="warn" title="Top 10% spend and Critical index">Exposure</Badge>}
                  {!!data.mismatch[i] && <Badge title="Delivery record doesn't match risk scores">Delivery ≠ scores</Badge>}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
