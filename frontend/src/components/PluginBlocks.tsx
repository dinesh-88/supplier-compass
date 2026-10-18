import { useMemo, useState } from "react";
import { levelColor } from "../lib/levels";
import EChart from "./EChart";
import Markdown from "./Markdown";
import { Tile } from "./ui";

/** Generic renderer for risk-analysis plugin output (see backend/app/plugins/base.py). */
export type TreeNode = {
  id: string;
  label: string;
  type: "gate" | "basic";
  gate?: "OR" | "AND" | "VOTE";
  k?: number;
  probability: number;
  children?: TreeNode[];
  column?: string;
  original?: string;
  score?: number;
  level?: string;
  repeated?: boolean | null;
};

export type Block =
  | { type: "metrics"; items: { label: string; value: string; sub?: string }[] }
  | { type: "text"; markdown: string }
  | { type: "table"; title?: string; columns: string[]; rows: (string | number)[][]; note?: string }
  | { type: "chart"; title?: string; option: Record<string, unknown>; height?: number }
  | { type: "fault_tree"; title?: string; tree: TreeNode }
  | { type: "tabs"; tabs: { label: string; blocks: Block[] }[] };

export function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <div className="space-y-4">
      {blocks.map((b, i) => (
        <BlockView key={i} block={b} />
      ))}
    </div>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case "metrics":
      return (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          {block.items.map((m) => (
            <Tile key={m.label} label={m.label} value={<span className="text-lg">{m.value}</span>} sub={m.sub} />
          ))}
        </div>
      );
    case "text":
      return (
        <div className="card p-4 text-sm leading-relaxed">
          <Markdown text={block.markdown} />
        </div>
      );
    case "table":
      return (
        <section className="card overflow-x-auto p-4">
          {block.title && <h3 className="mb-2 font-semibold">{block.title}</h3>}
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-3">
                {block.columns.map((c) => (
                  <th key={c} className="border-b border-line py-1 pr-3 font-medium">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((r, i) => (
                <tr key={i} className="border-b border-line last:border-0">
                  {r.map((v, j) => (
                    <td key={j} className="num py-1 pr-3 align-top">{v}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {block.note && <p className="mt-2 text-xs text-ink-3">{block.note}</p>}
        </section>
      );
    case "chart":
      return (
        <section className="card p-4">
          {block.title && <h3 className="mb-1 font-semibold">{block.title}</h3>}
          <EChart option={block.option} height={block.height ?? 280} ariaLabel={block.title ?? "chart"} />
        </section>
      );
    case "fault_tree":
      return <FaultTree title={block.title} tree={block.tree} />;
    case "tabs":
      return <Tabs tabs={block.tabs} />;
  }
}

function Tabs({ tabs }: { tabs: { label: string; blocks: Block[] }[] }) {
  const [i, setI] = useState(0);
  const cur = tabs[Math.min(i, tabs.length - 1)];
  return (
    <section>
      <div className="mb-3 flex flex-wrap gap-1 border-b border-line" role="tablist">
        {tabs.map((t, k) => (
          <button
            key={t.label}
            role="tab"
            aria-selected={k === i}
            onClick={() => setI(k)}
            className={`-mb-px rounded-t-md border px-3 py-1.5 text-sm ${k === i ? "border-line border-b-surface bg-surface font-medium text-accent-strong" : "border-transparent text-ink-2 hover:text-ink"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {cur && <Blocks blocks={cur.blocks} />}
    </section>
  );
}

const pct = (p: number) => `${(p * 100).toFixed(p < 0.01 ? 2 : 1)}%`;

function FaultTree({ title, tree }: { title?: string; tree: TreeNode }) {
  const { option, leaves } = useMemo(() => {
    let leafCount = 0;
    const conv = (n: TreeNode): Record<string, unknown> => {
      if (n.type === "basic") {
        leafCount++;
        const color = levelColor(n.level ?? "");
        return {
          name: `${n.label}${n.repeated ? " (repeated)" : ""}`,
          value: n.probability,
          raw: n,
          symbol: "circle",
          symbolSize: 12,
          itemStyle: { color, borderColor: "#fff", borderWidth: 2 },
          label: {
            formatter: `{name|${n.label}${n.repeated ? " ↺" : ""}}\n{sub|score ${n.score} ${n.level} · p ${pct(n.probability)}}`,
            rich: { name: { fontSize: 12, color: "#16191d" }, sub: { fontSize: 11, color: "#737a82" } },
          },
        };
      }
      const g = n.gate === "VOTE" ? `${n.k}/${n.children?.length}` : n.gate;
      return {
        name: n.label,
        value: n.probability,
        raw: n,
        symbol: n.gate === "AND" ? "roundRect" : n.gate === "OR" ? "triangle" : "diamond",
        symbolRotate: n.gate === "OR" ? 270 : 0,
        symbolSize: n.id === tree.id ? 18 : 15,
        itemStyle: { color: "#00727f" },
        label: {
          ...(n.id === tree.id
            ? { position: "left", align: "right", verticalAlign: "middle", distance: 10 }
            : { position: "top", align: "center", verticalAlign: "bottom", distance: 6 }),
          backgroundColor: "rgba(255,255,255,0.94)",
          padding: [3, 5],
          borderRadius: 4,
          borderColor: "#e3e5e8",
          borderWidth: 1,
          formatter:
            n.id === tree.id
              ? `{gate|${g}} {name|${n.label}}\n{p|${pct(n.probability)} per year}`
              : `{gate|${g}} {name|${n.label}}  {p|${pct(n.probability)}}`,
          rich: {
            gate: { fontSize: 10, color: "#fff", backgroundColor: "#00727f", padding: [1, 4], borderRadius: 3, fontWeight: 600 },
            name: { fontSize: 12, color: "#16191d", fontWeight: 600 },
            p: { fontSize: 12, color: "#005a64", fontWeight: 700 },
          },
        },
        children: (n.children ?? []).map(conv),
      };
    };
    const data = conv(tree);
    const opt = {
      tooltip: {
        trigger: "item",
        formatter: (p: { data: { raw: TreeNode } }) => {
          const n = p.data.raw;
          if (n.type === "basic")
            return `<b>${n.label}</b><br/>${n.original}: score ${n.score} (${n.level})<br/>probability ${pct(n.probability)}${n.repeated ? "<br/>repeated event (same cause as elsewhere)" : ""}`;
          const gate = n.gate === "OR" ? "OR: happens if any input happens" : n.gate === "AND" ? "AND: needs all inputs" : `${n.k} of ${n.children?.length} inputs`;
          return `<b>${n.label}</b><br/>${gate}<br/>probability ${pct(n.probability)}`;
        },
      },
      series: [
        {
          type: "tree",
          data: [data],
          orient: "LR",
          top: 40,
          bottom: 20,
          left: 250,
          right: 260,
          initialTreeDepth: -1,
          expandAndCollapse: true,
          roam: false,
          lineStyle: { color: "#c3c8ce", width: 1.5, curveness: 0.4 },
          label: { position: "right", verticalAlign: "middle", align: "left", distance: 8 },
          leaves: { label: { position: "right", align: "left" } },
          emphasis: { focus: "ancestor" },
          animationDuration: 300,
        },
      ],
    };
    return { option: opt, leaves: leafCount };
  }, [tree]);
  return (
    <section className="card p-4" data-testid="fault-tree">
      <div className="mb-1 flex flex-wrap items-center gap-3">
        {title && <h3 className="font-semibold">{title}</h3>}
        <span className="text-xs text-ink-3">
          ▷ OR gate (any input) · ▢ AND gate (all inputs) · ● basic event coloured by score level · ↺ repeated event · click a gate to collapse
        </span>
      </div>
      <EChart option={option} height={Math.max(380, leaves * 54)} ariaLabel="Fault tree" />
    </section>
  );
}
