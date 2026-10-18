import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MAX_COMPARE, useStore } from "../lib/store";
import { Modal } from "./ui";

/**
 * Edits the compare set, which the Compare, Analyses and Memo pages run on. When the set was restored from an
 * earlier session it opens pre-ticked so the user confirms it rather than running on a stale selection.
 */
export default function SupplierPicker({ title, min = 1, onClose }: { title: string; min?: number; onClose: () => void }) {
  const { data, compare, setCompareSet, compareRestored, confirmCompare } = useStore();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string[]>(compare);
  const restored = compareRestored && compare.length > 0;

  const nameOf = useMemo(() => new Map(data?.ids.map((id, i) => [id, i]) ?? []), [data]);
  const rows = useMemo(() => {
    if (!data) return [];
    const t = q.trim().toLowerCase();
    const match = (i: number) => !t || data.ids[i].toLowerCase().includes(t) || (data.names[i] ?? "").toLowerCase().includes(t);
    // Initially selected suppliers first, so they stay in place while ticking and unticking.
    const first = compare.map((id) => nameOf.get(id)).filter((i): i is number => i !== undefined && match(i));
    const rest: number[] = [];
    for (let i = 0; i < data.ids.length && rest.length < 200; i++) if (!compare.includes(data.ids[i]) && match(i)) rest.push(i);
    return [...first, ...rest];
  }, [q, data, compare, nameOf]);

  const toggle = (id: string) =>
    setSel((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : cur.length < MAX_COMPARE ? [...cur, id] : cur));
  const close = () => {
    // Dismissing the prompt keeps the restored set as it is; don't ask again on the next tab.
    if (restored) confirmCompare();
    onClose();
  };

  return (
    <Modal title={restored ? "Confirm suppliers" : title} onClose={close} width={560}>
      <p className="mb-2 text-xs text-ink-3">
        {restored
          ? `These ${compare.length} suppliers are from your last session. Keep them, untick any you don't want, or add others.`
          : "Suppliers go into the compare set."}{" "}
        Pick at least {min} (up to {MAX_COMPARE}).
      </p>
      <input className="input mb-2 w-full" placeholder="Search by ID or name" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      {!data ? (
        <p className="px-3 py-2 text-sm text-ink-3">Loading suppliers…</p>
      ) : (
        <ul className="max-h-[45vh] divide-y divide-line overflow-auto rounded-md border border-line" data-testid="supplier-picker">
          {rows.map((i) => {
            const id = data.ids[i];
            const on = sel.includes(id);
            return (
              <li key={id}>
                <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-canvas">
                  <input type="checkbox" className="accent-[var(--color-accent)]" checked={on} disabled={!on && sel.length >= MAX_COMPARE} onChange={() => toggle(id)} />
                  <span className="font-medium">{id}</span>
                  <span className="truncate text-ink-2">{data.names[i]}</span>
                  <span className="num ml-auto text-xs text-ink-3">{data.index[i]?.toFixed(2)}</span>
                </label>
              </li>
            );
          })}
          {!rows.length && <li className="px-3 py-2 text-sm text-ink-3">No matching suppliers.</li>}
        </ul>
      )}
      <div className="mt-3 flex items-center gap-2">
        <button className="btn-ghost text-xs" onClick={() => nav("/explore")}>Browse in Explore instead</button>
        <span className="ml-auto text-xs text-ink-3">{sel.length} selected</span>
        {sel.length > 0 && <button className="btn-ghost text-xs" onClick={() => setSel([])}>Clear</button>}
        <button className="btn" onClick={close}>Cancel</button>
        <button
          className="btn-primary"
          disabled={sel.length < min}
          onClick={() => {
            setCompareSet(sel);
            onClose();
          }}
          data-testid="confirm-suppliers"
        >
          {restored ? "Confirm" : "Use selected"}
        </button>
      </div>
    </Modal>
  );
}
