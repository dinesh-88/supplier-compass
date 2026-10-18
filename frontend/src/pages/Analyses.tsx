import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import SupplierPicker from "../components/SupplierPicker";
import { Blocks, type Block } from "../components/PluginBlocks";
import { Badge, Spinner } from "../components/ui";

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
  const { compare, openChat } = useStore();
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
      {picking && <SupplierPicker title="Select suppliers to analyse" min={plugin?.min_suppliers ?? 1} onClose={() => setPicking(false)} />}
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
