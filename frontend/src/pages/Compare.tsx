import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type CompareData, type WhyData } from "../lib/api";
import { fmtEur, fmtPct, fmtSigned, levelColor, levelText, COOL, WARM } from "../lib/levels";
import { useStore } from "../lib/store";
import EChart, { AXIS } from "../components/EChart";
import { weightsLabel } from "../components/WeightsBar";
import SupplierPicker from "../components/SupplierPicker";
import { Badge, LevelChip, LevelLegend, RankChange, Spinner } from "../components/ui";

// Categorical slots 1–5 of the validated reference palette, in fixed order.
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
const MAX_RADAR = 5;

type SortCol = { key: string; desc: boolean };

export default function Compare() {
  const { compare, removeCompare, clearCompare, weights, isOfficial, openChat, openDrawer, presetKey, meta } = useStore();
  const nav = useNavigate();
  const [data, setData] = useState<CompareData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sort, setSort] = useState<SortCol>({ key: "total_risk_index", desc: false });
  const [radar, setRadar] = useState<string[]>([]);
  // Comparing needs suppliers: prompt for them as soon as the tab opens with none selected.
  const [picking, setPicking] = useState(() => !compare.length);
  const presetName = meta && meta.loaded ? weightsLabel(presetKey, meta.presets) : "";

  useEffect(() => {
    if (!compare.length) {
      setData(null);
      return;
    }
    const t = window.setTimeout(() => {
      api
        .post<CompareData>("/api/compare", { ids: compare, weights: isOfficial ? null : weights })
        .then((d) => {
          setData(d);
          setErr(null);
        })
        .catch((e) => setErr(e.message));
    }, 150);
    return () => window.clearTimeout(t);
  }, [compare, weights, isOfficial]);

  useEffect(() => {
    setRadar((r) => {
      const kept = r.filter((id) => compare.includes(id));
      return kept.length ? kept : compare.slice(0, 3);
    });
  }, [compare]);

  const rows = useMemo(() => {
    if (!data) return [];
    const val = (s: CompareData["suppliers"][number]) =>
      sort.key === "total_risk_index"
        ? s.total_risk_index
        : sort.key === "custom_index"
          ? (s.custom_index ?? s.total_risk_index)
          : (s.scores[sort.key]?.score ?? 0);
    return [...data.suppliers].sort((a, b) => (val(a) - val(b)) * (sort.desc ? -1 : 1) || a.supplierID.localeCompare(b.supplierID));
  }, [data, sort]);

  if (!compare.length)
    return (
      <div className="mx-auto max-w-xl p-10 text-center">
        <h1 className="text-xl font-semibold">Nothing to compare yet</h1>
        <p className="mt-2 text-sm text-ink-2">Select up to 20 suppliers, tick “add to compare” in Explore, or ask the assistant to “compare these”.</p>
        <button className="btn-primary mt-4" onClick={() => setPicking(true)}>Select suppliers</button>
        {picking && <SupplierPicker title="Select suppliers to compare" onClose={() => setPicking(false)} />}
      </div>
    );
  if (err) return <p className="p-6 text-sm text-lv-high">{err}</p>;
  if (!data) return <div className="p-6"><Spinner label="Loading comparison…" /></div>;

  const toggleSort = (key: string) => setSort((s) => ({ key, desc: s.key === key ? !s.desc : false }));
  const diff = new Set(data.most_different);

  return (
    <div className="space-y-4 p-4">
      {picking && <SupplierPicker title="Add suppliers to compare" onClose={() => setPicking(false)} />}
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Compare <span className="num text-ink-3">{compare.length}</span></h1>
        <span className="text-xs text-ink-3">
          Index formula {data.formula} · {isOfficial ? "official weights" : <>custom weights: <strong>{presetName}</strong></>}
        </span>
        <div className="ml-auto flex gap-2">
          <button className="btn" onClick={() => setPicking(true)} data-testid="add-suppliers">Add suppliers</button>
          <button className="btn" onClick={clearCompare}>Clear</button>
          <button className="btn" onClick={() => openChat(compare)} data-testid="ask-about-these">Ask about these</button>
          <button className="btn" onClick={() => nav(`/analyses?plugin=fault_tree&ids=${compare.join(",")}`)} data-testid="open-fault-tree">
            Fault tree analysis
          </button>
          <button className="btn-primary" onClick={() => nav("/memo")} data-testid="generate-memo">Generate shortlist memo</button>
        </div>
      </div>

      <section className="card p-4">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <h2 className="font-semibold">Scores by category</h2>
          <span className="text-xs text-ink-3">Click a column to sort. ◆ marks the 3 categories where these suppliers differ most. Tick up to {MAX_RADAR} rows for the radar.</span>
          <div className="ml-auto"><LevelLegend bands={data.bands} /></div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-[13px]" data-testid="heatmap">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-surface px-2 py-1 text-left text-xs font-medium text-ink-3">Radar</th>
                <th className="sticky left-[52px] z-10 bg-surface px-2 py-1 text-left text-xs font-medium text-ink-3">Supplier</th>
                <SortHead label="Index" active={sort.key === "total_risk_index"} desc={sort.desc} onClick={() => toggleSort("total_risk_index")} />
                {!isOfficial && <SortHead label="Custom" active={sort.key === "custom_index"} desc={sort.desc} onClick={() => toggleSort("custom_index")} />}
                {data.categories.map((c) => (
                  <SortHead
                    key={c.column}
                    label={c.label}
                    sub={`${c.weight_pct}%`}
                    vertical
                    highlight={diff.has(c.column)}
                    active={sort.key === c.column}
                    desc={sort.desc}
                    onClick={() => toggleSort(c.column)}
                    title={`${c.original} · weight ${c.weight_pct}% · spread sd ${c.spread_sd}`}
                  />
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const ri = radar.indexOf(s.supplierID);
                return (
                  <tr key={s.supplierID} className="group">
                    <td className="sticky left-0 z-10 bg-surface px-2 py-0.5">
                      <label className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          className="accent-[var(--color-accent)]"
                          checked={ri >= 0}
                          disabled={ri < 0 && radar.length >= MAX_RADAR}
                          onChange={() => setRadar((r) => (ri >= 0 ? r.filter((x) => x !== s.supplierID) : [...r, s.supplierID]))}
                          aria-label={`Show ${s.supplierID} on radar`}
                        />
                        {ri >= 0 && <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SERIES[ri] }} />}
                      </label>
                    </td>
                    <td className="sticky left-[52px] z-10 bg-surface px-2 py-0.5">
                      <button className="num text-left font-medium hover:text-accent" onClick={() => openDrawer(s.supplierID)}>{s.supplierID}</button>
                      <div className="max-w-[150px] truncate text-[11px] text-ink-3">{s.name}</div>
                    </td>
                    <td className="px-1 py-0.5"><LevelChip level={s.level} value={s.total_risk_index} bands={data.bands} /></td>
                    {!isOfficial && (
                      <td className="px-1 py-0.5 whitespace-nowrap">
                        <span className="num font-medium">{s.custom_index?.toFixed(1)}</span>{" "}
                        <RankChange change={s.rank_change ?? 0} />
                      </td>
                    )}
                    {data.categories.map((c) => {
                      const cell = s.scores[c.column];
                      return (
                        <td key={c.column} className="p-[1px]">
                          <div
                            className={`num flex h-8 min-w-[34px] items-center justify-center rounded-[3px] text-xs font-medium ${diff.has(c.column) ? "ring-2 ring-ink/70 ring-inset" : ""}`}
                            style={{ background: levelColor(cell.level, data.bands), color: levelText(cell.level) }}
                            title={`${s.supplierID} · ${c.label}: ${cell.score} (${cell.level})`}
                          >
                            {cell.score}
                          </div>
                        </td>
                      );
                    })}
                    <td className="px-1">
                      <button className="btn-ghost text-xs opacity-60 group-hover:opacity-100" onClick={() => removeCompare(s.supplierID)} aria-label={`Remove ${s.supplierID}`}>✕</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid grid-cols-[1fr_1.15fr] gap-4">
        <section className="card p-4">
          <h2 className="font-semibold">Profile radar</h2>
          <p className="text-xs text-ink-3">Higher = more risk. {radar.length} of max {MAX_RADAR} shown.</p>
          <Radar data={data} ids={radar} />
        </section>
        <WhyAOverB ids={rows.map((r) => r.supplierID)} weights={isOfficial ? null : weights} presetName={presetName} />
      </div>

      <section className="card p-4">
        <h2 className="mb-2 font-semibold">Operational metrics</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-3">
              <th className="py-1 font-medium">Supplier</th>
              {data.metrics.map((m) => <th key={m.column} className="py-1 text-right font-medium">{m.original}</th>)}
              <th className="py-1 pl-4 font-medium">Sourcing risk</th>
              <th className="py-1 font-medium">Complexity</th>
              <th className="py-1 font-medium">Flags</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.supplierID} className="border-t border-line">
                <td className="num py-1 font-medium">{s.supplierID}</td>
                {data.metrics.map((m) => {
                  const v = s[m.column] as number | null;
                  return (
                    <td key={m.column} className="num py-1 text-right">
                      {m.column === "purchase_order_volume_eur" ? fmtEur(v) : fmtPct(v, 2)}
                    </td>
                  );
                })}
                <td className="py-1 pl-4">{(s.sourcing_risk_level as string) ?? "–"}</td>
                <td className="py-1">{(s.supply_chain_complexity as string) ?? "–"}</td>
                <td className="py-1">
                  <span className="flex gap-1">
                    {!!s.exposure_list && <Badge tone="warn">Exposure</Badge>}
                    {!!s.delivery_mismatch && <Badge>Delivery ≠ scores</Badge>}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function SortHead({ label, sub, active, desc, onClick, vertical, highlight, title }: { label: string; sub?: string; active: boolean; desc: boolean; onClick: () => void; vertical?: boolean; highlight?: boolean; title?: string }) {
  return (
    <th className="px-0.5 pb-1 align-bottom" title={title} aria-sort={active ? (desc ? "descending" : "ascending") : "none"}>
      <button onClick={onClick} className={`flex flex-col items-center gap-0.5 rounded px-0.5 text-[11px] font-medium leading-tight hover:text-accent ${active ? "text-accent" : highlight ? "text-ink" : "text-ink-3"}`}>
        <span className={vertical ? "h-[136px] [writing-mode:vertical-rl] rotate-180 text-left whitespace-nowrap" : ""}>
          {highlight && "◆ "}
          {label}
        </span>
        {sub && <span className="num text-[10px] text-ink-3">{sub}</span>}
        <span className="h-3 text-[10px]">{active ? (desc ? "▼" : "▲") : ""}</span>
      </button>
    </th>
  );
}

function Radar({ data, ids }: { data: CompareData; ids: string[] }) {
  const option = useMemo(() => {
    const byId = new Map(data.suppliers.map((s) => [s.supplierID, s]));
    return {
      legend: { bottom: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: "#4b5259" } },
      tooltip: { trigger: "item" },
      radar: {
        radius: "66%",
        center: ["50%", "48%"],
        indicator: data.categories.map((c) => ({ name: c.label, max: 100 })),
        axisName: { color: "#4b5259", fontSize: 10.5 },
        splitLine: { lineStyle: { color: "#e3e5e8" } },
        splitArea: { show: false },
        axisLine: { lineStyle: { color: "#e3e5e8" } },
      },
      series: [
        {
          type: "radar",
          symbolSize: 4,
          data: ids
            .filter((id) => byId.has(id))
            .map((id, i) => ({
              name: id,
              value: data.categories.map((c) => byId.get(id)!.scores[c.column].score),
              lineStyle: { color: SERIES[i], width: 2 },
              itemStyle: { color: SERIES[i] },
              areaStyle: { color: SERIES[i], opacity: 0.06 },
            })),
        },
      ],
    };
  }, [data, ids]);
  return <EChart option={option} height={420} ariaLabel="Radar of category scores" />;
}

function WhyAOverB({ ids, weights, presetName }: { ids: string[]; weights: Record<string, number> | null; presetName: string }) {
  const [a, setA] = useState(ids[0] ?? "");
  const [b, setB] = useState(ids[1] ?? ids[0] ?? "");
  const [res, setRes] = useState<WhyData | null>(null);

  useEffect(() => {
    if (!ids.includes(a)) setA(ids[0] ?? "");
    if (!ids.includes(b)) setB(ids.find((x) => x !== ids[0]) ?? "");
  }, [ids, a, b]);

  useEffect(() => {
    if (!a || !b || a === b) {
      setRes(null);
      return;
    }
    api.post<WhyData>("/api/why", { a, b, weights }).then(setRes).catch(() => setRes(null));
  }, [a, b, weights]);

  const option = useMemo(() => {
    if (!res || !res.differences.length) return null;
    const d = res.differences;
    return {
      grid: { left: 150, right: 56, top: 6, bottom: 22 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "value", ...AXIS, name: "index points", nameLocation: "middle", nameGap: 16 },
      yAxis: { type: "category", inverse: true, data: d.map((x) => x.label), ...AXIS, axisLabel: { ...AXIS.axisLabel, color: "#4b5259" } },
      series: [
        {
          type: "bar",
          name: "Effect on official index",
          data: d.map((x) => ({ value: x.effect_official, itemStyle: { color: x.effect_official > 0 ? WARM : COOL, borderRadius: 2 } })),
          label: { show: true, position: "right", color: "#4b5259", fontSize: 11, formatter: (p: { value: number }) => fmtSigned(p.value, 2) },
          barCategoryGap: "30%",
        },
      ],
    };
  }, [res]);

  return (
    <section className="card p-4" data-testid="why-a-over-b">
      <h2 className="font-semibold">Why A over B</h2>
      <div className="mt-2 flex items-center gap-2 text-sm">
        <select className="input" value={a} onChange={(e) => setA(e.target.value)} aria-label="Supplier A">
          {ids.map((id) => <option key={id}>{id}</option>)}
        </select>
        <span className="text-ink-3">vs</span>
        <select className="input" value={b} onChange={(e) => setB(e.target.value)} aria-label="Supplier B">
          {ids.map((id) => <option key={id}>{id}</option>)}
        </select>
      </div>
      {a === b && <p className="mt-3 text-sm text-ink-3">Pick two different suppliers.</p>}
      {res && (
        <>
          <p className="mt-3 text-sm">
            <strong className="num">{res.a}</strong> has index <span className="num">{res.index_a}</span>, <strong className="num">{res.b}</strong> has{" "}
            <span className="num">{res.index_b}</span>: a gap of <strong className="num">{fmtSigned(res.index_gap, 0)}</strong> points.{" "}
            The {res.differences.length} categories differing by ≥{res.threshold} points account for <span className="num">{fmtSigned(res.explained_by_listed, 2)}</span> of it
            {res.approximate && " (approximate formula)"}.
            {res.custom_gap !== undefined && (
              <> Under <em>{presetName}</em> the gap is <span className="num">{fmtSigned(res.custom_gap, 2)}</span>.</>
            )}
          </p>
          <p className="text-xs text-ink-3">Bars: weight × (B − A). Positive = B is riskier there, which favours A.</p>
          {option ? <EChart option={option} height={Math.max(120, res.differences.length * 30 + 40)} ariaLabel="Weighted effect per category" /> : <p className="mt-2 text-sm text-ink-3">No category differs by 10 points or more.</p>}
          {res.differences.length > 0 && (
            <table className="mt-2 w-full text-[13px]">
              <thead>
                <tr className="text-left text-xs text-ink-3">
                  <th className="py-1 font-medium">Category</th>
                  <th className="py-1 text-right font-medium">A</th>
                  <th className="py-1 text-right font-medium">B</th>
                  <th className="py-1 text-right font-medium">B − A</th>
                  <th className="py-1 text-right font-medium">Weight</th>
                  <th className="py-1 text-right font-medium">Effect</th>
                  {res.differences[0].effect_custom !== undefined && <th className="py-1 text-right font-medium">Effect (custom)</th>}
                  <th className="py-1 pl-3 font-medium">Better</th>
                </tr>
              </thead>
              <tbody>
                {res.differences.map((d) => (
                  <tr key={d.column} className="border-t border-line">
                    <td className="py-1">{d.label}</td>
                    <td className="num py-1 text-right">{d.score_a}</td>
                    <td className="num py-1 text-right">{d.score_b}</td>
                    <td className="num py-1 text-right">{fmtSigned(d.difference, 0)}</td>
                    <td className="num py-1 text-right text-ink-2">{d.weight_pct}%</td>
                    <td className="num py-1 text-right">{fmtSigned(d.effect_official, 2)}</td>
                    {d.effect_custom !== undefined && <td className="num py-1 text-right">{fmtSigned(d.effect_custom, 2)}</td>}
                    <td className="num py-1 pl-3">{d.better}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
