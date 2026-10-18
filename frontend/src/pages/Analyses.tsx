import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { MAX_COMPARE, useStore } from "../lib/store";
import type { SuppliersData } from "../lib/api";
import { Blocks, type Block } from "../components/PluginBlocks";
import { Badge, Modal, Spinner } from "../components/ui";

type ParamSpec = {
  key: string;
  label: string;
  type: "number" | "select" | "boolean";
  default: number | string | boolean;
  help?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string }[];
};
type PluginInfo = {
  id: string;
  name: string;
  description: string;
  version: string;
  available: boolean;
  unavailable_reason: string;
  min_suppliers: number;
  max_suppliers: number;
  params: ParamSpec[];
};
type RunResult = { plugin_name: string; title: string; summary: string; assumptions: string[]; blocks: Block[]; ids: string[]; params: Record<string, unknown> };

export default function Analyses() {
  const { compare, openChat, addCompare, data } = useStore();
  const nav = useNavigate();
  const [search, setSearch] = useSearchParams();
  const [list, setList] = useState<PluginInfo[] | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<RunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);

  const pluginId = search.get("plugin") ?? list?.find((p) => p.available)?.id ?? "";
  const urlIds = search.get("ids");
  const ids = useMemo(() => (urlIds ? urlIds.split(",").filter(Boolean) : compare), [urlIds, compare]);
  const plugin = list?.find((p) => p.id === pluginId) ?? null;

  useEffect(() => {
    api.get<PluginInfo[]>("/api/plugins").then(setList).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    if (plugin) setValues(Object.fromEntries(plugin.params.map((p) => [p.key, p.default])));
    setResult(null);
  }, [plugin]);

  async function run() {
    if (!plugin) return;
    setBusy(true);
    setErr(null);
    try {
      setResult(await api.post<RunResult>(`/api/plugins/${plugin.id}/run`, { ids, params: values }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    // Opened from the assistant or the Compare page with suppliers in the URL: run straight away.
    if (plugin?.available && urlIds && !result && !busy) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plugin, urlIds]);

  // Analyses need suppliers: prompt for them as soon as the tab opens with none selected.
  useEffect(() => {
    if (list && !ids.length) setPicking(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list]);

  const choose = (id: string) => setSearch((s) => {
    const n = new URLSearchParams(s);
    n.set("plugin", id);
    return n;
  });

  if (!list) return <div className="p-6">{err ? <p className="text-sm text-lv-high">{err}</p> : <Spinner label="Loading analyses…" />}</div>;

  const tooFew = plugin ? ids.length < plugin.min_suppliers : true;
  const tooMany = plugin ? ids.length > plugin.max_suppliers : false;

  return (
    <div className="mx-auto grid max-w-[1400px] grid-cols-[320px_1fr] gap-4 p-4">
      {picking && data && (
        <SupplierPicker
          data={data}
          selected={ids}
          min={plugin?.min_suppliers ?? 1}
          onClose={() => setPicking(false)}
          onExplore={() => nav("/explore")}
          onConfirm={(picked) => {
            addCompare(picked);
            setPicking(false);
          }}
        />
      )}
      <aside className="space-y-4">
        <section className="card p-4">
          <h1 className="text-lg font-semibold">Risk analyses</h1>
          <p className="text-xs text-ink-3">Analysis plugins run on the suppliers you select. New plugins appear here automatically.</p>
          <ul className="mt-3 space-y-1.5">
            {list.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => choose(p.id)}
                  disabled={!p.available}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm ${p.id === pluginId ? "border-accent bg-accent-soft" : "border-line hover:bg-canvas"} disabled:opacity-50`}
                  data-testid={`plugin-${p.id}`}
                >
                  <span className="font-medium">{p.name}</span> <span className="text-xs text-ink-3">v{p.version}</span>
                  {!p.available && <span className="block text-xs text-lv-high">Unavailable: {p.unavailable_reason}</span>}
                </button>
              </li>
            ))}
          </ul>
        </section>

        {plugin && (
          <section className="card space-y-3 p-4">
            <p className="text-xs text-ink-2">{plugin.description}</p>
            <div className="text-sm">
              <div className="mb-1 flex items-center justify-between font-medium">
                Suppliers ({ids.length})
                {urlIds && <button className="btn-ghost text-xs" onClick={() => setSearch({ plugin: plugin.id })}>use compare set</button>}
              </div>
              {ids.length ? (
                <div className="flex flex-wrap gap-1">{ids.map((id) => <Badge key={id}>{id}</Badge>)}</div>
              ) : (
                <p className="text-xs text-ink-3">No suppliers selected.</p>
              )}
              {!urlIds && (
                <button className="btn-ghost mt-1 text-xs" onClick={() => setPicking(true)} data-testid="pick-suppliers">
                  {ids.length ? "Add suppliers" : "Select suppliers"}
                </button>
              )}
              {tooMany && <p className="mt-1 text-xs text-lv-high">At most {plugin.max_suppliers} suppliers.</p>}
            </div>
            {plugin.params.map((p) => (
              <ParamField key={p.key} spec={p} value={values[p.key]} onChange={(v) => setValues((cur) => ({ ...cur, [p.key]: v }))} />
            ))}
            <button className="btn-primary w-full justify-center" disabled={busy || tooFew || tooMany || !plugin.available} onClick={run} data-testid="run-analysis">
              {busy ? "Running…" : `Run ${plugin.name.toLowerCase()}`}
            </button>
            {!ids.length && <button className="btn w-full justify-center" onClick={() => setPicking(true)}>Select suppliers</button>}
            {err && <p className="text-sm text-lv-high">{err}</p>}
          </section>
        )}
      </aside>

      <main className="min-w-0 space-y-4">
        {busy && <div className="card p-6"><Spinner label="Running analysis…" /></div>}
        {!busy && !result && (
          <div className="card flex h-60 items-center justify-center p-6 text-center text-sm text-ink-3">
            Choose an analysis and run it on your selected suppliers.
          </div>
        )}
        {result && !busy && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold">{result.title}</h2>
              <button className="btn ml-auto" onClick={() => openChat(result.ids, `Explain the ${result.plugin_name.toLowerCase()} for these suppliers.`)}>
                Ask about this
              </button>
            </div>
            <details className="card px-4 py-2 text-xs text-ink-2" open>
              <summary className="cursor-pointer font-medium text-ink">Assumptions</summary>
              <ul className="ml-4 mt-1 list-disc space-y-0.5">{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            </details>
            <div data-testid="analysis-result">
              <Blocks blocks={result.blocks} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function SupplierPicker({ data, selected, min, onClose, onExplore, onConfirm }: {
  data: SuppliersData;
  selected: string[];
  min: number;
  onClose: () => void;
  onExplore: () => void;
  onConfirm: (ids: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const room = MAX_COMPARE - selected.length;
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    const out: number[] = [];
    for (let i = 0; i < data.ids.length && out.length < 200; i++) {
      if (selected.includes(data.ids[i])) continue;
      if (!t || data.ids[i].toLowerCase().includes(t) || (data.names[i] ?? "").toLowerCase().includes(t)) out.push(i);
    }
    return out;
  }, [q, data, selected]);
  const toggle = (id: string) =>
    setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : cur.length < room ? [...cur, id] : cur));
  const total = selected.length + picked.length;

  return (
    <Modal title="Select suppliers to analyse" onClose={onClose} width={560}>
      <p className="mb-2 text-xs text-ink-3">
        Analyses run on the compare set. Pick at least {min} supplier{min === 1 ? "" : "s"} (up to {MAX_COMPARE} in total).
      </p>
      <input className="input mb-2 w-full" placeholder="Search by ID or name" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <ul className="max-h-[45vh] divide-y divide-line overflow-auto rounded-md border border-line">
        {rows.map((i) => {
          const id = data.ids[i];
          const on = picked.includes(id);
          return (
            <li key={id}>
              <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-canvas">
                <input type="checkbox" className="accent-[var(--color-accent)]" checked={on} disabled={!on && picked.length >= room} onChange={() => toggle(id)} />
                <span className="font-medium">{id}</span>
                <span className="truncate text-ink-2">{data.names[i]}</span>
                <span className="num ml-auto text-xs text-ink-3">{data.index[i]?.toFixed(2)}</span>
              </label>
            </li>
          );
        })}
        {!rows.length && <li className="px-3 py-2 text-sm text-ink-3">No matching suppliers.</li>}
      </ul>
      <div className="mt-3 flex items-center gap-2">
        <button className="btn-ghost text-xs" onClick={onExplore}>Browse in Explore instead</button>
        <span className="ml-auto text-xs text-ink-3">{total} selected</span>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={!picked.length || total < min} onClick={() => onConfirm(picked)} data-testid="confirm-suppliers">
          Use selected
        </button>
      </div>
    </Modal>
  );
}

function ParamField({ spec, value, onChange }: { spec: ParamSpec; value: unknown; onChange: (v: unknown) => void }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{spec.label}</span>
      {spec.type === "select" ? (
        <select className="input w-full" value={String(value ?? spec.default)} onChange={(e) => onChange(e.target.value)}>
          {spec.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      ) : spec.type === "boolean" ? (
        <input type="checkbox" className="accent-[var(--color-accent)]" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
      ) : (
        <input
          className="input w-full"
          type="number"
          min={spec.min}
          max={spec.max}
          step={spec.step}
          value={String(value ?? spec.default)}
          onChange={(e) => onChange(e.target.value === "" ? spec.default : Number(e.target.value))}
        />
      )}
      {spec.help && <span className="mt-0.5 block text-xs text-ink-3">{spec.help}</span>}
    </label>
  );
}
