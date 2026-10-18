import { useEffect, useMemo, useState } from "react";
import { api, type SupplierDetail } from "../lib/api";
import { COOL, WARM, fmtEur, fmtPct, fmtSigned, levelColor } from "../lib/levels";
import { useStore } from "../lib/store";
import EChart, { AXIS } from "./EChart";
import { Badge, LevelChip, Spinner } from "./ui";

export default function SupplierDrawer() {
  const { drawerId, openDrawer, compare, toggleCompare, openChat, meta } = useStore();
  const [d, setD] = useState<SupplierDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"waterfall" | "average">("waterfall");

  useEffect(() => {
    if (!drawerId) return;
    setD(null);
    setErr(null);
    api.get<SupplierDetail>(`/api/suppliers/${encodeURIComponent(drawerId)}`).then(setD).catch((e) => setErr(e.message));
  }, [drawerId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && openDrawer(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openDrawer]);

  const bands = meta && meta.loaded ? meta.bands : [];
  const inSet = !!drawerId && compare.includes(drawerId);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={() => openDrawer(null)}>
      <aside
        className="flex h-full w-[720px] max-w-[95vw] flex-col bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`Supplier ${drawerId}`}
        data-testid="supplier-drawer"
      >
        <div className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="num text-lg font-semibold">{drawerId}</div>
            <div className="truncate text-sm text-ink-2">{d?.name}</div>
          </div>
          <button className={inSet ? "btn" : "btn-primary"} onClick={() => drawerId && toggleCompare(drawerId)}>
            {inSet ? "Remove from compare" : "Add to compare"}
          </button>
          <button className="btn" onClick={() => drawerId && openChat([drawerId], `Why is the Total Risk Index of ${drawerId} so high?`)}>
            Ask
          </button>
          <button className="btn-ghost text-lg" onClick={() => openDrawer(null)} aria-label="Close">
            ×
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {err && <p className="text-sm text-lv-high">{err}</p>}
          {!d && !err && <Spinner label="Loading supplier…" />}
          {d && (
            <div className="space-y-5">
              <div className="grid grid-cols-4 gap-3">
                <Box label="Total Risk Index">
                  <LevelChip level={d.level} value={d.total_risk_index} bands={bands} />
                </Box>
                <Box label="Percentile">
                  <span className="num text-lg font-semibold">{Math.floor(d.percentile)}th</span>
                  <span className="text-xs text-ink-3"> riskier than {Math.floor(d.percentile)}%</span>
                </Box>
                <Box label="Rank (1 = lowest risk)">
                  <span className="num text-lg font-semibold">#{d.official_rank.toLocaleString()}</span>
                </Box>
                <Box label="vs average supplier">
                  <span className="num text-lg font-semibold">{fmtSigned(d.points_above_average_total)}</span>
                  <span className="text-xs text-ink-3"> pts</span>
                </Box>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge tone={d.approximate ? "warn" : "accent"}>Formula {d.formula_label}</Badge>
                <span className="text-ink-3">{d.note}</span>
                {d.exposure_list && <Badge tone="warn">On the exposure list</Badge>}
              </div>

              <section>
                <div className="mb-1 flex items-center gap-2">
                  <h3 className="font-semibold">Why the index is {d.total_risk_index}{d.approximate && " (approximate)"}</h3>
                  <div className="ml-auto flex rounded-md border border-line-2 p-0.5 text-xs">
                    <button className={`rounded px-2 py-0.5 ${tab === "waterfall" ? "bg-accent-soft font-medium text-accent-strong" : "text-ink-2"}`} onClick={() => setTab("waterfall")}>
                      Contributions
                    </button>
                    <button className={`rounded px-2 py-0.5 ${tab === "average" ? "bg-accent-soft font-medium text-accent-strong" : "text-ink-2"}`} onClick={() => setTab("average")}>
                      Points above average
                    </button>
                  </div>
                </div>
                <p className="mb-1 text-xs text-ink-3">
                  {tab === "waterfall"
                    ? "Each category adds weight × score points. They sum to the weighted total, which rounds (half to even) to the index."
                    : "weight × (score − mean score): how far each category pushes this supplier above (+) or below (−) an average supplier."}
                </p>
                {tab === "waterfall" ? <Waterfall d={d} /> : <AboveAverage d={d} />}
              </section>

              <section>
                <h3 className="mb-1 font-semibold">Categories</h3>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-ink-3">
                      <th className="py-1 font-medium">Category</th>
                      <th className="py-1 font-medium">Level</th>
                      <th className="py-1 text-right font-medium">Percentile</th>
                      <th className="py-1 text-right font-medium">Weight</th>
                      <th className="py-1 text-right font-medium">Contribution</th>
                      <th className="py-1 text-right font-medium">vs avg</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...d.contributions].sort((a, b) => b.score - a.score).map((c) => (
                      <tr key={c.column} className="border-t border-line">
                        <td className="py-1" title={c.original}>{c.label}</td>
                        <td className="py-1"><LevelChip size="xs" level={c.level} value={c.score} bands={bands} /></td>
                        <td className="num py-1 text-right">{Math.floor(c.percentile)}</td>
                        <td className="num py-1 text-right text-ink-2">{c.weight_pct}%</td>
                        <td className="num py-1 text-right">{c.contribution.toFixed(2)}</td>
                        <td className={`num py-1 text-right ${c.points_above_average > 0 ? "text-lv-high" : "text-accent"}`}>{fmtSigned(c.points_above_average, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>

              {d.metrics.length > 0 && (
                <section>
                  <h3 className="mb-1 font-semibold">Operational metrics</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {d.metrics.map((m) => (
                      <div key={m.column} className="rounded-md bg-canvas px-3 py-2">
                        <div className="text-xs text-ink-3">{m.original}</div>
                        <div className="num font-semibold">
                          {m.column === "purchase_order_volume_eur" ? fmtEur(m.value) : fmtPct(m.value, 2)}
                          <span className="ml-2 text-xs font-normal text-ink-3">percentile {m.percentile === null ? "–" : Math.floor(m.percentile)}</span>
                        </div>
                      </div>
                    ))}
                    {d.exposure_eur !== undefined && (
                      <div className="rounded-md bg-canvas px-3 py-2">
                        <div className="text-xs text-ink-3">Exposure (index/100 × spend)</div>
                        <div className="num font-semibold">{fmtEur(d.exposure_eur)}</div>
                      </div>
                    )}
                    {d.sourcing_risk_level && (
                      <div className="rounded-md bg-canvas px-3 py-2">
                        <div className="text-xs text-ink-3">Sourcing Risk Level · Complexity</div>
                        <div className="font-semibold">{d.sourcing_risk_level} · {d.supply_chain_complexity ?? "–"}</div>
                      </div>
                    )}
                  </div>
                </section>
              )}

              {d.mismatch && (
                <section className={`rounded-md border p-3 ${d.mismatch.flagged ? "border-amber-300 bg-amber-50" : "border-line"}`}>
                  <h3 className="flex items-center gap-2 font-semibold">
                    {d.mismatch.flagged ? "⚠ " : ""}
                    {d.mismatch.label}: {d.mismatch.flagged ? "flagged" : "no"}
                  </h3>
                  <p className="mt-1 text-sm text-ink-2">{d.mismatch.explanation}</p>
                  <p className="mt-1 text-xs text-ink-3">
                    Model: Supplier Delivery Rating regressed on Operational_Resilience and Quality_Risk across all suppliers; flagged when the residual exceeds 2 sd.
                  </p>
                </section>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Box({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line px-3 py-2">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function Waterfall({ d }: { d: SupplierDetail }) {
  const option = useMemo(() => {
    const items = d.contributions; // sorted by contribution, largest first
    const labels = [...items.map((c) => c.label), "Weighted total"];
    let acc = 0;
    const base: number[] = [];
    const vals: { value: number; itemStyle: { color: string } }[] = [];
    for (const c of items) {
      base.push(acc);
      vals.push({ value: c.contribution, itemStyle: { color: levelColor(c.level) } });
      acc += c.contribution;
    }
    base.push(0);
    vals.push({ value: Math.round(acc * 100) / 100, itemStyle: { color: "#4b5259" } });
    return {
      grid: { left: 150, right: 50, top: 8, bottom: 24 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0].dataIndex;
          if (i === items.length) return `Weighted total ${acc.toFixed(2)} → index ${d.total_risk_index}`;
          const c = items[i];
          return `<b>${c.label}</b><br/>score ${c.score} × weight ${c.weight_pct}% = <b>${c.contribution.toFixed(2)}</b> points<br/>running total ${(base[i] + c.contribution).toFixed(2)}`;
        },
      },
      xAxis: { type: "value", max: Math.ceil(acc / 10) * 10, ...AXIS },
      yAxis: { type: "category", data: labels, inverse: true, ...AXIS, axisLabel: { ...AXIS.axisLabel, color: "#4b5259" } },
      series: [
        { type: "bar", stack: "w", data: base, itemStyle: { color: "transparent" }, silent: true, barCategoryGap: "28%" },
        {
          type: "bar",
          stack: "w",
          data: vals,
          itemStyle: { borderRadius: 2 },
          label: { show: true, position: "right", formatter: (p: { value: number }) => p.value.toFixed(1), color: "#4b5259", fontSize: 11 },
        },
      ],
    };
  }, [d]);
  return <EChart option={option} height={430} ariaLabel="Index waterfall" />;
}

function AboveAverage({ d }: { d: SupplierDetail }) {
  const option = useMemo(() => {
    const items = d.drivers; // sorted by points above average
    return {
      grid: { left: 150, right: 50, top: 8, bottom: 24 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (ps: { dataIndex: number }[]) => {
          const c = items[ps[0].dataIndex];
          return `<b>${c.label}</b><br/>${c.weight_pct}% × (${c.score} − ${c.mean_score.toFixed(1)}) = <b>${fmtSigned(c.points_above_average, 2)}</b> points`;
        },
      },
      xAxis: { type: "value", ...AXIS },
      yAxis: { type: "category", data: items.map((c) => c.label), inverse: true, ...AXIS, axisLabel: { ...AXIS.axisLabel, color: "#4b5259" } },
      series: [
        {
          type: "bar",
          data: items.map((c) => ({ value: c.points_above_average, itemStyle: { color: c.points_above_average >= 0 ? WARM : COOL, borderRadius: 2 } })),
          label: { show: true, position: "right", formatter: (p: { value: number }) => fmtSigned(p.value, 1), color: "#4b5259", fontSize: 11 },
          barCategoryGap: "28%",
        },
      ],
    };
  }, [d]);
  return <EChart option={option} height={430} ariaLabel="Points above average" />;
}
